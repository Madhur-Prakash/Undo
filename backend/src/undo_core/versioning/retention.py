"""Retention policies.

Always kept, regardless of policy:
* the latest version of every file (its current state, or its DELETE marker),
* the latest *content* version of every file (so deleted files stay recoverable),
* every version referenced by a manual snapshot.

With ``keep_all`` the rule-based pruning is disabled; only the storage quota
(``max_storage_bytes``) can then remove versions. Otherwise a version is kept
when *any* configured rule keeps it (keep_last, keep_days, daily, weekly).
Removing a version row never removes data directly; garbage collection later
deletes blobs that no longer have any reference.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from undo_core.config.settings import RetentionSettings
from undo_core.database.models import Blob, File, Operation, SnapshotEntry, Version
from undo_core.database.repositories import MetaRepository
from undo_core.utils.timeutil import utcnow


@dataclass
class RetentionPlan:
    remove: set[int] = field(default_factory=set)
    files_examined: int = 0
    versions_examined: int = 0
    files_affected: int = 0
    estimated_reclaim_bytes: int = 0


@dataclass(frozen=True)
class _V:
    id: int
    file_id: int
    timestamp: datetime
    operation: str
    blob_hash: str | None
    parent_id: int | None


def _rule_keep(versions: list[_V], policy: RetentionSettings, now: datetime) -> set[int]:
    """Versions kept by time/count rules. ``versions`` is newest-first."""
    keep: set[int] = set()
    if policy.keep_last:
        keep.update(v.id for v in versions[: policy.keep_last])
    if policy.keep_days:
        cutoff = now - timedelta(days=policy.keep_days)
        keep.update(v.id for v in versions if v.timestamp >= cutoff)
    if policy.daily_days:
        cutoff = now - timedelta(days=policy.daily_days)
        seen_days: set[str] = set()
        for v in versions:
            if v.timestamp < cutoff:
                break
            day = v.timestamp.date().isoformat()
            if day not in seen_days:
                seen_days.add(day)
                keep.add(v.id)
    if policy.weekly_weeks:
        cutoff = now - timedelta(weeks=policy.weekly_weeks)
        seen_weeks: set[tuple[int, int]] = set()
        for v in versions:
            if v.timestamp < cutoff:
                break
            iso = v.timestamp.isocalendar()
            week = (iso[0], iso[1])
            if week not in seen_weeks:
                seen_weeks.add(week)
                keep.add(v.id)
    return keep


def plan_retention(
    session: Session,
    policy: RetentionSettings,
    *,
    now: datetime | None = None,
    stored_bytes: int = 0,
) -> RetentionPlan:
    now = now or utcnow()
    plan = RetentionPlan()
    protected: set[int] = set(session.scalars(select(SnapshotEntry.version_id)))
    by_file: dict[int, list[_V]] = defaultdict(list)
    rows = session.execute(
        select(
            Version.id,
            Version.file_id,
            Version.timestamp,
            Version.operation,
            Version.blob_hash,
            Version.parent_version_id,
        ).order_by(Version.file_id, Version.timestamp.desc(), Version.id.desc())
    ).all()
    for r in rows:
        by_file[r[1]].append(_V(r[0], r[1], r[2], r[3], r[4], r[5]))
    plan.files_examined = len(by_file)
    plan.versions_examined = len(rows)

    candidates: list[_V] = []
    for versions in by_file.values():
        always = {versions[0].id}
        latest_content = next((v for v in versions if v.blob_hash), None)
        if latest_content:
            always.add(latest_content.id)
        if policy.keep_all:
            keep = {v.id for v in versions}
        else:
            keep = _rule_keep(versions, policy, now)
        for v in versions:
            if v.id in always or v.id in protected:
                continue
            if v.id not in keep:
                plan.remove.add(v.id)
            else:
                candidates.append(v)

    # Reference counts after rule-based removal, to estimate reclaimable space.
    refcount: dict[str, int] = defaultdict(int)
    for versions in by_file.values():
        for v in versions:
            if v.blob_hash and v.id not in plan.remove:
                refcount[v.blob_hash] += 1
    for h in session.scalars(select(SnapshotEntry.blob_hash)):
        refcount[h] += 1
    sizes = {h: s for h, s in session.execute(select(Blob.hash, Blob.compressed_size)).all()}
    reclaim = 0
    removed_hashes: set[str] = set()
    for versions in by_file.values():
        for v in versions:
            if v.id in plan.remove and v.blob_hash and refcount.get(v.blob_hash, 0) == 0:
                if v.blob_hash not in removed_hashes:
                    removed_hashes.add(v.blob_hash)
                    reclaim += sizes.get(v.blob_hash, 0)

    # Storage quota: drop oldest unprotected versions until under the limit.
    if policy.max_storage_bytes is not None and stored_bytes - reclaim > policy.max_storage_bytes:
        for v in sorted(candidates, key=lambda x: x.timestamp):
            if stored_bytes - reclaim <= policy.max_storage_bytes:
                break
            plan.remove.add(v.id)
            if v.blob_hash:
                refcount[v.blob_hash] -= 1
                if refcount[v.blob_hash] == 0 and v.blob_hash not in removed_hashes:
                    removed_hashes.add(v.blob_hash)
                    reclaim += sizes.get(v.blob_hash, 0)

    plan.estimated_reclaim_bytes = reclaim
    plan.files_affected = len(
        {v.file_id for vs in by_file.values() for v in vs if v.id in plan.remove}
    )
    return plan


def apply_retention(session: Session, plan: RetentionPlan) -> int:
    """Delete planned versions, re-linking parent pointers to the nearest kept ancestor."""
    if not plan.remove:
        MetaRepository(session).set("last_retention_at", utcnow().isoformat())
        return 0
    parents = dict(session.execute(select(Version.id, Version.parent_version_id)).all())

    def kept_ancestor(vid: int | None) -> int | None:
        seen = 0
        while vid is not None and vid in plan.remove and seen < 100_000:
            vid = parents.get(vid)
            seen += 1
        return vid

    for vid, parent in parents.items():
        if vid in plan.remove or parent is None or parent not in plan.remove:
            continue
        session.execute(
            update(Version).where(Version.id == vid).values(parent_version_id=kept_ancestor(parent))
        )
    ids = sorted(plan.remove)
    affected_files: set[int] = set()
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        affected_files.update(session.scalars(select(Version.file_id).where(Version.id.in_(batch))))
        session.execute(delete(Version).where(Version.id.in_(batch)))
    for file in session.scalars(select(File).where(File.id.in_(affected_files))):
        remaining = session.scalars(select(Version.id).where(Version.file_id == file.id)).all()
        file.version_count = len(remaining)
    MetaRepository(session).set("last_retention_at", utcnow().isoformat())
    return len(ids)


__all__ = ["Operation", "RetentionPlan", "apply_retention", "plan_retention"]
