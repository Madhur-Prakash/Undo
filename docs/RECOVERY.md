# Recovery

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · **Recovery** · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md)

Getting files back, and exactly what Undo promises when it writes them. Command details are in
the [CLI reference](CLI.md#restoration); the dashboard way is in
[CLI › Terminal UI](CLI.md#terminal-ui).

## A typical restore

```sh
undo history ~/project/config.yml                 # find the version (first column is its id)
undo cat 42                                       # look at it
undo diff 41 42                                   # what changed
undo restore ~/project/config.yml --version 42 --dry-run
undo restore ~/project/config.yml --version 42 --overwrite
```

## What can be restored

| Situation | Command |
|---|---|
| Latest stored version of a file | `undo restore PATH` |
| A specific version | `undo restore PATH --version ID` (ids from `undo versions PATH`) |
| State at a time | `undo restore PATH --at 2024-05-01T13:00` or `--at 2h` / `3d` |
| The version before a change | `undo restore PATH --before ID` |
| A deleted file | `undo recover PATH` (list with `undo recover`) |
| All deleted files below a folder | `undo recover FOLDER` |
| A directory at a point in time | `undo restore FOLDER --at TIME` |
| A snapshot | `undo snapshot restore NAME [--path SUBDIR]` |
| Anything, somewhere else | add `--to DIR` |
| Preview only | add `--dry-run` |

`PATH` may be a file's current path or any former path (renames and moves are tracked).
Times without an offset are local time; relative times count back from now.

## Restore guarantees

1. **No silent overwrite.** If the destination exists with different content the item is a
   *conflict* and is left untouched (exit code 5). `--overwrite` is required to replace it,
   and the CLI shows the plan and asks for confirmation unless `--yes`.
2. **Overwritten content is preserved.** Before replacing a file inside a tracked folder,
   Undo captures its current content as a new version. If that capture fails for a reason
   other than "excluded" or "too large", the overwrite is refused.
3. **Verified data only.** Content is reconstructed into a temporary file
   (`.undo-restore-*.tmp`) in the destination directory while being hashed. A mismatch with the
   BLAKE3 address aborts that item; the destination is not touched and the temp file is removed.
4. **Atomic placement.** After `fsync`, the temp file is moved into place with an atomic
   rename (`os.replace` for overwrite, no-clobber link/rename for new files, so a file that
   appears meanwhile is not overwritten).
5. **Identical files are skipped** (`identical`).
6. **Directory restores only touch files that existed in that directory at that time.** Files
   created later are left alone; nothing is deleted.
7. **Metadata is reported honestly.** Restored: modification time, permission bits (POSIX) or the
   read-only flag (Windows), ownership only when running as root on Linux. Not captured and
   therefore never claimed: ACLs, extended attributes, alternate data streams.
8. Blobs used by a restore are **pinned**, so a concurrent garbage collection cannot remove them.

## Crash recovery

At every daemon start (`startup_recovery`), while holding the exclusive lock:

* incomplete staging files are deleted (with retries for handles a killed process left open);
* objects in `trash/` from an interrupted garbage collection are moved back if their row still
  exists, otherwise deleted;
* object files that were published but never recorded (crash between publish and commit) are
  removed: nothing references them;
* every referenced whole-file object is checked for existence; missing ones are marked `missing`
  and reported;
* `PRAGMA quick_check` and `foreign_key_check` run, and `latest_version_id` pointers are repaired;
* then every enabled root is reconciled, which captures changes made while the daemon was down.

The result is visible in `undo status --json` (`daemon.recovery`) and the GUI's daemon card.

Writes are crash-safe by construction: data is written to staging, fsynced, verified and atomically
published before the metadata transaction commits, so a crash at any point leaves either the
previous consistent state or the new one. SQLite in WAL mode with `synchronous=NORMAL` can lose
the last committed transaction on power loss (never corrupt); the next reconciliation re-captures
any such change from the live file.

## Repairing damaged storage

```sh
undo storage verify            # full check; repairs from live files when possible
undo storage verify --quick    # existence only
```

A blob whose object is missing or corrupt can be repaired automatically if a tracked file still
has exactly that content. Otherwise the affected versions are reported as unrecoverable; restoring
them fails with a verification error and never writes bad data.

## Ransomware

Local version history is **not** a reliable defence against ransomware:

* Malware running as your user can read and delete `~/.local/share/undo` or `%LOCALAPPDATA%\Undo`
  just like any of your files.
* Malware that only encrypts documents will be *captured* by Undo as new versions; the previous
  versions remain restorable as long as the data directory itself survives.
* Retention could eventually remove the good versions; snapshots are always protected.

To improve your chances:

1. **Keep independent, offline or append-only backups** (external disk you disconnect, NAS with
   snapshots, cloud backup with versioning and object lock). This is the real protection.
2. Run the daemon under a **separate account** that owns the data directory (Linux:
   `sudo services/linux/install_service.sh --system --user undo-svc` with read access to the tracked
   folders; Windows: install the service with `--user`). Then your normal account cannot delete history.
3. Periodically copy the data directory to protected storage (with the daemon stopped, or after
   `undo snapshot create`): it is self-contained (`undo.db` plus `blobs/`).
4. Take a named snapshot before risky operations; snapshots are exempt from retention.

---

Related: [CLI reference](CLI.md) · [Storage](STORAGE.md) · [Troubleshooting › Restoring](TROUBLESHOOTING.md#restoring)
