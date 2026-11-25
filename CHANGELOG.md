# Changelog

All notable changes to Undo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

## [1.0.0] - 2026-11-24

First release.

### Added

#### Version history

- Automatic version capture for tracked folders: every create, modify, rename, move and delete
  is recorded, from any application. Each version keeps size, timestamps, content hash and
  the operation.
- Changes are captured once a file has stopped changing, so a file still being written is not
  recorded half-done. Bursts of events are debounced, and the event queue is bounded so heavy
  activity cannot exhaust memory.
- Rename and move detection, so a file keeps one history across new names and folders.
- Named snapshots of a whole folder, which can be compared and restored.
- Retention rules that thin out old versions on a schedule (`retention.*` settings), with a
  preview before anything is deleted, and can be applied on demand (`undo storage gc --retention`,
  *Apply retention now* in the app, *Apply retention* in the TUI).
- Exclusion rules: built-in, default and your own (`undo exclude`). Hidden-file and file-size
  limits are configurable.
- Default exclusions for installed and built packages, which change constantly and are not
  your work: Python wheels and eggs (`*.whl`, `*.egg`, `*.egg-info/`, `.eggs/`), environments
  (`venv/`, `site-packages/`, `__pypackages__/`, `.nox/`), `*.pyc`/`*.pyo`; Node package stores
  (`.npm/`, `.pnpm-store/`, `.yarn/`, `bower_components/`, `jspm_packages/`); Rust build output
  and homes (`target/`, `.cargo/`, `.rustup/`, `*.crate`); log files (`*.log`). Later versions add new defaults to
  existing installs once, on upgrade (`exclusions.defaults_version`); a default you removed is
  never added back.
- Undo refuses to track its own data folder and, in installed builds, its program folder
  (`%LOCALAPPDATA%\Programs\Undo`).
- Side-by-side comparison of two versions in the app, `undo diff` and `undo tui`, like an editor's
  git diff: old on the left, new on the right, changed characters highlighted, `+added -removed`
  counts. The app can switch to an inline view; `undo diff -u` prints a unified diff. Lines are
  compared without their endings, so a CRLF/LF change is reported as a note instead of marking
  every line as changed.
- Sorting for files, history and snapshots in the app, `undo tui` and the CLI. Each sort key
  starts in its natural order (names A to Z, times newest first, sizes and counts largest first)
  and can be reversed. Files are sorted by the daemon before paging
  (`GET /files?sort=&descending=`).

#### Storage

- Content-addressed storage with BLAKE3 hashes: identical content is stored once, across all
  files and versions.
- Zstandard compression, with the raw bytes kept when compression would not save space.
- Optional fixed-size chunk deduplication for large files (off by default).
- Crash-safe writes: content goes to a staging file, is synced and verified, then published
  under its hash. Leftovers from a crash are cleaned up at the next start.
- `undo storage verify` checks stored content against its hashes. `undo storage gc` removes
  content no version uses, and is safe to run while files are being captured.
- SQLite metadata in WAL mode, with schema migrations.

#### Restore and recovery

- Restore a file or folder by version, by time (`--at 2h`, `--at 2024-05-01T09:00`) or to the
  version before a given one. Restore to the original place or to another folder (`--to`).
- Restores never overwrite silently. Replacing an existing file needs `--overwrite` or
  confirmation, and the current content is saved as a version first.
- Every restore is checked against its hash before it is written. Damaged content never reaches
  the destination, and no partial or temporary file is left behind.
