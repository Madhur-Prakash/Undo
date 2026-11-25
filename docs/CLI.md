# CLI reference

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · **CLI** · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md) · [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md)
Every `undo` command, option and setting. For step-by-step recipes see
[Recovery](RECOVERY.md); for first-time setup see [Installation](INSTALLATION.md).

`undo [--data-dir DIR] [--local] COMMAND ...`

* `--data-dir` (env `UNDO_HOME`) selects the data directory.
* `--local` never talks to the daemon; writes then need the daemon to be stopped.
* When a daemon is running, commands go through its API; otherwise they run in-process and take the
  data-directory lock for writes. Output is identical either way.
* Most commands accept `--json` for automation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | general error / failures during the operation |
| 2 | invalid input (bad option, invalid setting value) |
| 3 | not initialised (`undo init`) |
| 4 | not found |
| 5 | conflict (e.g. restore destination exists; nothing was overwritten) |
| 6 | data directory locked by another process |
| 7 | daemon not running / unreachable |
| 8 | storage integrity problem (`undo storage verify` found damage) |
| 9 | API authentication failed |
| 130 | interrupted |

## Initialisation

| Command | Description |
|---|---|
| `undo init` | Create data directory, settings, database (migrations) and API token. Idempotent. |
| `undo config [--path] [--json]` | Show data/settings/log locations, daemon URL, autostart state. |
| `undo doctor [--json]` | Health checks; exit 1 on errors (details below). |

## Tracking

| Command | Description |
|---|---|
| `undo track PATH [--no-scan]` | Track a folder and everything below it (details below). |
| `undo untrack PATH\|ID [--purge] [-y]` | Stop monitoring; history kept. `--purge` deletes the root's history (data reclaimed by `gc`). |
| `undo roots` | List roots with file/version counts, last scan and monitoring mode. |
| `undo scan [PATH\|ID] [--deep]` | Reconcile now (all roots, one root, or a sub-directory). `--deep` re-hashes every file. |
| `undo skipped [--root R] [-n N]` | Files not captured, and why. |

**Details:**

* `undo track`:
  * relative paths such as `.` are resolved first;
  * overlapping folders, the data directory and (installed builds) Undo's program folder are
    refused;
  * with the daemon running, the first scan happens in the background; without it, in the
    terminal (`--no-scan` skips it).
* `undo skipped` reasons: `excluded:<pattern>`, `too_large`, `permission_denied`,
  `symlink_not_followed`, `temporarily_unavailable`.
* `undo doctor` checks: writability, database integrity, disk space, token permissions, roots,
  stored-data health, monitoring backend, inotify limits.

## Daemon

| Command | Description |
|---|---|
| `undo start [-f/--foreground]` | Start the background daemon (detached) or run it in this terminal. |
| `undo stop` | Graceful shutdown via the API. |
| `undo restart` | Stop and start. |
| `undo status [--json]` | Daemon state, queue, watchers, recent errors, totals. Works without a daemon. |
| `undo logs [-n N] [-f] [--raw]` | Show / follow the JSON log, pretty-printed. |
| `undo service install [--system]` | Start the daemon automatically, and now (details below). |
| `undo service status` | Whether autostart is installed. Windows: the registered command. Linux: `systemctl --user is-enabled undo`. |
| `undo service uninstall [--system]` | Removes autostart. A running daemon keeps running until `undo stop`. |

**`undo service install`:**

* Linux: a systemd user unit; `--system` (as root) installs a system unit.
* Windows: the value `Undo` in your per-user Run key; starts at sign-in, no admin needed.
* It also starts the daemon right away.

## History

| Command | Description |
|---|---|
| `undo history PATH [-n N]` | File summary, former paths and every version (operation, time, size, hash). |
| `undo versions PATH` | Compact list of version ids. |
| `undo files [QUERY] [--root R] [-d] [-s KEY] [-r]` | List tracked files (sorting below). |
| `undo log [-n N] [--since 1d] [--root R] [-s KEY] [-r]` | Recent changes across roots, newest first. `--sort` by `time`, `path`, `size` or `operation`. |
| `undo search QUERY` | Match current and former paths. |
| `undo show VERSION` | Version details: hash, compression, storage, references, neighbours. |
| `undo merge VERSION [PATH] [--all disk\|version] [-y]` | Resolve a restore like a merge conflict (details below). |
| `undo merge-drafts [--discard PATH]` | List saved merges (unfinished or resolved), or delete one. |
| `undo diff-file VERSION [PATH] [-u]` | Compare a version with the file on disk. |
| `undo diff A B [-u]` | Compare two versions side by side. |
| `undo cat VERSION` | Print a text version. |
| `undo forget PATH [--before TIME] [--dry-run] [-y]` | Remove a file's or folder's history (details below). |
| `undo delete-versions ID... [-y]` | Delete individual versions. Refuses a file's latest version (use `forget`) and versions in a snapshot. |

