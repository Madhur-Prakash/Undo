# Recovery

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · **Recovery** · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md) · [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md)
Getting files back, and exactly what Undo promises when it writes them.

* Command details: [CLI reference › Restoration](CLI.md#restoration).
* The dashboard way: [CLI › Terminal UI](CLI.md#terminal-ui).

## A typical restore

```sh
undo history ~/project/config.yml                 # find the version (first column is its id)
undo cat 42                                       # look at it
undo diff 41 42                                   # what changed
undo restore ~/project/config.yml --version 42 --dry-run
undo restore ~/project/config.yml --version 42 --overwrite
```

## Comparing and resolving conflicts

A restore never replaces a file that changed: it reports a **conflict**. Before deciding, you can
see exactly what differs, and merge the two like a merge conflict.

**Filter the preview** (app): chips above the list show each outcome with its count (*Conflicts*,
*Errors*, *Overwrite*, *Create*, *Identical*). Conflicts and errors are listed first. In the TUI
preview, `t` cycles the filter.

**Compare** an item with the file on disk, side by side: left is the file now, right is what the
restore would write.

* App: the compare icon on the item, or on a version in a file's history.
* CLI: `undo diff-file VERSION [PATH]`.
* TUI: `c` on the item in the restore preview.

**Resolve** opens the merge editor, in all three interfaces:

* App: *Resolve* on a conflict, error or overwrite in the restore preview, or *Edit and merge*
  in any comparison.
* TUI: `m` in the restore preview, or on a version in a file's history.
* CLI: `undo merge VERSION [PATH]` asks for each difference, then what to do with the result.

In the editor:

1. Each difference shows the disk on the left and the version on the right. Choose **Keep disk**,
   **Use version** or **Both**, or use *Keep disk for all* / *Use version for all*.
2. The **Result** below updates from your choices. You can also edit it freely by hand.
3. **Save to file** writes the result. The file's current content is saved as a version first, so
   this can be undone, and the save is refused if the file changed since the editor opened.
4. **Save progress** keeps an unfinished merge. Closing with unsaved changes asks: *Save
   progress*, *Discard* or *Keep editing*. Opening the same file's merge again offers to
   **Resume**. Unfinished merges are listed in the app (*Overview* > **Unfinished merges**),
   the TUI (`u`) and by `undo merge-drafts`.

Saved progress is stored in the data directory (`merge-drafts/`) and deleted automatically once
the file is merged or restored. Identical files have nothing to resolve; their comparison just
says so. Binary files and files over 2 MiB cannot be merged; restore them to another folder.

## Rolling back a whole folder

Puts every file in a folder back the way it was at a point in time. No snapshot is needed: every
saved version is already in the history.

* Files created later are left alone, and **nothing is deleted**.
* Files that changed since then are only replaced with *overwrite*; their current content is
  saved as a version first, so the rollback itself can be undone.

**In the app:** *Overview › Tracked folders* › the **Roll back** button
(<kbd>⟲</kbd>) on a folder. Then:

1. keep the whole folder or choose a subfolder,
2. pick a time (15 minutes ago … 1 week ago, or an exact date and time),
3. **Preview** shows every file that would be restored, overwritten or skipped,
4. optionally restore into another folder, tick *Overwrite*, then **Restore**.

**On the command line:**

```sh
undo restore ~/project --at 2h --dry-run          # preview
undo restore ~/project --at 2h --overwrite        # roll back
undo restore ~/project --at 2026-11-24T14:00 --to ~/project-as-of-2pm   # into another folder
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

Writes are crash-safe by construction:

* Data is written to staging, fsynced, verified and atomically published **before** the metadata
  transaction commits.
* So a crash at any point leaves either the previous consistent state or the new one.
* SQLite in WAL mode with `synchronous=NORMAL` can lose the last committed transaction on power
  loss, but never corrupts. The next reconciliation re-captures such a change from the live
  file.

## Repairing damaged storage

```sh
undo storage verify            # full check; repairs from live files when possible
undo storage verify --quick    # existence only
```

* A missing or corrupt object is repaired automatically if a tracked file still has exactly that
  content.
* Otherwise the affected versions are reported as unrecoverable.
* Restoring them fails with a verification error and never writes bad data.

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
