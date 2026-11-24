# CLI reference

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · **CLI** · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md)

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
| `undo doctor [--json]` | Check writability, database integrity, disk space, token permissions, roots, blob health, monitoring backend, inotify limits. Exit 1 on errors. |

## Tracking

| Command | Description |
|---|---|
| `undo track PATH [--no-scan]` | Track a folder and everything below it. Relative paths such as `.` are resolved first. Overlapping roots, the data directory and (installed builds) Undo's program folder are refused. With a daemon running the first scan happens in the background; without one it runs in the terminal (`--no-scan` skips it). |
| `undo untrack PATH\|ID [--purge] [-y]` | Stop monitoring; history kept. `--purge` deletes the root's history (data reclaimed by `gc`). |
| `undo roots` | List roots with file/version counts, last scan and monitoring mode. |
| `undo scan [PATH\|ID] [--deep]` | Reconcile now (all roots, one root, or a sub-directory). `--deep` re-hashes every file. |
| `undo skipped [--root R] [-n N]` | Files not captured and why (`excluded:<pattern>`, `too_large`, `permission_denied`, `symlink_not_followed`, `temporarily_unavailable`, …). |

## Daemon

| Command | Description |
|---|---|
| `undo start [-f/--foreground]` | Start the background daemon (detached) or run it in this terminal. |
| `undo stop` | Graceful shutdown via the API. |
| `undo restart` | Stop and start. |
| `undo status [--json]` | Daemon state, queue, watchers, recent errors, totals. Works without a daemon. |
| `undo logs [-n N] [-f] [--raw]` | Show / follow the JSON log, pretty-printed. |
| `undo service install [--system]` | Autostart. Linux: systemd user unit (`--system` as root for a system unit). Windows: starts the daemon at sign-in through the per-user Run key (value `Undo`; no admin needed), and starts it now. |
| `undo service status` | Whether autostart is installed. Windows: the registered command. Linux: `systemctl --user is-enabled undo`. |
| `undo service uninstall [--system]` | Removes autostart. A running daemon keeps running until `undo stop`. |

## History

| Command | Description |
|---|---|
| `undo history PATH [-n N]` | File summary, former paths and every version (operation, time, size, hash). |
| `undo versions PATH` | Compact list of version ids. |
| `undo files [QUERY] [--root R] [-d] [-s KEY] [-r]` | List tracked files. `--sort` by `path` (default), `modified`, `size`, `version` (latest change) or `versions` (number of versions); `-d` includes deleted files. |
| `undo log [-n N] [--since 1d] [--root R] [-s KEY] [-r]` | Recent changes across roots, newest first. `--sort` by `time`, `path`, `size` or `operation`. |
| `undo search QUERY` | Match current and former paths. |
| `undo show VERSION` | Version details: hash, compression, storage, references, neighbours. |
| `undo diff A B [-u]` | Side-by-side diff of two text versions: old on the left, new on the right, changed characters highlighted, `+added -removed` summary. `-u` (or a terminal under 100 columns) prints a unified diff. Line-ending changes (CRLF/LF) are ignored and reported in the summary. |
| `undo cat VERSION` | Print a text version. |

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
| `undo snapshot delete ID\|NAME [-y]` | Delete (versions remain). |

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
| `retention.*` | keep_all | see STORAGE.md |
| `exclusions.defaults` | VCS dirs, tool caches, temp/swap files; Python wheels, eggs, `site-packages/`, `venv/`, `*.pyc`; Node `node_modules/`, `.npm/`, `.pnpm-store/`, `.yarn/`; Rust `target/`, `.cargo/`, `.rustup/`, `*.crate` | `undo exclude list` shows them all; `undo exclude remove PATTERN` drops one (e.g. `target/` if you keep your own folder named *target*) |
| `exclusions.defaults_version` | 2 | which release of the default list yours is up to date with; new defaults are added once on upgrade, removed ones never come back |
| `api.host` / `api.port` | 127.0.0.1 / 47821 | loopback only unless `api.allow_remote` |
| `daemon.autostart` | true | GUI/TUI start the daemon when needed |
| `daemon.gc_interval_seconds` / `gc_grace_seconds` | 86400 / 3600 | |
| `daemon.verify_interval_seconds` | 0 | scheduled verification (0 = off) |
| `daemon.log_level` | INFO | |
| `ui.theme` | system | GUI theme |

## Terminal UI

`undo tui` opens a full-screen dashboard; it works over SSH.

| Where | Keys |
|---|---|
| Everywhere | `1`–`7` switch tabs (Dashboard, Roots, Files, History, Snapshots, Storage, Settings) · `F5` / `Ctrl+R` refresh · `q` quit |
| Roots | `a` add · `s` scan · `e` enable/disable · `x` untrack |
| Files | type to search · tick *Include deleted* · `Enter` opens the file's history |
| File history | `v` view content · `d` compare with previous (side by side) · `i` details · `r` restore · `Esc` back |
| Snapshots | `c` create · `d` compare · `r` restore · `x` delete |

Restores always show a **Preview** first, and replacing existing files needs the *Overwrite* tick.

---

Related: [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Local API](API.md)