**Details:**

* `undo files --sort` (`-s`): `path` (default), `modified`, `size`, `version` (latest change),
  `versions` (number of versions). `-r` reverses, `-d` includes deleted files.
* `undo diff` and `undo diff-file`:
  * side by side, changed characters highlighted, with a `+added -removed` summary;
  * `-u`, or a terminal under 100 columns, prints a unified diff;
  * line-ending changes (CRLF/LF) are ignored and reported in the summary.
* `undo diff-file`: left is the file now, right the version, i.e. what restoring it would change.
  Default path: the file's current location. Only files inside tracked folders.
* `undo merge`:
  * for each difference: `d` keep disk, `v` use version, `b` both (`--all disk|version` answers
    all at once);
  * then: `w` save the resolution (the file is not changed), show the result, edit it in your
    editor, save progress, or discard;
  * apply a resolution by restoring that version: `undo restore PATH --version N` (or a folder
    or snapshot restore);
  * offers to resume saved progress;
  * tracked files only; not binary; at most 2 MiB.
* `undo forget`:
  * `--before` (ISO, or relative such as `30d`, `2w`) removes only older versions and keeps each
    file's latest version;
  * shows a preview and asks first; snapshot versions are kept;
  * files that still exist start a new history.

## Restoration

| Command | Description |
|---|---|
| `undo restore PATH` | Latest stored content (file) or current state (directory). |
| `undo restore PATH --version ID` | Specific version. |
| `undo restore PATH --at TIME` | State at a time (ISO or relative: `30m`, `2h`, `3d`, `1w`). Works for directories. |
| `undo restore PATH --before ID` | Version before the given one. |
| `undo restore PATH --to DEST` | Restore elsewhere (an existing directory or a path ending in `/`). |
| `undo restore PATH --overwrite [-y]` | Replace existing files (plan shown, confirmation asked unless `-y`). |
| `undo restore PATH --dry-run` | Show the plan only. |
| `undo recover` | List deleted files with recoverable content. |
| `undo recover PATH [--to DEST] [--overwrite] [--dry-run]` | Recover a deleted file or all deleted files below a folder. |

## Snapshots

| Command | Description |
|---|---|
| `undo snapshot create --name NAME [--root R] [-d TEXT] [--no-scan]` | Scan the root, then record every file's current version. |
| `undo snapshot list [--root R] [-s KEY] [-r]` | List snapshots, newest first. `--sort` by `created`, `name`, `root`, `files` or `size`. |
| `undo snapshot show ID\|NAME` | Files in the snapshot. |
| `undo snapshot diff A B` | Added / removed / modified between two snapshots. |
| `undo snapshot restore ID\|NAME [--to DIR] [--path SUBDIR] [--overwrite] [--dry-run]` | Restore. |
| `undo snapshot rename ID\|NAME [NEW_NAME] [-d TEXT]` | Rename a snapshot and/or change its description (`-d ""` clears it). Names are unique per folder. |
| `undo snapshot delete ID\|NAME [-y]` | Delete (versions remain). |

**Snapshot names:**

* Matched ignoring case, spaces, `-` and `_`, so `try1` finds "try 1".
* Quote names with spaces, or use the id:

```sh
undo snapshot show "try 1"
undo snapshot show 1
```

## Storage

| Command | Description |
|---|---|
| `undo storage stats` | Sizes, savings by deduplication and compression, health, last maintenance. |
| `undo storage verify [--quick] [--no-repair]` | Integrity verification (exit 8 on damage). |
| `undo storage gc [--dry-run] [--retention] [-y]` | Garbage collection, optionally applying retention first. |
| `undo storage retention [--dry-run]` | Apply the retention policy only. |

## Exclusions

| Command | Description |
|---|---|
| `undo exclude add PATTERN [--root R]` | `name/` directory name, `*.ext` glob, `a/b` relative path, `/abs/path`. |
| `undo exclude remove PATTERN [--root R]` | Removes a user pattern, or a default one from `exclusions.defaults`. Built-ins cannot be removed. |
| `undo exclude list [--root R]` | All active rules with their source (builtin / default / user). |

## Settings

* Settings are stored in `config.json` in the data directory.
* Every setting below can also be changed on the app's **Settings** page; exclusion patterns are
  on its **Exclusions** card.

```sh
undo config --path        # where config.json is
```

`undo settings show [SECTION|KEY]` and `undo settings set KEY VALUE`. Sizes accept units
(`500MB`, `2GiB`), lists accept JSON or comma-separated values, `none` clears optional values.

