<div align="center">

<img src="gui/assets/undo.png" alt="Undo logo" width="128" height="128">

<h1>Undo</h1>

<p><strong>Local-first file version history for Windows and Linux.</strong><br>
Every version of every file in the folders you choose, kept automatically.</p>

<p>
  <a href="CHANGELOG.md"><img alt="Version 1.0.0" src="https://img.shields.io/badge/version-1.0.0-3D5A80?style=flat-square"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/Madhur-Prakash/Undo?style=flat-square"></a>
  <a href="https://github.com/Madhur-Prakash/Undo/commits"><img alt="Last commit" src="https://img.shields.io/github/last-commit/Madhur-Prakash/Undo?style=flat-square"></a>
  <a href="https://github.com/Madhur-Prakash/Undo/issues"><img alt="Issues" src="https://img.shields.io/github/issues/Madhur-Prakash/Undo?style=flat-square"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white">
  <img alt="Linux" src="https://img.shields.io/badge/Linux-systemd-FCC624?style=flat-square&logo=linux&logoColor=black">
</p>

<p>
  <img alt="Flutter" src="https://img.shields.io/badge/Flutter-desktop-02569B?style=flat-square&logo=flutter&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-local%20API-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite&logoColor=white">
  <img alt="Textual" src="https://img.shields.io/badge/Textual-TUI-5A4FCF?style=flat-square">
  <img alt="uv" src="https://img.shields.io/badge/built%20with-uv-DE5FE9?style=flat-square&logo=uv&logoColor=white">
  <img alt="Code style: ruff" src="https://img.shields.io/badge/code%20style-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black">
  <img alt="Type checked: mypy" src="https://img.shields.io/badge/types-mypy-2A6DB2?style=flat-square">
</p>

<p>
  <a href="docs/INSTALLATION.md">Installation</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="docs/CLI.md">CLI reference</a> &middot;
  <a href="gui/undo_desktop/README.md">Desktop app</a> &middot;
  <a href="docs/README.md">Documentation</a> &middot;
  <a href="CHANGELOG.md">Changelog</a> &middot;
  <a href="https://github.com/Madhur-Prakash/Undo/issues">Report an issue</a>
</p>

</div>

---

**Undo** watches the folders you choose and automatically keeps every version of every file: no
commits, no staging. Recover a file you overwrote, bring back one you deleted, or put a whole
directory back the way it was last Tuesday.

Think of Git, but for ordinary files, running quietly in the background.

