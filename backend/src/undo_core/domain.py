"""Pydantic models returned by the service layer and exposed through the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class _Model(BaseModel):
    model_config = {"from_attributes": True}


class RootInfo(_Model):
    id: int
    path: str
    platform: str
    enabled: bool
    created_at: datetime
    last_scan_at: datetime | None = None
    file_count: int = 0
    deleted_file_count: int = 0
    version_count: int = 0
    watch_mode: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class FileInfo(_Model):
    id: int
    root_id: int
    root_path: str
    relative_path: str
    absolute_path: str
    name: str
    file_type: str
    size: int | None = None
    created_at: datetime
    last_seen_at: datetime
    deleted_at: datetime | None = None
    is_deleted: bool = False
    latest_version_id: int | None = None
    version_count: int = 0
    last_modified: datetime | None = None
    latest_operation: str | None = None
    latest_timestamp: datetime | None = None


class FilePage(_Model):
    items: list[FileInfo]
    total: int
    limit: int
    offset: int


class VersionInfo(_Model):
    id: int
    file_id: int
    root_id: int
    relative_path: str
    absolute_path: str
    operation: str
    timestamp: datetime
    file_size: int
    blob_hash: str | None = None
    parent_version_id: int | None = None
    snapshot_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlobInfo(_Model):
    hash: str
    original_size: int
    compressed_size: int
    compression_algorithm: str
    compression_level: int | None = None
    storage_kind: str
    storage_path: str | None = None
    status: str
    verified_at: datetime | None = None
    created_at: datetime
    chunk_count: int = 0
    reference_count: int = 0


class VersionDetail(_Model):
    version: VersionInfo
    file: FileInfo
    blob: BlobInfo | None = None
    previous_version_id: int | None = None
    next_version_id: int | None = None
    is_text: bool = False


class PathHistoryInfo(_Model):
    relative_path: str
    valid_from: datetime
    valid_to: datetime | None = None


class FileHistory(_Model):
    file: FileInfo
    versions: list[VersionInfo]
    paths: list[PathHistoryInfo]


class SearchHit(_Model):
    file: FileInfo
    matched_path: str
    historical: bool


class SkipInfo(_Model):
    root_id: int
    relative_path: str
    reason: str
    detail: str | None = None
    first_seen: datetime
    last_seen: datetime
    count: int


class ReconcileReport(_Model):
    root_id: int
    root_path: str
    prefix: str = ""
    deep: bool = False
    scanned: int = 0
    new: int = 0
    modified: int = 0
    deleted: int = 0
    renamed: int = 0
    unchanged: int = 0
    deduplicated: int = 0
    skipped: int = 0
    failed: int = 0
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    stored_bytes: int = 0
    duration_seconds: float = 0.0


class AddRootResult(_Model):
    root: RootInfo
    scan: ReconcileReport | None = None


class RestoreItem(_Model):
    relative_path: str
    destination: str
    action: str  # create | overwrite | identical | conflict | error | missing_blob
    version_id: int | None = None
    blob_hash: str | None = None
    size: int = 0
    detail: str | None = None
    resolved: bool = False  # writes a resolution saved in the merge editor


class RestoreResult(_Model):
    dry_run: bool
    items: list[RestoreItem]
    created: int = 0
    overwritten: int = 0
    identical: int = 0
    conflicts: int = 0
    errors: int = 0
    metadata_restored: list[str] = Field(default_factory=list)
    metadata_not_restored: list[str] = Field(default_factory=list)
    pre_restore_versions: list[int] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.errors == 0 and self.conflicts == 0


class SnapshotInfo(_Model):
    id: int
    name: str
    description: str | None = None
    created_at: datetime
    root_id: int
    root_path: str
    file_count: int
    total_size: int


class SnapshotEntryInfo(_Model):
    file_id: int
    version_id: int
    relative_path: str
    blob_hash: str
    file_size: int


class SnapshotDetail(_Model):
    snapshot: SnapshotInfo
    entries: list[SnapshotEntryInfo]


class SnapshotChange(_Model):
    relative_path: str
    a_version_id: int | None = None
    b_version_id: int | None = None
    a_size: int | None = None
    b_size: int | None = None


class SnapshotDiff(_Model):
    a: SnapshotInfo
    b: SnapshotInfo
    added: list[SnapshotChange]
    removed: list[SnapshotChange]
    modified: list[SnapshotChange]
    unchanged: int


class StorageStats(_Model):
    data_dir: str
    root_count: int
    file_count: int
    deleted_file_count: int
    version_count: int
    snapshot_count: int
    blob_count: int
    chunk_count: int
    chunked_blob_count: int
    logical_bytes: int
    unique_bytes: int
    stored_bytes: int
    blob_disk_bytes: int
    database_bytes: int
    dedup_savings_bytes: int
    compression_savings_bytes: int
    total_savings_bytes: int
    compression_algorithms: dict[str, int]
    unhealthy_blobs: int
    skipped_files: int
    last_verify_at: str | None = None
    last_verify_ok: bool | None = None
    last_gc_at: str | None = None
    last_retention_at: str | None = None


class VerifyReport(_Model):
    full: bool
    checked_blobs: int
    checked_chunks: int
    ok: int
    missing: list[str]
    corrupt: list[str]
    repaired: list[str]
    orphan_files: list[str]
    database_problems: list[str]
    healthy: bool
    duration_seconds: float


class GCReport(_Model):
    dry_run: bool
    candidate_blobs: int
    candidate_chunks: int
    reclaimable_bytes: int
    deleted_blobs: int
    deleted_chunks: int
    reclaimed_bytes: int
    protected_by_grace: int
    orphan_files: int
    orphan_bytes: int
    staging_files: int
    errors: list[str]
    duration_seconds: float


class RetentionReport(_Model):
    dry_run: bool
    policy: dict[str, Any]
    files_examined: int
    versions_examined: int
    versions_removed: int
    files_affected: int
    estimated_reclaim_bytes: int
    removed_version_ids: list[int] = Field(default_factory=list)


class ForgetResult(_Model):
    """Result of removing history on purpose (a file, a folder, older versions, single versions)."""

    dry_run: bool
    target: str
    before: datetime | None = None
    files_examined: int = 0
    files_affected: int = 0
    files_removed: int = 0  # file records with no history left
    versions_removed: int = 0
    versions_kept_in_snapshots: int = 0
    removed_version_ids: list[int] = Field(default_factory=list)
    note: str | None = None


class ExclusionInfo(_Model):
    id: int | None = None
    pattern: str
    root_id: int | None = None
    source: str
    created_at: datetime | None = None


class WatcherInfo(_Model):
    root_id: int
    path: str
    mode: str
    healthy: bool
    error: str | None = None


class RecoveryInfo(_Model):
    staging_removed: int = 0
    orphan_objects_removed: int = 0
    missing_blobs: list[str] = Field(default_factory=list)
    fixed_latest_pointers: int = 0
    database_problems: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    ok: bool = True


class HealthInfo(_Model):
    running: bool
    pid: int
    version: str
    api_version: str
    started_at: datetime
    uptime_seconds: float
    data_dir: str
    api_url: str | None = None
    watchers: list[WatcherInfo] = Field(default_factory=list)
    queue_depth: int = 0
    queue_capacity: int = 0
    pending_captures: int = 0
    events_received: int = 0
    events_dropped: int = 0
    overflow_count: int = 0
    captures: dict[str, int] = Field(default_factory=dict)
    last_reconcile_at: datetime | None = None
    reconciling: bool = False
    jobs: dict[str, Any] = Field(default_factory=dict)
    recent_errors: list[str] = Field(default_factory=list)
    recovery: RecoveryInfo | None = None


class StatusInfo(_Model):
    initialized: bool
    data_dir: str
    daemon_running: bool
    daemon: HealthInfo | None = None
    root_count: int = 0
    file_count: int = 0
    deleted_file_count: int = 0
    version_count: int = 0
    snapshot_count: int = 0
    skipped_count: int = 0
    stored_bytes: int = 0
    logical_bytes: int = 0


class DiffRow(_Model):
    """One row of a side-by-side diff: the old line (a) next to the new line (b)."""

    kind: str  # equal | delete | insert | change
    a_no: int | None = None
    a_text: str | None = None
    b_no: int | None = None
    b_text: str | None = None
    a_spans: list[tuple[int, int]] = Field(default_factory=list)  # changed chars [start, end)
    b_spans: list[tuple[int, int]] = Field(default_factory=list)


class DiffHunk(_Model):
    a_start: int
    a_count: int
    b_start: int
    b_count: int
    rows: list[DiffRow]


class VersionDiff(_Model):
    a: VersionInfo
    b: VersionInfo
    identical: bool
    is_text: bool
    diff: str | None = None  # unified text
    hunks: list[DiffHunk] = Field(default_factory=list)  # side by side
    added: int = 0
    removed: int = 0
    truncated: bool = False
    size_delta: int
    note: str | None = None


class FileDiff(_Model):
    """A stored version compared with a file on disk: left = the file now, right = the version.

    This is what a restore of ``version`` to ``path`` would change.
    """

    version: VersionInfo
    path: str
    exists: bool  # False: the file is not on disk (a restore would create it)
    identical: bool
    is_text: bool
    diff: str | None = None
    hunks: list[DiffHunk] = Field(default_factory=list)
    added: int = 0
    removed: int = 0
    truncated: bool = False
    size_delta: int = 0  # version size minus current size
    note: str | None = None


class MergeDraft(_Model):
    """Saved progress of a merge, to resume later."""

    path: str
    version_id: int
    text: str
    choices: dict[str, str] = Field(default_factory=dict)  # hunk index -> disk | version | both
    edited: bool = False
    resolved: bool = False  # finished: the next restore of this version writes it
    updated_at: datetime | None = None


class MergeSource(_Model):
    """Both sides of a merge: the file on disk now (left) and a stored version (right)."""

    version: VersionInfo
    path: str
    exists: bool
    current_lines: list[str]  # the file now, split exactly like the diff (no line endings)
    version_lines: list[str]  # the stored version, split the same way
    current_hash: str  # the merge is refused if the file changed since this
    line_ending: str  # CRLF | LF: used when writing the result
    hunks: list[DiffHunk] = Field(default_factory=list)
    identical: bool = False
    draft: MergeDraft | None = None


class MergeWriteResult(_Model):
    path: str
    bytes_written: int
    pre_restore_version_id: int | None = None  # the content that was replaced, saved first
    version_id: int | None = None  # the merged content, recorded as a new version
    note: str | None = None


class DoctorCheck(_Model):
    name: str
    ok: bool
    severity: str = "info"  # info | warning | error
    detail: str


class VersionContent(_Model):
    version_id: int
    is_text: bool
    size: int
    truncated: bool
    text: str | None = None