| Key | Default | |
|---|---|---|
| `compression.enabled` / `compression.level` | true / 3 | Zstandard |
| `chunking.enabled` / `chunk_size` / `min_file_size` | false / 4 MiB / 16 MiB | chunk-level dedup |
| `capture.max_file_size` | 4 GiB | larger files are skipped (`too_large`) |
| `capture.debounce_seconds` / `stable_seconds` | 1.0 / 0.5 | event debounce / stability wait |
| `capture.retry_seconds` / `max_retries` | 2.0 / 5 | busy files |
| `capture.max_concurrent` | 2 | capture workers (CPU/IO budget) |
| `monitor.reconcile_interval_seconds` | 3600 | periodic full scan |
| `monitor.initial_scan` | true | reconcile at daemon start |
| `monitor.force_polling` / `polling_interval_seconds` | false / 10 | polling mode |
| `monitor.event_queue_size` | 10000 | bounded event queue |
| `monitor.follow_symlinks` / `exclude_hidden` | false / false | |
| `retention.keep_all` | true | keep every version (rules below off) |
| `retention.keep_last` / `keep_days` / `daily_days` / `weekly_weeks` | none | retention rules; a version is kept if any rule keeps it ([details](STORAGE.md#retention)) |
| `retention.max_storage_bytes` | none | storage quota, e.g. `50GB` |
| `retention.interval_seconds` | 86400 | how often retention runs (first run 10 min after the daemon starts) |
| `compression.min_size` / `skip_extensions` | 64 B / archives, images, video … | stored uncompressed |
| `exclusions.defaults` | see below | default exclusion patterns |
| `exclusions.defaults_version` | 3 | internal: version of the default list (see below) |
| `api.host` / `api.port` | 127.0.0.1 / 47821 | loopback only unless `api.allow_remote` |
| `daemon.autostart` | true | GUI/TUI start the daemon when needed |
| `daemon.gc_interval_seconds` / `gc_grace_seconds` | 86400 / 3600 | |
| `daemon.verify_interval_seconds` | 0 | scheduled verification (0 = off) |
| `daemon.log_level` | INFO | |
| `ui.theme` | system | GUI theme |

**Default exclusions** (`exclusions.defaults`):

* Version control and tool caches: `.git/`, `.svn/`, `__pycache__/`, `.mypy_cache/`, …
* Temporary and log files: `*.tmp`, `*.swp`, `~$*`, `*.log`, …
* Python: `*.whl`, `*.egg-info/`, `site-packages/`, `venv/`, `.venv/`, `*.pyc`
* Node: `node_modules/`, `.npm/`, `.pnpm-store/`, `.yarn/`
* Rust: `target/`, `.cargo/`, `.rustup/`, `*.crate`

```sh
undo exclude list                   # all of them, with their source
undo exclude remove "target/"       # e.g. if your own folder is called target
```

`exclusions.defaults_version` records which version of this list yours matches. New defaults
are added once on upgrade; a default you removed never comes back.

## Terminal UI

`undo tui` opens a full-screen dashboard; it works over SSH.

**Everywhere**

* `1`–`7` switch tabs: Dashboard, Roots, Files, History, Snapshots, Storage, Settings
* `u` saved merges (Enter open, `x` discard)
* `F5` / `Ctrl+R` refresh · `q` quit

**Roots**

* `a` add · `s` scan · `e` enable/disable
* `x` untrack (history kept)
* `f` delete history of the folder or a subfolder (all, or older than e.g. `30d`)

**Files**

* type to search · tick *Include deleted* · `Enter` opens the file's history

**File history**

* `v` view content · `i` details · `r` restore
* `d` compare with the previous version · `c` compare with the file on disk
* `m` merge into the file
* `x` delete this version (not the latest) · `f` delete the file's history
* `Esc` back

**Snapshots**

* `c` create · `d` compare · `r` restore · `n` rename · `x` delete

**Restore preview**

* `c` compare the selected file with the disk
* `m` resolve it in the merge editor
* `t` cycle the filter (all, conflict, error, overwrite, create, identical)
* conflicts and errors are listed first

**Merge editor**

* `n` / `p` next / previous difference
* `1` keep disk · `2` use version · `3` both · `a` / `v` all disk / all version
* `e` edit the result (`Esc` back)
* `Ctrl+S` save resolution (the file is not changed; restoring the version applies it)
* `Ctrl+D` save progress · `q` close (asks about unsaved changes)

**Storage**

* buttons: Verify · GC preview · Run GC · Retention preview · Apply retention

Restores always show a **Preview** first, and replacing existing files needs the *Overwrite* tick.

---

Related: [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Local API](API.md)