> [!WARNING]
> **Undo is not a backup.** It keeps history on the *same machine*. Disk failure, theft or
> ransomware that reaches the Undo data directory destroys the history too. Keep an independent
> backup as well. See [Limitations](#limitations).

---

## Features

- **Automatic versioning**: a background daemon captures every content change (native
  notifications via inotify / ReadDirectoryChangesW, with polling fallback).
- **Never miss a change**: a reconciliation engine rescans tracked folders periodically and at
  startup, catching anything missed while the daemon was stopped or events were dropped.
- **Safe capture**: debouncing, stability checks, change-during-capture detection, bounded
  retries, streaming (multi-GB files never load into RAM).
- **Content-addressed storage**: BLAKE3-256 hashes, Zstandard compression (raw fallback when it
  does not help), whole-file deduplication, optional fixed-size chunk deduplication.
- **Integrity first**: every stored object is verified after writing and on every restore. Atomic
  publishing, crash recovery and safe garbage collection.
- **Recovery**: restore a file to the latest version, a specific version, a point in time or the
  version before a change. Recover deleted files. Restore whole directories. Dry runs everywhere.
- **Safe restore**: never overwrites silently. Overwriting needs an explicit flag, and the content
  being replaced is versioned first.
- **Renames and moves** keep their history. Search by current *or former* path.
- **Snapshots**: named, metadata-only checkpoints of a whole folder; compare and restore them.
- **Retention**: keep everything, the last N versions, N days, daily/weekly thinning, or a
  storage quota. Snapshots and the last content of deleted files are always protected.
- **Three interfaces, one backend**: `undo` CLI (Rich), `undo tui` (Textual) and a Flutter
  desktop app, all backed by the same authenticated local API.

## Screenshots

The desktop app (Flutter, Material 3) has six sections: Overview, Files, History, Snapshots,
Storage and Settings. Screenshots are not committed to the repository. Run `make gui` (or
`./make.sh gui`) to see the real application.

## Architecture

```
Filesystem ──► Watcher (watchdog: inotify / ReadDirectoryChangesW / polling)
                 │
                 ▼
           Event processor (bounded queue, debounce, backpressure) ◄── Reconciler (periodic scans)
                 │
                 ▼
           Capture engine ──► BLAKE3 ──► dedup ──► zstd ──► staging ──► verify ──► blobs/
                 │
                 ▼
           SQLite (WAL) metadata ──► UndoService ──► FastAPI (127.0.0.1, token) ──► CLI / TUI / GUI
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/STORAGE.md](docs/STORAGE.md).

## Supported platforms

| Platform | Monitoring | Autostart | GUI |
|---|---|---|---|
| Windows 10/11 | ReadDirectoryChangesW (polling fallback) | at sign-in, no admin needed (`undo service install`) or Windows service (pywin32) | Flutter Windows |
| Ubuntu / mainstream Linux | inotify (polling fallback) | systemd user or system unit | Flutter Linux (GTK) |
| Headless Linux servers | inotify / polling | systemd | not needed: CLI + TUI |

The Windows installer bundles everything. On Linux and from source, Undo needs Python 3.12+, which
uv installs for you.

## Installation

| Machine | How |
|---|---|
| **Windows 10/11** | Run `Undo-Setup-<version>.exe`, built from [`gui/installer/Undo.iss`](gui/installer/Undo.iss). It needs no admin rights or Python. It installs the app, the `undo` command and the daemon, and can start the daemon at sign-in. |
| **Linux server** | Install with uv, `undo init`, `undo track /path`, then `undo service install` and `sudo loginctl enable-linger $USER`. Use `undo tui` over SSH. |
| **Linux desktop** | Unpack the release archive from `python scripts/build.py` and run `./installer/install.sh`. It installs the app with a menu entry and the systemd user service. |

Step-by-step instructions for each, including the inotify limit, system services, upgrading,
uninstalling and building the installer: **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.
The Linux steps have not been run on a Linux machine yet.

### From source

Development checkout (needs [uv](https://docs.astral.sh/uv/)):

```sh
git clone https://github.com/Madhur-Prakash/Undo.git && cd Undo
uv sync --all-packages           # creates .venv with backend + CLI + dev tools
uv run undo --help
```

Install the `undo` command for your user:

```sh
uv tool install --editable ./cli --with-editable ./backend     # or: make install
```

## Quick start

```sh
undo init                         # create the data directory, database and API token
undo track ~/Documents            # start tracking a folder (captures its current state)
undo start                        # start the background daemon
undo status
```

Now edit, overwrite or delete files in `~/Documents` as usual.

## CLI examples

```sh
undo history ~/Documents/report.docx          # every version, rename and deletion
undo restore ~/Documents/report.docx --version 42 --to ~/Desktop/
undo restore ~/Documents/report.docx --at "2h"          # state two hours ago
undo restore ~/Documents/report.docx --at 2024-05-01T09:00 --overwrite
undo recover                                   # list deleted files
undo recover ~/Documents/old-notes.txt         # bring one back
undo restore ~/Documents/project --at 3d --dry-run   # preview a directory restore
undo snapshot create --name before-cleanup
undo snapshot diff before-cleanup after-cleanup
undo search invoice                             # matches former paths too
undo log --since 1d
undo storage stats
undo storage verify
undo storage gc --dry-run
undo exclude add "*.iso"
undo settings set capture.max_file_size 2GB
undo history notes.txt --json                    # machine-readable output
undo tui                                         # interactive dashboard
```

Every command and option: [docs/CLI.md](docs/CLI.md).

## GUI

Full details: [gui/undo_desktop/README.md](gui/undo_desktop/README.md).

```sh
make gui            # or ./make.sh gui    (flutter run -d windows|linux)
```

The app finds the daemon through the data directory (`daemon.json` + `api_token`) and **starts it
automatically** when it is not running (`daemon.autostart`, on by default): the installed app runs
its bundled `backend\undo-daemon.exe`; a development build uses the `undo` command (set `UNDO_CLI`
if `undo` is not on `PATH`). Every button calls the real backend.

- **Overview**: daemon status, totals, savings, tracked roots (add, scan, pause, untrack), recent changes and snapshots
- **Files**: search live and deleted files, open a file's full history, restore or compare any version
- **History**: chronological list of all changes; click for version details (hash, compression, restore, compare, preview)
- **Snapshots**: create, compare two, restore (with preview), delete
- **Storage**: usage, dedup/compression savings, verify integrity, garbage collection and retention previews
- **Settings**: compression, retention, monitoring, exclusions, performance, autostart, theme

### Windows installer

`gui/installer/Undo.iss` builds a complete installer with Inno Setup 7: open it and choose
Build > Compile (or `ISCC gui/installer/Undo.iss`). Compiling:

* runs `uv sync`,
* builds the backend with PyInstaller: `undo.exe` and the windowless `undo-daemon.exe`, from
  `gui/installer/Undo.spec`,
* builds `Undo.exe` with Flutter,
* writes `gui/installer/Undo-Setup-<version>.exe`.

The build machine needs uv and Flutter (with Visual Studio's C++ desktop workload). The machine
you install on needs neither. See
[docs/INSTALLATION.md](docs/INSTALLATION.md#windows).

## How storage works

Each distinct file content is stored once, at `blobs/<first two hex chars>/<blake3>.zst`.
The hash is computed from the **original** content, so identical files (or a file changed back to an
earlier state) cost nothing extra. Data is compressed with Zstandard (level 3 by default; set 1 for
speed or up to 22 for archival). Formats that are already compressed (`.jpg`, `.zip`, `.mp4`, ...) and
data that does not shrink are stored raw. Every object is decompressed and re-hashed before it is
published, and again on every restore. Details: [docs/STORAGE.md](docs/STORAGE.md).

## Recovery examples

```sh
# I overwrote a file an hour ago
undo restore budget.xlsx --at 1h --overwrite      # current content is saved as a version first

# I deleted a folder
undo recover ~/Documents/thesis                    # recovers every deleted file below it

# Put a directory back as it was yesterday, into a separate folder for inspection
undo restore ~/code/site --at 1d --to /tmp/site-yesterday

# Undo a bulk change using a snapshot taken before it
undo snapshot restore before-cleanup --overwrite
```

Guarantees and failure handling: [docs/RECOVERY.md](docs/RECOVERY.md).

## Limitations

- **Not a backup.** History lives on the same disk as your data. Use a separate backup (another
  disk, NAS or offsite) for hardware failure, theft and disasters.
- **Ransomware.** Malware running as your user can usually also delete or encrypt the Undo data
  directory. Undo may help with ransomware that only touches documents, but cannot guarantee it.
  See [docs/RECOVERY.md](docs/RECOVERY.md#ransomware) for hardening (separate account, protected copies).
- Files that are written continuously (databases, VM disks, mail stores) may be captured in an
  internally inconsistent state; snapshot them with their own tools, or exclude them.
- Files held with exclusive locks on Windows are reported as *temporarily unavailable* and retried.
- Only file **content**, modification time and permission bits are versioned. ACLs, ownership
  (except as root on Linux), extended attributes and alternate data streams are not, and restore
  output says so explicitly.
- Empty directories and symlinks themselves are not versioned. Symlinks are not followed by
  default, and never outside the tracked folder.
- A snapshot is consistent at the metadata level; the scan before it is not an atomic filesystem
  snapshot of files that change while it runs.
- The Windows USN journal is only probed (it needs administrator rights). Reconciliation uses
  directory scanning, which works everywhere.

## Documentation

Start at the **[documentation index](docs/README.md)**, which says where to look for each task.

| Document | Contents |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Windows installer, Linux server, Linux desktop, from source; services, upgrading, uninstalling, building the installer |
| [docs/CLI.md](docs/CLI.md) | Every `undo` command and option, settings reference |
| [docs/RECOVERY.md](docs/RECOVERY.md) | Getting files back in common situations, and the limits of what Undo protects |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the daemon, storage, database, API and interfaces fit together |
| [docs/STORAGE.md](docs/STORAGE.md) | Content-addressed storage, compression, deduplication, integrity and garbage collection |
| [docs/API.md](docs/API.md) | The local HTTP API ([OpenAPI schema](docs/API_OPENAPI.json)) |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems and their fixes |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Dev setup, running each part, tests and checks, trying changes on a real install, releasing |
| [gui/undo_desktop/README.md](gui/undo_desktop/README.md) | The desktop app: screens, how it finds the daemon, building it, code layout |
| [gui/installer/Undo.iss](gui/installer/Undo.iss) | The Windows installer script (Inno Setup 7); comments at the top explain the build |
| [CHANGELOG.md](CHANGELOG.md) | Changes in each version |
| [LICENSE](LICENSE) | MIT license |

## Development

```sh
make init       # or ./make.sh init: uv sync, a separate .dev-home/ data directory, flutter pub get
make backend    # run the daemon in the foreground against .dev-home/
make test       # unit + integration (make test-stress for stress tests)
make lint typecheck
```

To try your changes on a **real installation** (the installer build on Windows, the systemd
service on a server), install the checked-out code with the update scripts:

```sh
bash scripts/update_windows.sh      # Windows (Git Bash): build the installer from this checkout and install it
bash scripts/update_linux.sh        # Linux: reinstall from this checkout and restart the daemon
```

Full guide: **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**.

| Script | Purpose |
|---|---|
| [scripts/dev.py](scripts/dev.py) | Task runner behind `make` and `./make.sh` |
| [scripts/build.py](scripts/build.py) | Python wheels, desktop build, Linux release archive |
| [scripts/release.py](scripts/release.py) | `python scripts/release.py X.Y.Z` sets the version everywhere |
| [scripts/update_linux.sh](scripts/update_linux.sh) | Update a Linux install to the checked-out code and restart the daemon (`--pull` to `git pull` first) |
| [scripts/update_windows.sh](scripts/update_windows.sh) | Build the Windows installer from the checked-out code and install it silently (Git Bash) |

License: MIT (see [LICENSE](LICENSE)). Changes in each version: [CHANGELOG.md](CHANGELOG.md).
