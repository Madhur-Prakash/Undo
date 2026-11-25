"""Manual snapshots: named, metadata-only records of a root's state.

A snapshot references existing versions/blobs; no content is copied. It is
transactionally consistent at the metadata level (created in one write
transaction). The preceding scan is *not* an atomic filesystem snapshot: files
modified while the scan runs are captured at whatever state they had when read.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from undo_core.database.models import File, Root, Snapshot, SnapshotEntry, Version
from undo_core.database.repositories import SnapshotRepository
from undo_core.domain import (
    SnapshotChange,
    SnapshotDetail,
    SnapshotDiff,
    SnapshotEntryInfo,
    SnapshotInfo,
)
from undo_core.utils.errors import ConflictError, InvalidInputError, NotFoundError
from undo_core.utils.timeutil import to_aware, utcnow


def snapshot_info(snapshot: Snapshot, root_path: str) -> SnapshotInfo:
    return SnapshotInfo(
        id=snapshot.id,
        name=snapshot.name,
        description=snapshot.description,
        created_at=to_aware(snapshot.created_at),  # type: ignore[arg-type]
        root_id=snapshot.root_id,
        root_path=root_path,
        file_count=snapshot.file_count,
        total_size=snapshot.total_size,
    )


def _root_path(session: Session, root_id: int) -> str:
    root = session.get(Root, root_id)
    return root.absolute_path if root else "?"


def create_snapshot(
    session: Session,
    root_id: int,
    name: str,
    description: str | None,
    *,
    scan_started_at: datetime | None = None,
) -> SnapshotInfo:
    name = name.strip()
    if not name:
        raise InvalidInputError("Snapshot name must not be empty")
    if session.scalar(select(Snapshot).where(Snapshot.root_id == root_id, Snapshot.name == name)):
        raise ConflictError(f"A snapshot named {name!r} already exists for this root")
    snapshot = Snapshot(name=name, description=description, root_id=root_id, created_at=utcnow())
    session.add(snapshot)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"A snapshot named {name!r} already exists for this root") from exc
    rows = session.execute(
        select(File.id, Version.id, Version.relative_path, Version.blob_hash, Version.file_size)
        .join(Version, Version.id == File.latest_version_id)
        .where(
            File.root_id == root_id,
            File.deleted_at.is_(None),
            Version.blob_hash.is_not(None),
        )
    ).all()
    total = 0
    for file_id, version_id, rel, blob_hash, size in rows:
        session.add(
            SnapshotEntry(
                snapshot_id=snapshot.id,
                file_id=file_id,
                version_id=version_id,
                relative_path=rel,
                blob_hash=blob_hash,
                file_size=size,
            )
        )
        total += size
    snapshot.file_count = len(rows)
    snapshot.total_size = total
    if scan_started_at is not None:
        # Tag versions captured by the pre-snapshot scan.
        file_ids = select(File.id).where(File.root_id == root_id).scalar_subquery()
        session.execute(
            update(Version)
            .where(
                Version.file_id.in_(file_ids),
                Version.timestamp >= scan_started_at,
                Version.snapshot_id.is_(None),
            )
            .values(snapshot_id=snapshot.id)
        )
    session.flush()
    return snapshot_info(snapshot, _root_path(session, root_id))


def get_snapshot(session: Session, snapshot_id: int) -> Snapshot:
    snapshot = SnapshotRepository(session).get(snapshot_id)
    if snapshot is None:
        raise NotFoundError(f"Snapshot {snapshot_id} not found")
    return snapshot


def find_snapshot(session: Session, ref: str) -> Snapshot:
    """Resolve a snapshot by numeric id or by (unique) name.

    The exact name wins. Otherwise names are compared ignoring case, spaces, "-" and "_", so
    `try1`, `Try-1` and `"try 1"` all find a snapshot named "try 1".
    """
    ref = ref.strip()
    if ref.isdigit():
        return get_snapshot(session, int(ref))
    matches = session.scalars(select(Snapshot).where(Snapshot.name == ref)).all()
    if not matches:

        def loose(name: str) -> str:
            return "".join(ch for ch in name.casefold() if ch not in " -_")

        wanted = loose(ref)
        matches = [s for s in session.scalars(select(Snapshot)) if loose(s.name) == wanted]
    if not matches:
        existing = list(session.scalars(select(Snapshot).order_by(Snapshot.id)))
        if existing:
            listed = ", ".join(f"{s.id} ({s.name})" for s in existing)
            hint = (
                f" Available: {listed}. Use the id, or put names with spaces in quotes, "
                f'e.g. undo snapshot show "{existing[0].name}".'
            )
        else:
            hint = " There are no snapshots yet (undo snapshot create --name NAME)."
        raise NotFoundError(f"Snapshot {ref!r} not found.{hint}")
    if len(matches) > 1:
        ids = ", ".join(str(s.id) for s in matches)
        raise InvalidInputError(f"Several snapshots match {ref!r} (ids {ids}); use the numeric id")
    return matches[0]


def rename_snapshot(
    session: Session,
    snapshot_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Snapshot:
    """Change a snapshot's name and/or description. Names are unique within a folder (root)."""
    snapshot = get_snapshot(session, snapshot_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise InvalidInputError("Snapshot name must not be empty")
        if name != snapshot.name:
            clash = session.scalar(
                select(Snapshot).where(
                    Snapshot.root_id == snapshot.root_id,
                    Snapshot.name == name,
                    Snapshot.id != snapshot.id,
                )
            )
            if clash is not None:
                raise ConflictError(f"A snapshot named {name!r} already exists for this root")
            snapshot.name = name
    if description is not None:
        snapshot.description = description.strip() or None
    return snapshot


def list_snapshots(session: Session, root_id: int | None) -> list[SnapshotInfo]:
    roots = {r.id: r.absolute_path for r in session.scalars(select(Root))}
    return [
        snapshot_info(s, roots.get(s.root_id, "?"))
        for s in SnapshotRepository(session).list(root_id)
    ]


def entries_info(session: Session, snapshot_id: int) -> list[SnapshotEntryInfo]:
    return [
        SnapshotEntryInfo(
            file_id=e.file_id,
            version_id=e.version_id,
            relative_path=e.relative_path,
            blob_hash=e.blob_hash,
            file_size=e.file_size,
        )
        for e in SnapshotRepository(session).entries(snapshot_id)
    ]


def snapshot_detail(session: Session, snapshot_id: int) -> SnapshotDetail:
    snapshot = get_snapshot(session, snapshot_id)
    return SnapshotDetail(
        snapshot=snapshot_info(snapshot, _root_path(session, snapshot.root_id)),
        entries=entries_info(session, snapshot_id),
    )


def diff_snapshots(session: Session, a_id: int, b_id: int) -> SnapshotDiff:
    a = get_snapshot(session, a_id)
    b = get_snapshot(session, b_id)
    a_entries = {e.file_id: e for e in SnapshotRepository(session).entries(a_id)}
    b_entries = {e.file_id: e for e in SnapshotRepository(session).entries(b_id)}
    added, removed, modified = [], [], []
    unchanged = 0
    for fid, eb in b_entries.items():
        ea = a_entries.get(fid)
        if ea is None:
            added.append(
                SnapshotChange(
                    relative_path=eb.relative_path, b_version_id=eb.version_id, b_size=eb.file_size
                )
            )
        elif ea.blob_hash != eb.blob_hash or ea.relative_path != eb.relative_path:
            label = (
                eb.relative_path
                if ea.relative_path == eb.relative_path
                else f"{ea.relative_path} -> {eb.relative_path}"
            )
            modified.append(
                SnapshotChange(
                    relative_path=label,
                    a_version_id=ea.version_id,
                    b_version_id=eb.version_id,
                    a_size=ea.file_size,
                    b_size=eb.file_size,
                )
            )
        else:
            unchanged += 1
    for fid, ea in a_entries.items():
        if fid not in b_entries:
            removed.append(
                SnapshotChange(
                    relative_path=ea.relative_path, a_version_id=ea.version_id, a_size=ea.file_size
                )
            )
    key = lambda c: c.relative_path  # noqa: E731
    return SnapshotDiff(
        a=snapshot_info(a, _root_path(session, a.root_id)),
        b=snapshot_info(b, _root_path(session, b.root_id)),
        added=sorted(added, key=key),
        removed=sorted(removed, key=key),
        modified=sorted(modified, key=key),
        unchanged=unchanged,
    )


def delete_snapshot(session: Session, snapshot_id: int) -> SnapshotInfo:
    snapshot = get_snapshot(session, snapshot_id)
    info = snapshot_info(snapshot, _root_path(session, snapshot.root_id))
    session.execute(
        update(Version).where(Version.snapshot_id == snapshot_id).values(snapshot_id=None)
    )
    session.query(SnapshotEntry).filter(SnapshotEntry.snapshot_id == snapshot_id).delete()
    session.delete(snapshot)
    return info