- `--dry-run` shows exactly what a restore would do.
- Recover deleted files and folders (`undo recover`).
- Roll back a tracked folder (or a subfolder) to a point in time, with a preview first; no
  snapshot needed (`undo restore FOLDER --at TIME`, or *Roll back* on the app's *Overview*).
- Remove history on purpose: a file's or a folder's whole history, only versions older than a
  date (each file's latest version is kept), or single versions. Previewed first; snapshot
  versions are kept; files are never touched. Available everywhere: `undo forget` and
  `undo delete-versions`, *Delete history* and the per-version delete in the app, and `f` / `x`
  in the TUI.

#### Daemon

- Background daemon watching tracked folders: ReadDirectoryChangesW on Windows, inotify on
  Linux. It falls back to polling when native watching is unavailable or the inotify limit is
  reached.
- Periodic and startup rescans catch changes made while the daemon was stopped or events were
  missed.
- Only one daemon or writing command can own a data directory at a time. The lock is released by
  the OS if the process dies, so a crash never leaves a stale lock.
- Local HTTP API (FastAPI) on `127.0.0.1` only, protected by a token stored in the data
  directory. It is used by the CLI, the TUI and the desktop app.
- Health reporting: watcher state, queue depth, pending captures, recovery results (`undo status`,
  `undo doctor`, `undo logs`).
- Autostart: at sign-in on Windows (per-user Run key, no admin needed), or a systemd user or
  system unit on Linux
  (`undo service install`).

#### Command line and TUI

- `undo` command (Typer + Rich) with these command groups:
  - setup: `init`, `config`, `track`, `untrack`, `roots`, `scan`, `skipped`
  - daemon: `start`, `stop`, `restart`, `status`, `doctor`, `logs`, `service`
  - history: `history`, `versions`, `files`, `log`, `search`, `show`, `diff`, `cat`
  - recovery: `restore`, `recover`
  - groups of subcommands: `snapshot`, `storage`, `exclude`, `settings`
  
  Most commands take `--json` for scripts. Lists sort with `--sort KEY` and `--reverse`
  (`undo files`, `undo log`, `undo snapshot list`).
- The CLI talks to the daemon when one is running, and works directly on the data otherwise.
- `undo tui`: a full-screen terminal dashboard (Textual) with tracked folders, files, history,
  restore, snapshots, storage and settings. It works over SSH.

#### Desktop app

- Flutter desktop app for Windows and Linux (Riverpod, GoRouter, Dio, Material 3, light and dark
  themes). Its screens are Overview, Files, History, Snapshots, Storage and Settings, plus version
  details, preview, diff and a restore dialog that shows what will happen first.
- Starts the daemon automatically when it is not running (`daemon.autostart`).
- Click a tracked folder on *Overview* to see its files. *Pause* stops recording a folder and
  keeps its history; *Stop tracking* also deletes the folder's recorded history, after a
  confirmation that says how much (`undo untrack --purge`). Neither touches the files themselves.
- Native folder picker with no Flutter plugins, so Windows Developer Mode is not needed to build.
- App icon: a bold counter-clockwise arrow ring with a violet-to-blue gradient on a light tile
  (`gui/assets/undo.ico`, `gui/assets/undo.png`).

#### Installation and packaging

- Windows installer `Undo-Setup-1.0.0.exe`, built from `gui/installer/Undo.iss` (Inno Setup 7):
  - per user, with no admin rights or Python needed;
  - bundles the app, `undo.exe` and the windowless `undo-daemon.exe`;
  - options to start the daemon at sign-in and to add `undo` to `PATH`;
  - upgrades stop the daemon first; uninstalling asks before deleting history.
- Linux release archive with `installer/install.sh` / `uninstall.sh`. It installs the systemd user
  service and adds the app with a menu entry (`.desktop` file and icon).
- systemd unit and scripts for a system-wide Linux service. pywin32 wrapper for a machine-wide
  Windows service.
- Development tooling: uv workspace, `Makefile` and `make.sh`, `scripts/dev.py`, `build.py`,
  `release.py`.
- `scripts/update_linux.sh` and `scripts/update_windows.sh`: update Undo to the checked-out code
  (optionally `--pull` first) and restart the daemon, whichever way it runs (systemd user or
  system service, plain `undo start`; on Windows by building and silently running the
  installer).

#### Documentation

- `README.md`, plus guides in `docs/`: architecture, storage, CLI, API (with the generated
  OpenAPI file), installation, recovery and troubleshooting, with an index (`docs/README.md`)
  and a development guide (`docs/DEVELOPMENT.md`). Every page has the same navigation bar.
- `CONTRIBUTING.md` (reporting bugs, making a change, checks, the rules the code follows) and
  `SECURITY.md` (supported versions, reporting vulnerabilities privately, what is in scope),
  linked from the README, the documentation index and every page's navigation bar.

### Known limitations

- Undo is not a backup. History lives on the same disk as your files, so it does not survive
  disk failure, theft or ransomware that reaches the data directory. Keep independent backups.
- Tested on Windows 11. The Linux code paths (inotify, systemd, the Linux app build and install
  scripts) have not yet been run on Linux.
- The machine-wide Windows service (pywin32) has not been tested. The tested way to start at
  sign-in is `undo service install`.
- The Windows USN journal is only detected, not used, because it needs administrator rights.
  Missed changes are found by rescanning folders instead.
- Empty folders and symlinks themselves are not versioned, and symlinks are not followed by
  default.
- The desktop app cannot connect to a daemon on another machine: the API listens on `127.0.0.1`
  only. On servers, use `undo tui` over SSH.

[1.0.0]: https://github.com/Madhur-Prakash/Undo/releases/tag/v1.0.0
