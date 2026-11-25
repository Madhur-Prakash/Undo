# Development

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · **Development** · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md) · [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md)
How to work on Undo: set up a checkout, run each part, check your changes, and try them on a real
installation with the update scripts. For how to report bugs and open pull requests, see
[CONTRIBUTING.md](../CONTRIBUTING.md); for security problems, [SECURITY.md](../SECURITY.md).

**On this page:**

* [Repository layout](#repository-layout)
* [Setup](#setup)
* [Running each part](#running-each-part)
* [Checks before you commit](#checks-before-you-commit)
* [Trying your changes on a real install](#trying-your-changes-on-a-real-install)
* [Releasing](#releasing)
* [Conventions](#conventions)

---

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | `undo_core`: storage, versioning, file watching, restore, the daemon and its API. Tests in `backend/tests/`. |
| `cli/` | `undo_cli`: the `undo` command (Typer + Rich) and the terminal dashboard (Textual) |
| `gui/undo_desktop/` | The Flutter desktop app ([its README](../gui/undo_desktop/README.md)) |
| `gui/installer/` | Windows installer: `Undo.iss` (Inno Setup 7), `Undo.spec` (PyInstaller), entry points |
| `gui/assets/` | The app icon (`undo.ico`, `undo.png`) |
| `services/` | systemd unit and scripts (Linux), pywin32 service (Windows) |
| `packaging/linux/` | Linux release-archive installer and `.desktop` entry |
| `scripts/` | Task runner, build, release, update scripts (below) |
| `docs/` | This documentation |

The backend is the only place with logic. The CLI, the dashboard and the app all call the same
operations: in-process, or through the daemon's API. See [Architecture](ARCHITECTURE.md).

## Setup

You need:

* [uv](https://docs.astral.sh/uv/). It installs Python 3.12 from `.python-version`.
* For the app: [Flutter](https://flutter.dev).
* On Windows: Visual Studio 2022 with *Desktop development with C++*.

```sh
git clone https://github.com/Madhur-Prakash/Undo.git && cd Undo
make init            # or: ./make.sh init   (Git Bash / no make)   or: python scripts/dev.py init
```

`make init`:

* runs `uv sync --all-packages`, which creates `.venv` with the backend, CLI and dev tools;
* initialises a **separate development data directory**, `.dev-home/`;
* runs `flutter pub get`.

All `make` targets that run Undo use `UNDO_HOME=.dev-home`, so development never touches the
history of an Undo you have installed.

Every target works three ways: `make <target>`, `./make.sh <target>` (Git Bash on Windows) and
`python scripts/dev.py <target>`.

| Target | What it does |
|---|---|
| `init` | `uv sync`, initialise `.dev-home/`, `flutter pub get` |
| `backend` | Run the daemon in the foreground with logs on the console (`.dev-home`) |
| `cli ARGS="…"` | Run `undo …` against `.dev-home`, e.g. `make cli ARGS="status"` |
| `tui` | The terminal dashboard against `.dev-home` |
| `gui` | `flutter run` the desktop app against `.dev-home` |
| `test` | Unit and integration tests (no stress) |
| `test-unit` · `test-integration` · `test-stress` | One group of tests |
| `lint` · `format` · `typecheck` | ruff (+ `flutter analyze`) · ruff format (+ `dart format`) · mypy |
| `install` | Put an **editable** `undo` on your `PATH` with `uv tool` (follows the checkout) |
| `build` | Wheels, desktop build, and on Linux the release archive ([scripts/build.py](../scripts/build.py)) |
| `docs` | Regenerate [API_OPENAPI.json](API_OPENAPI.json) from the FastAPI app |
| `clean` | Remove caches and build outputs |

## Running each part

Start the daemon in one terminal and use it from another:

```sh
make backend                       # daemon, console logs, data in .dev-home/
make cli ARGS="track ~/scratch"    # a throwaway folder to experiment with
make cli ARGS="status"
make tui
make gui
```

Without `make`, run the same things with an explicit data directory:

```sh
export UNDO_HOME="$PWD/.dev-home"          # PowerShell: $env:UNDO_HOME = "$PWD\.dev-home"
uv run undo init
uv run python -m undo_core.daemon --console-log
uv run undo track ~/scratch
```

Use a throwaway folder such as `~/scratch` while developing, not your real documents.

## Checks before you commit

```sh
make format        # ruff format + autofix, dart format
make lint          # ruff check, flutter analyze
make typecheck     # mypy on backend and CLI (untyped functions are checked too)
make test          # unit + integration (about 1.5 minutes)
make test-stress   # optional: concurrency and GC/capture races
cd gui/undo_desktop && flutter test
```

| Folder | What it tests |
|---|---|
| `backend/tests/unit/` | Hashing, blob store, exclusions, settings, versioning, retention and GC, restore safety, autostart, checkpoint |
| `backend/tests/integration/` | A real daemon (watcher, API, auth, ownership, restart), the CLI, the TUI |
| `backend/tests/filesystem/` | Event processing, symlinks, case sensitivity, permissions |
| `backend/tests/recovery/` | Crash recovery |
| `backend/tests/stress/` | Many files, concurrent captures, GC racing with capture |

Tests that cannot run on a platform skip themselves with a reason. For example, symlink tests
need Developer Mode on Windows, and POSIX-permission tests need Linux.

## Trying your changes on a real install

* Tests run against throwaway data directories.
* To see a change working on a **real installation**, use the update scripts. That covers
  autostart, the real data directory, the installed app, and the server's systemd service.
* The scripts install **whatever code is checked out**: a local branch as well as `git pull`.

### On Windows (Git Bash)

```sh
bash scripts/update_windows.sh                # build Undo-Setup-<version>.exe from this checkout, install it silently
bash scripts/update_windows.sh --no-build     # reinstall the installer you built last (seconds)
bash scripts/update_windows.sh --dev          # for a `uv tool install` setup instead of the installer
bash scripts/update_windows.sh --pull         # git pull first
```

The default mode tests exactly what users get: the frozen `undo.exe` and `undo-daemon.exe`, the
Flutter release build and the installer's steps. It:

1. builds the installer (logs in `gui/installer/build/`),
2. closes the app and stops the daemon,
3. installs silently with *start at sign-in* and *add to PATH*,
4. prints `undo --version`, `undo status` and `undo service status`.

Then open a **new** terminal and try your change with `undo …`, or open the app.

### On a Linux server

```sh
cd ~/undo
git fetch && git checkout my-branch           # or: git pull
bash scripts/update_linux.sh                  # reinstall from this checkout, restart the daemon
bash scripts/update_linux.sh --editable       # editable install (see below)
bash scripts/update_linux.sh --pull           # git pull first
```

The script:

* detects how the daemon runs: systemd user service, system service, `undo start`, or not
  running;
* stops it and reinstalls;
* applies migrations and new default settings (`undo init`);
* restarts the daemon, waits until it answers, and prints `undo status`.

**`--editable`** installs the checkout itself rather than a copy. After that, Python edits on the
server only need a daemon restart (`systemctl --user restart undo`), not a reinstall. That is
handy while iterating on a server; switch back with a plain `update_linux.sh` run.

### What to check after an update

```sh
undo --version
undo status              # daemon running, no "Recent errors", counts going up
undo service status      # autostart still installed
undo logs -n 50          # anything unexpected at startup
```

A schema migration or a new settings default is applied on the first start of the new code.
Data written by an older version stays readable.

## Releasing

1. Move the *Unreleased* entries in [CHANGELOG.md](../CHANGELOG.md) under a new version heading.
2. Set the version everywhere: `python scripts/release.py X.Y.Z`. This updates both Python
   packages, `__version__` and the Flutter `pubspec.yaml`, then builds.
3. Run the checks above, then build the Windows installer
   ([how](INSTALLATION.md#building-the-installer)). It is named `Undo-Setup-X.Y.Z.exe`.
4. Build the Linux release archive **on a Linux machine** (any one with uv and the checkout; with
   Flutter installed it also contains the desktop app, without it the archive is server-only):

```sh
cd ~/undo
git pull
python3 scripts/build.py              # writes dist/undo-linux.tar.gz
sha256sum dist/undo-linux.tar.gz      # line for SHA256SUMS.txt
```

5. Copy the archive to the computer you publish from (run this **there**), or upload it from the
   Linux machine with `gh release upload vX.Y.Z dist/undo-linux.tar.gz`:

```sh
scp user@server:~/undo/dist/undo-linux.tar.gz .
```

6. Write `SHA256SUMS.txt` with one line per file (`sha256sum Undo-Setup-X.Y.Z.exe undo-linux.tar.gz`).
7. Commit, tag `vX.Y.Z`, push, and attach `Undo-Setup-X.Y.Z.exe`, `undo-linux.tar.gz` and
   `SHA256SUMS.txt` to a GitHub release.

## Conventions

* Python 3.12+, type-annotated and checked with mypy, formatted and linted with ruff.
* All business logic lives in `undo_core`. Clients only call `UndoService` operations, through
  `LocalBackend` or the API.
* Every write goes through a short `BEGIN IMMEDIATE` transaction. Slow work (hashing,
  compression) happens before it. See [Architecture › Concurrency model](ARCHITECTURE.md#concurrency-model).
* Never write file content without verifying it, and never overwrite a user's file without
  versioning it first. See [Recovery › Restore guarantees](RECOVERY.md#restore-guarantees).
* New behaviour gets a test. User-visible changes get a [CHANGELOG](../CHANGELOG.md) entry and,
  if needed, a docs update.

---

Related: [Architecture](ARCHITECTURE.md) · [Installation › Building the installer](INSTALLATION.md#building-the-installer) · [Troubleshooting](TROUBLESHOOTING.md)
