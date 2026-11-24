# Storage

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · **Storage** · [API](API.md)

What is inside the data directory and how file contents are stored, deduplicated, kept and
verified.

## Data directory layout

Default location: `%LOCALAPPDATA%\Undo` (Windows), `$XDG_DATA_HOME/undo` or `~/.local/share/undo`
(Linux). Override with `UNDO_HOME` or `--data-dir`.

```
undo-data/
├── config.json          settings (validated, atomically written)
├── undo.db (+ -wal)     SQLite metadata, WAL mode
├── api_token            local API token (owner-only permissions)
├── undo.lock            OS-level daemon/writer lock   (undo.owner: informational pid)
├── daemon.json          discovery info written by the running daemon
├── blobs/0a/0a92…zst    whole-file objects, sharded by the first two hex chars
├── chunks/1b/1b73…zst   chunk objects (only when chunking is enabled)
├── staging/             in-progress writes (cleaned at startup)
├── trash/               objects being removed by an in-flight garbage collection
├── quarantine/          corrupt objects replaced during repair
└── logs/undo.log        JSON-lines log, rotated (10 MiB × 5)
```

The data directory is always excluded from monitoring, even if it lies inside a tracked folder.
Tracking the data directory itself, or a folder inside it, is refused; installed builds also
refuse Undo's program folder.

Removing history (`undo untrack --purge`, retention) deletes database rows. The space is only
freed by [garbage collection](#garbage-collection), so *stored* in `undo status` can stay high
until `undo storage gc` (or the daemon's daily `gc` job) runs.

## Hashing

* Algorithm: **BLAKE3-256**, hex encoded (64 chars).
* The hash identifies the **original, uncompressed content**, so the address does not depend on
  compression settings.
* Files are streamed in 1 MiB blocks; nothing is loaded whole into memory.

## Capture and publishing

1. **Pass 1**: stream the file through BLAKE3; confirm size and mtime did not change.
2. **Dedup check**: if a healthy blob with that hash exists, reuse it; no data is written.
3. **Pass 2**: stream the file again into `staging/obj-*.part`, compressing and hashing at the same
   time. A different hash, size or mtime means the file changed during capture, so it is retried.
4. If zstd output is not smaller than the input, the object is rewritten raw.
5. `fsync` the staged file, then **decompress and re-hash it** (successful decompression alone is
   never taken as proof of integrity).
6. Publish atomically without overwriting: `os.link`+`unlink` on POSIX, `os.rename` (which fails if
   the target exists) on Windows; then fsync the directory (POSIX). If an object already exists at
   that address and verifies, the new copy is discarded. If it is corrupt it is moved to
   `quarantine/` and replaced (repair).
7. Record the blob row in SQLite, checking inside the write transaction that the object file is
   present (see garbage collection), and then the version row in a separate short transaction.

## Compression

| Setting | Default | Meaning |
|---|---|---|
| `compression.enabled` | `true` | Zstandard on/off |
| `compression.level` | `3` | 1 = fastest … 22 = smallest; 3 is a good default, 19+ for archival |
| `compression.min_size` | `64` | smaller files are stored raw |
| `compression.skip_extensions` | jpg, png, zip, mp4, docx, … | already-compressed formats stored raw |

Each blob records `compression_algorithm` (`zstd`, `none` or `chunked`), the level used, the
original size and the stored size. Frames are written with zstd content checksums.

## Deduplication

* **Whole-file** (always on): identical content anywhere in any tracked root, in any version, is
  stored once. Renames and moves reuse the existing blob; no data is copied.
* **Chunk-level** (`chunking.enabled`, off by default): files of at least
  `chunking.min_file_size` (16 MiB) are split into fixed `chunking.chunk_size` (4 MiB) chunks.
  Each chunk is hashed, compressed and stored once in `chunks/`. The blob then has
  `storage_kind = chunked` and an ordered manifest in `blob_chunks`. On read every chunk is
  verified against its own hash and the reassembled stream against the whole-file hash.
  Fixed-size chunking helps with in-place edits (VM images, large binaries) but not with
  insertions that shift data.

The public API is identical for both kinds: callers only see blob hashes.

## Metadata (SQLite)

| Table | Purpose |
|---|---|
| `roots` | tracked folders (`absolute_path`, `platform`, `enabled`, `last_scan_at`, `configuration`) |
| `files` | one row per tracked file identity; `relative_path`, `path_key` (case-folded on Windows), `filesystem_identity`, `deleted_at`, last size/mtime, `latest_version_id` |
| `path_history` | every path a file has had (search by former names) |
| `versions` | `operation` (CREATE/MODIFY/DELETE/RENAME/MOVE), `blob_hash`, `file_size`, `timestamp`, `parent_version_id`, `snapshot_id`, `relative_path`, `metadata` (mtime, mode, uid/gid, attributes, `from_path`) |
| `blobs` | `hash`, sizes, compression, `storage_kind`, `storage_path`, `status` (ok/missing/corrupt), `verified_at` |
| `chunks`, `blob_chunks` | chunk objects and per-blob manifests |
| `snapshots`, `snapshot_entries` | named snapshots and the version of every file they captured |
| `exclusions` | user patterns (global or per root) |
| `skip_records` | why a path was not captured (excluded, too_large, permission_denied, …) |
| `blob_pins` | cross-process protection of blobs used by an in-flight restore |
| `meta_kv` | last GC / verify / retention times |
| `schema_migrations` | applied migrations |

Foreign keys are enforced. `versions.blob_hash` and `snapshot_entries.blob_hash/version_id` use
`ON DELETE RESTRICT`, so the database itself refuses to drop data that is still referenced.
A partial unique index guarantees one *live* file per path and root.

## Retention

Configured in `retention.*`; applied by the daemon every `retention.interval_seconds` or with
`undo storage retention` / `undo storage gc --retention`.

Always kept: the latest version of every file, the latest content of deleted files, every
version referenced by a snapshot. With `keep_all = true` (default) nothing else is removed unless
`max_storage_bytes` is exceeded. With `keep_all = false` a version survives if any of
`keep_last`, `keep_days`, `daily_days`, `weekly_weeks` keeps it. The quota then removes the oldest
remaining unprotected versions. Removing versions re-links `parent_version_id` to the nearest
kept ancestor and never deletes data directly.

## Garbage collection

`undo storage gc [--dry-run]` (and the daemon's `gc` job) deletes blobs and chunks that are not
referenced by versions, snapshot entries, blob pins (active restores, any process) or in-process
pins, and that are older than `daemon.gc_grace_seconds` (default 1 h). Inside one
`BEGIN IMMEDIATE` transaction it re-computes the unreferenced set, deletes the rows (foreign keys
refuse anything still referenced) and moves the object files into `trash/`; after the commit the
trash is emptied, and on rollback the files are moved back. Because captures check the presence of
their object inside their own write transaction, GC and capture can never interleave into a
dangling reference. Orphan files (objects with no row, for example after a crash) and stale
staging files are removed under the same rules. Dry run reports exactly what would be reclaimed.

## Verification

`undo storage verify` decompresses and re-hashes every blob and chunk (`--quick` only checks
existence), marks missing or corrupt objects in the database, runs `PRAGMA quick_check` and
`foreign_key_check`, lists orphan files and repairs damaged blobs from live files whose current
content still has the same hash.

---

Related: [Architecture](ARCHITECTURE.md) · [Recovery](RECOVERY.md) · [Troubleshooting › Storage](TROUBLESHOOTING.md#storage-and-disk-space)
