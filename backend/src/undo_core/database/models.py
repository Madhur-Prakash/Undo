"""SQLAlchemy ORM models. Timestamps are naive UTC."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from undo_core.utils.timeutil import utcnow


class Base(DeclarativeBase):
    pass


class Operation(StrEnum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    MOVE = "MOVE"


class BlobStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"


class Root(Base):
    __tablename__ = "roots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    absolute_path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False)
    filesystem_identity: Mapped[str | None] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(16), default="file", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_size: Mapped[int | None] = mapped_column(BigInteger)
    last_mtime_ns: Mapped[int | None] = mapped_column(BigInteger)
    latest_version_id: Mapped[int | None] = mapped_column(Integer)
    version_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index(
            "ux_files_active_path",
            "root_id",
            "path_key",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_files_root_path", "root_id", "path_key"),
        Index("ix_files_identity", "filesystem_identity"),
        Index("ix_files_deleted", "deleted_at"),
    )


class PathHistory(Base):
    __tablename__ = "path_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_path_history_file", "file_id"),
        Index("ix_path_history_key", "path_key"),
    )


class Blob(Base):
    __tablename__ = "blobs"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compression_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    compression_level: Mapped[int | None] = mapped_column(Integer)
    storage_kind: Mapped[str] = mapped_column(String(16), default="whole", nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=BlobStatus.OK, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_blobs_created", "created_at"),)


class Chunk(Base):
    __tablename__ = "chunks"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compression_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=BlobStatus.OK, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BlobChunk(Base):
    __tablename__ = "blob_chunks"

    blob_hash: Mapped[str] = mapped_column(
        ForeignKey("blobs.hash", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_hash: Mapped[str] = mapped_column(
        ForeignKey("chunks.hash", ondelete="RESTRICT"), nullable=False
    )
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (Index("ix_blob_chunks_chunk", "chunk_hash"),)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("root_id", "name", name="uq_snapshot_root_name"),)


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    blob_hash: Mapped[str | None] = mapped_column(
        ForeignKey("blobs.hash", ondelete="RESTRICT"), nullable=True
    )
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("versions.id", ondelete="SET NULL")
    )
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id", ondelete="SET NULL"))
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_versions_file_ts", "file_id", "timestamp"),
        Index("ix_versions_blob", "blob_hash"),
        Index("ix_versions_ts", "timestamp"),
    )


class SnapshotEntry(Base):
    __tablename__ = "snapshot_entries"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("versions.id", ondelete="RESTRICT"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    blob_hash: Mapped[str] = mapped_column(
        ForeignKey("blobs.hash", ondelete="RESTRICT"), nullable=False
    )
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_snapshot_entries_version", "version_id"),
        Index("ix_snapshot_entries_blob", "blob_hash"),
    )


class Exclusion(Base):
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int | None] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"))
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_exclusions_root", "root_id"),)


class SkipRecord(Base):
    __tablename__ = "skip_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (UniqueConstraint("root_id", "path_key", name="uq_skip_root_path"),)


class BlobPin(Base):
    """Cross-process protection of blobs used by an in-flight restore or capture."""

    __tablename__ = "blob_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blob_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_blob_pins_hash", "blob_hash"),)


class MetaKV(Base):
    __tablename__ = "meta_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
