"""Removing history on purpose: one file, one folder, older versions only, or single versions.

Two entry points, both planned first (so callers can show a dry run) and then applied in one
write transaction:

* :func:`plan_forget` - every version of the given files, or only those older than ``before``.
  With ``before``, the latest version of each file is always kept.
* :func:`plan_delete_versions` - exactly the listed versions. The latest version of a file
  cannot be deleted this way; forgetting the file is the explicit way to drop everything.

Versions referenced by a snapshot are never removed here (``ON DELETE RESTRICT`` would refuse
anyway); they are reported so the user knows to delete the snapshot first.

:func:`apply_forget` deletes the versions, re-links ``parent_version_id`` to the nearest kept
ancestor, repairs ``latest_version_id`` / ``version_count``, and removes file records that have
no versions left. Stored content is not deleted directly: garbage collection frees blobs that
nothing references any more.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from undo_core.database.models import File, PathHistory, SkipRecord, SnapshotEntry, Version
from undo_core.utils.errors import ConflictError, InvalidInputError, NotFoundError


@dataclass
class ForgetPlan:
    remove: set[int] = field(default_factory=set)
    files_examined: int = 0
    files_affected: set[int] = field(default_factory=set)
    files_emptied: set[int] = field(default_factory=set)  # every version goes: record removed
    kept_in_snapshots: int = 0


def _snapshot_versions(session: Session, version_ids: list[int]) -> set[int]:
    out: set[int] = set()
    for i in range(0, len(version_ids), 500):
        batch = version_ids[i : i + 500]
        out.update(
            session.scalars(
                select(SnapshotEntry.version_id).where(SnapshotEntry.version_id.in_(batch))
            )
        )
    return out


def _versions_by_file(
    session: Session, file_ids: list[int]
) -> dict[int, list[tuple[int, datetime]]]:
    """Each file's versions as (id, timestamp), newest first."""
    out: dict[int, list[tuple[int, datetime]]] = defaultdict(list)
    for i in range(0, len(file_ids), 500):
        batch = file_ids[i : i + 500]
        rows = session.execute(
            select(Version.file_id, Version.id, Version.timestamp)
            .where(Version.file_id.in_(batch))
            .order_by(Version.file_id, Version.timestamp.desc(), Version.id.desc())
        ).all()
        for file_id, vid, ts in rows:
            out[file_id].append((vid, ts))
    return out


def plan_forget(session: Session, file_ids: list[int], *, before: datetime | None) -> ForgetPlan:
    plan = ForgetPlan(files_examined=len(file_ids))
    by_file = _versions_by_file(session, file_ids)
    protected = _snapshot_versions(session, [vid for vs in by_file.values() for vid, _ in vs])
    for file_id, versions in by_file.items():
        removable: list[int] = []
        for index, (vid, ts) in enumerate(versions):
            if before is not None and (index == 0 or ts >= before):
                continue  # keep the latest version, and everything from `before` on
            if vid in protected:
                plan.kept_in_snapshots += 1
                continue
            removable.append(vid)
        if removable:
            plan.remove.update(removable)
            plan.files_affected.add(file_id)
            if len(removable) == len(versions):
                plan.files_emptied.add(file_id)
    return plan


def plan_delete_versions(session: Session, version_ids: list[int]) -> ForgetPlan:
    plan = ForgetPlan()
    wanted = sorted(set(version_ids))
    if not wanted:
        raise InvalidInputError("No version ids given")
    rows = {
        vid: (file_id, rel)
        for vid, file_id, rel in session.execute(
            select(Version.id, Version.file_id, Version.relative_path).where(Version.id.in_(wanted))
        ).all()
    }
    missing = [v for v in wanted if v not in rows]
    if missing:
        raise NotFoundError(f"Version(s) not found: {', '.join(map(str, missing))}")
    file_ids = sorted({file_id for file_id, _ in rows.values()})
    latest = dict(
        session.execute(select(File.id, File.latest_version_id).where(File.id.in_(file_ids))).all()
    )
    for vid, (file_id, rel) in rows.items():
        if latest.get(file_id) == vid:
            raise InvalidInputError(
                f"v{vid} is the latest version of {rel}, which keeps the file restorable. "
                f"To remove the file's whole history use `undo forget {rel}` (or Delete history in the app)."
            )
    protected = _snapshot_versions(session, wanted)
    if protected:
        ids = ", ".join(f"v{v}" for v in sorted(protected))
        raise ConflictError(f"{ids} belong to a snapshot; delete the snapshot first")
    plan.remove = set(wanted)
    plan.files_examined = len(file_ids)
    plan.files_affected = set(file_ids)
    return plan


def apply_forget(session: Session, plan: ForgetPlan) -> set[int]:
    """Delete the planned versions. Returns the ids of file records that were removed."""
    if not plan.remove:
        return set()
    affected = sorted(plan.files_affected)

    # Re-link children whose parent is being removed to the nearest kept ancestor.
    parents: dict[int, int | None] = {}
    for i in range(0, len(affected), 500):
        batch = affected[i : i + 500]
        parents.update(
            session.execute(
                select(Version.id, Version.parent_version_id).where(Version.file_id.in_(batch))
            ).all()
        )

    def kept_ancestor(vid: int | None) -> int | None:
        hops = 0
        while vid is not None and vid in plan.remove and hops < 100_000:
            vid = parents.get(vid)
            hops += 1
        return vid

    for vid, parent in parents.items():
        if vid in plan.remove or parent is None or parent not in plan.remove:
            continue
        session.execute(
            update(Version).where(Version.id == vid).values(parent_version_id=kept_ancestor(parent))
        )

    ids = sorted(plan.remove)
    for i in range(0, len(ids), 500):
        session.execute(delete(Version).where(Version.id.in_(ids[i : i + 500])))

    removed_files: set[int] = set()
    for file in session.scalars(select(File).where(File.id.in_(affected))):
        remaining = (
            session.execute(
                select(Version.id)
                .where(Version.file_id == file.id)
                .order_by(Version.timestamp.desc(), Version.id.desc())
            )
            .scalars()
            .all()
        )
        if not remaining:
            removed_files.add(file.id)
            continue
        if file.latest_version_id not in remaining:
            file.latest_version_id = remaining[0]
            # Forget size/mtime so the next scan re-checks the file on disk.
            file.last_size = None
            file.last_mtime_ns = None
        file.version_count = len(remaining)
    if removed_files:
        doomed = sorted(removed_files)
        for i in range(0, len(doomed), 500):
            batch = doomed[i : i + 500]
            session.execute(delete(PathHistory).where(PathHistory.file_id.in_(batch)))
            session.execute(delete(File).where(File.id.in_(batch)))
    return removed_files


def skip_records_cleanup(session: Session, root_id: int, prefix_key: str | None) -> None:
    """Drop skip records below a forgotten folder; they are rebuilt by the next scan."""
    stmt = delete(SkipRecord).where(SkipRecord.root_id == root_id)
    if prefix_key:
        stmt = stmt.where(
            (SkipRecord.path_key == prefix_key)
            | SkipRecord.path_key.startswith(prefix_key + "/", autoescape=True)
        )
    session.execute(stmt)


__all__ = [
    "ForgetPlan",
    "apply_forget",
    "plan_delete_versions",
    "plan_forget",
    "skip_records_cleanup",
]
