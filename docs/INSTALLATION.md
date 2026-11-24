# Installation

> **Undo docs** · [Index](README.md) · **Installation** · [CLI](CLI.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md)

Pick the section for your machine:

| Machine | How | You need |
|---|---|---|
| Windows 10/11 | [`Undo-Setup-<version>.exe`](#windows) | Nothing: Python and the daemon are bundled |
| Linux server (no desktop) | [`undo` command + systemd](#linux-server) | `git`, `curl`, and `sudo` for two optional steps |
| Linux desktop | [Release archive](#linux-desktop) with `installer/install.sh` | uv, and a desktop for the app |
| Development, any OS | [From source](#from-source-development) | uv; Flutter for the app |

Undo keeps its version history, settings and API token in one **data directory** per user:

| OS | Data directory |
|---|---|
| Windows | `%LOCALAPPDATA%\Undo` |
| Linux | `$XDG_DATA_HOME/undo`, or `~/.local/share/undo` |

Set `UNDO_HOME` (or pass `--data-dir`) to use another directory. The desktop app honours
`UNDO_HOME` too. Uninstalling never deletes this directory unless you ask it to.

**Tested so far:**

* Windows 11: everything except the machine-wide Windows service.
* Ubuntu: the Linux server steps (user service, linger, exclusions).
* Not yet run: the Linux desktop app and release archive.

Before you track anything, read [Choosing what to track](#choosing-what-to-track).

**On this page:**

* [Choosing what to track](#choosing-what-to-track)
* [Windows](#windows): [install](#1-install) · [check](#2-check-the-installation) · [track](#3-track-folders) · [start at sign-in](#starting-at-sign-in) · [update](#updating) · [uninstall](#uninstalling) · [build the installer](#building-the-installer)
* [Linux server](#linux-server): [steps 1–7](#1-install-uv) · [update](#updating-1) · [stop and logs](#stopping-restarting-logs) · [fix a wrong folder](#fixing-a-wrong-folder) · [remove](#removing-undo)
* [Linux desktop](#linux-desktop)
* [From source](#from-source-development)
* [Using Undo](#using-undo-any-platform)

---

## Choosing what to track

* `undo track FOLDER` covers that folder and **everything below it**: all subfolders at any
  depth, including ones created later.
* Track the few top-level folders where your own work lives, such as a project folder,
  `Documents` or `/srv/data`.
* You do not need to track each subfolder.

Do **not** track:

| Folder | Why |
|---|---|
| Your whole home folder (`~`, `C:\Users\you`) | It holds caches, browser profiles and app data that change constantly. They would fill Undo's storage, and a home folder can have hundreds of thousands of files. |
| System folders (`C:\Windows`, `/usr`, `/var`) | Constantly changing, many files are locked, and not your work |
| Undo's data directory or program folder | Refused: Undo would record itself |

Already skipped by default, inside any tracked folder (`undo exclude list` shows the full list):

| Kind | Patterns |
|---|---|
| Version control | `.git/`, `.hg/`, `.svn/` |
| Python | `.venv/`, `venv/`, `site-packages/`, `__pycache__/`, `*.whl`, `*.egg-info/`, `*.pyc`, tool caches |
| Node | `node_modules/`, `.npm/`, `.pnpm-store/`, `.yarn/` |
| Rust | `target/`, `.cargo/`, `.rustup/` |
| Temporary and lock files | `*.tmp`, `*.swp`, `~$*` and similar |
| Log files | `*.log` |

Add your own exclusions for anything else that is generated or downloaded, **before** the first
scan:

```sh
undo exclude add "dist/"          # a folder name, anywhere in tracked folders
undo exclude add "*.bak"          # a file pattern
undo exclude add "data/raw"       # a path relative to the tracked folder
undo exclude list
```

**The first scan** reads, hashes and compresses every file once. On big trees (100,000+ files or
several GB) that takes minutes, so let the daemon do it in the background (see the Linux steps).
Later scans only look at files whose size or modification time changed, so they are fast.

---

## Windows

### 1. Install

Download `Undo-Setup-<version>.exe` from the
**[latest release](https://github.com/Madhur-Prakash/Undo/releases/latest)** (always the newest
version; older ones are on the [Releases page](https://github.com/Madhur-Prakash/Undo/releases)).

Run it. It installs for your account only, needs no administrator rights,
and installs into `%LOCALAPPDATA%\Programs\Undo`. Keep the first two options ticked:

| Option | Default | What it does |
|---|---|---|
| Start the Undo daemon when I sign in | on | Runs `undo service install`. It adds the value `Undo` to your per-user Run key, so the daemon starts at every sign-in and records changes even when the app is closed. You can switch it off under *Settings > Apps > Startup*. |
| Add the undo command to PATH | on | Adds `%LOCALAPPDATA%\Programs\Undo\backend` to your user `PATH`, so `undo` and `undo tui` work in any **new** terminal |
| Create a desktop shortcut | off | A desktop icon for the app |

Setup also creates the data directory (`undo init`), starts the daemon, and offers to open the
app.

### 2. Check the installation

Open a **new** terminal. Terminals that were already open still have the old `PATH`; in VS Code,
close and reopen VS Code. Then run:

```powershell
undo --version            # undo 1.0.0
(Get-Command undo).Source # ...\AppData\Local\Programs\Undo\backend\undo.exe
undo status               # daemon  running
undo service status       # autostart at sign-in: installed
```

If `undo service status` says *not installed*, run `undo service install`.

### 3. Track folders

In the app: **Overview > Track folder**, then pick the folder. From a terminal:

```powershell
undo track "C:\Users\you\Documents"
cd C:\code\my-project
undo track .              # the folder you are in
undo roots                # what is tracked
```

Then check that changes are recorded:

* Edit and save a file in a tracked folder.
* A couple of seconds later, `undo history FILE` shows a `CREATE` and a `MODIFY` entry.
* Day-to-day use: [Using Undo](#using-undo-any-platform).

### Installed files

```
%LOCALAPPDATA%\Programs\Undo\
  Undo.exe                 the desktop app
  data\, flutter_windows.dll
  backend\
    undo.exe               the command line and `undo tui`
    undo-daemon.exe        the daemon (no console window)
    _internal\             Python runtime and libraries
```

The Start menu has **Undo**, and **Undo (terminal dashboard)**, which opens `undo tui`. The
app starts the daemon itself if it is not running.

### Starting at sign-in

* The daemon starts at sign-in through the value `Undo` in
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
* That value runs `"…\Programs\Undo\backend\undo-daemon.exe" --data-dir "…\Undo"`.
* No administrator rights are needed.

```powershell
undo service status       # installed or not, and the registered command
undo service install      # add it, and start the daemon now
undo service uninstall    # remove it
```

* It starts at **sign-in**, not at boot.
* Changes made while you are signed out are found by the rescan the daemon runs when it starts.
* To record changes when nobody is signed in, use the
  [machine-wide service](#machine-wide-windows-service-optional-advanced).

### Updating

Run the newer `Undo-Setup-<version>.exe` and keep the options ticked. Setup:

* asks you to close the app,
* stops the daemon cleanly,
* replaces the programs,
* re-registers start-at-sign-in and starts the new daemon.

Your history and settings are kept, and new default exclusions are added to your list once. There
is no separate "reload" step on Windows: the installer does the whole restart.

**From source, after `git pull`:** one command in Git Bash builds the installer from your checkout
and installs it silently:

```sh
bash scripts/update_windows.sh --pull
```

[`scripts/update_windows.sh`](../scripts/update_windows.sh):

1. builds `Undo-Setup-<version>.exe` with Inno Setup. This needs uv, Flutter and Visual Studio;
   see [Building the installer](#building-the-installer).
2. closes the app and stops the daemon,
3. runs Setup silently with *start at sign-in* and *add to PATH* on (log:
   `gui/installer/build/install.log`),
4. checks `undo --version`, `undo status` and `undo service status`.

It finds Inno Setup 6 or 7 in the usual folders, or uses `ISCC=/path/to/ISCC.exe`. Options:

| Option | Effect |
|---|---|
| `--pull` | Run `git pull --ff-only` first |
| `--no-build` | Install the newest `gui/installer/Undo-Setup-*.exe` that is already built |
| `--dev` | For a `uv tool install` development setup: reinstall with uv, restart the daemon, re-register autostart |

### Uninstalling

Use *Settings > Apps > Undo > Uninstall*. It:

* stops the daemon,
* removes the start-at-sign-in entry and the `PATH` entry,
* asks whether to delete your version history.

The default is **No**. If you keep the history, reinstalling picks it up again.

### Building the installer

`gui/installer/Undo.iss` is an Inno Setup 7 script that builds everything from the repository.
The build machine needs:

* [uv](https://docs.astral.sh/uv/),
* [Flutter](https://flutter.dev) on `PATH`,
* Visual Studio 2022 with the *Desktop development with C++* workload,
* Inno Setup 7.

Open `Undo.iss` in Inno Setup and choose **Build > Compile**, or from the repository root run:

```powershell
& "C:\Program Files\Inno Setup 7\ISCC.exe" gui\installer\Undo.iss
```

Compiling:

1. runs `uv sync --all-packages` (log: `gui/installer/build/uv.log`),
2. builds `undo.exe` and `undo-daemon.exe` with PyInstaller from `gui/installer/Undo.spec` into
   `gui/installer/build/dist/backend` (log: `pyinstaller.log`),
3. builds `Undo.exe` with `flutter build windows --release` (log: `flutter.log`),
4. writes `gui/installer/Undo-Setup-<version>.exe`.

The first compile takes several minutes. If a step fails, the error names its log. Options:

| Option | Effect |
|---|---|
| `/DBuildApp=0` | Skip steps 1–3 and package the existing builds (seconds instead of minutes) |
| `/DUv=C:\path\uv.exe` | The uv to build with (default: `~\.local\bin\uv.exe`, else `uv` on `PATH`) |
| `/DFlutter=C:\flutter\bin\flutter.bat` | The Flutter to build with (default: `flutter.bat` found on `PATH`) |

From Git Bash, prefix the command with `MSYS_NO_PATHCONV=1`, or Bash rewrites the `/D` options as
paths:

```sh
MSYS_NO_PATHCONV=1 "/c/Program Files/Inno Setup 7/ISCC.exe" /DBuildApp=0 gui/installer/Undo.iss
```

If you see *"EndUpdateResource failed, try excluding the Output folder from your antivirus"*,
compile again: an antivirus scan briefly locked the new setup file.

* The version comes from `gui/undo_desktop/pubspec.yaml`. To change it everywhere:

```sh
python scripts/release.py X.Y.Z
```

* The icon is `gui/assets/undo.ico`, the same design as `gui/assets/undo.png` and
  `gui/undo_desktop/assets/undo.png`.

### Machine-wide Windows service (optional, advanced)

* Start-at-sign-in suits a personal PC.
* To record changes for an account that is **not signed in**, run the daemon as a Windows
  service instead.
* This needs administrator rights and a Python install with pywin32:

```powershell
pip install "undo-core[windows-service]"
```

```powershell
undo --data-dir D:\UndoData init
python services\windows\install_service.py --data-dir D:\UndoData [--user .\alice --password ***]
python services\windows\uninstall_service.py
```

A service running as LocalSystem can only see files LocalSystem can read. Use `--user` to run it
as the account that owns the tracked folders. This has not been tested yet.

---

## Linux server

* On a server there is no desktop app. You use the daemon, the `undo` command and the terminal
  dashboard `undo tui`, all of which work over SSH.
* Run every step as the user who owns the files you want to track.
* Only the steps marked `sudo` need root.

### 1. Install uv

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
uv --version
```

### 2. Install Undo

```sh
git clone https://github.com/Madhur-Prakash/Undo.git ~/undo
cd ~/undo
uv tool install --python 3.12 ./cli --with ./backend
undo --version
```

uv downloads Python 3.12 if the server does not have it. `undo` is installed into
`~/.local/bin`.

### 3. Initialise

```sh
undo init                 # creates ~/.local/share/undo: database, settings, API token
undo doctor               # checks permissions, disk space and the inotify limit
```

### 4. Raise the inotify limit (sudo, once)

* Linux needs one inotify watch per watched directory.
* Ubuntu's default limit (often 8,192–65,536) is too low for real project trees.
* When a tree needs more, Undo falls back to polling, which is slower to notice changes, and
  `undo status` reports *"inotify watch limit reached"*.
* Raise the limit **before** tracking:

```sh
echo fs.inotify.max_user_watches=524288 | sudo tee /etc/sysctl.d/90-undo.conf
sudo sysctl --system
cat /proc/sys/fs/inotify/max_user_watches      # 524288
```

### 5. Start the daemon and keep it running

Use **one** of these two options.

**Option A: user service** (recommended; no root needed for the service itself):

```sh
undo service install                  # writes ~/.config/systemd/user/undo.service, enables and starts it
sudo loginctl enable-linger "$USER"   # start at boot and keep running after you log out
```

Without linger, systemd only starts user services when you log in, and stops them when your
last SSH session closes. Check both:

```sh
undo service status                         # systemd --user: enabled
loginctl show-user "$USER" -p Linger        # Linger=yes
systemctl --user status undo                # active (running)
```

**Option B: system service** (starts at boot and runs as the account you name):

```sh
sudo ~/undo/services/linux/install_service.sh --system --user "$USER"
sudo systemctl is-enabled undo              # enabled
sudo systemctl status undo                  # active (running)
```

* This installs `/etc/systemd/system/undo.service` (`WantedBy=multi-user.target`, `Nice=10`,
  idle IO class, `MemoryHigh=512M`).
* The script finds the Python that has Undo installed. Override with `--python PATH` or
  `--data-dir DIR`.
* With this option, `undo service status` (which checks the user service) reports `not-found`.
  That is expected.

### 6. Check exclusions, then track folders

First look at what is big in the folder you want to track, and exclude anything generated:

```sh
du -sh ~/myproject/* ~/myproject/.[!.]* 2>/dev/null | sort -h | tail -15
undo exclude list
undo exclude add "dist/"                    # example: build output
```

Then track the folder. With the daemon running, `track` returns at once and the daemon does the
first scan in the background:

```sh
undo track ~/myproject                      # or: cd ~/myproject && undo track .
undo roots
undo status                                 # "reconciling yes" while the first scan runs
```

Repeat `undo track` for each separate top-level folder. Do not track `~` itself.

* If the daemon is **not** running, `undo track` does the first scan in your terminal, and shows
  nothing until it finishes. That can take minutes on large trees.
* To return at once and let the daemon scan when it starts:

```sh
undo track ~/myproject --no-scan
```

### 7. Verify

```sh
undo status                 # last full reconcile set, files/versions > 0, no "Recent errors"
undo skipped | head -20     # files left out and why
echo test >> ~/myproject/undo-check.txt
sleep 3
undo history ~/myproject/undo-check.txt     # a CREATE entry
rm ~/myproject/undo-check.txt
```

### Updating

One command pulls the new code, reinstalls `undo` and restarts the daemon:

```sh
bash ~/undo/scripts/update_linux.sh --pull
```

[`scripts/update_linux.sh`](../scripts/update_linux.sh) works for any user and any setup:

* It finds the checkout it lives in, and finds uv in `PATH` or `~/.local/bin`.
* It detects how the daemon runs: the systemd **user** service, the **system** service (using
  `sudo` when you are not root), a plain `undo start`, or not running at all.
* It stops the daemon, reinstalls with `--reinstall`, runs `undo init` to apply database
  migrations and new default settings, restarts the daemon, and waits until it answers.
* At the end it prints `undo status`, and warns if linger is off.

Options:

| Option | Effect |
|---|---|
| `--pull` | Run `git pull --ff-only` first. Without it, the script installs the code that is checked out now. |
| `--editable` | Install in editable mode, so the installed `undo` follows the checkout |

The same steps by hand:

```sh
cd ~/undo
git pull
systemctl --user stop undo
uv tool install --force --reinstall --python 3.12 ./cli --with ./backend
undo --version
undo init
systemctl --user daemon-reload
systemctl --user start undo                 # system service: sudo systemctl restart undo
undo status
```

`--reinstall` matters: without it, uv may reuse its cached build of the previous code when the
version number has not changed.

### Stopping, restarting, logs

```sh
systemctl --user stop undo        # stop (systemd will not restart it)
systemctl --user start undo
systemctl --user restart undo
journalctl --user -u undo -f      # systemd's log; Undo's own log: undo logs
```

* Stop the daemon through **systemd**, not with `kill`.
* A killed daemon finishes its current step before it exits, and keeps the data directory locked
  until then. Commands then report *"The Undo data directory is in use by another process"*.
* If a stop hangs, force it. This is safe for your data: writes are crash-safe and the next
  start cleans up.

```sh
systemctl --user kill -s KILL undo
```

### Fixing a wrong folder

To stop tracking a folder and delete what was recorded for it:

```sh
undo untrack /path/you/tracked --purge -y   # without --purge the history is kept
undo storage gc                             # frees the disk space
```

If this reports that the data directory is in use, the daemon is busy (for example, scanning a
huge folder). Stop it, run the two commands, then start it again:

```sh
systemctl --user stop undo
undo untrack /path/you/tracked --purge -y
undo storage gc
systemctl --user start undo
```

### Removing Undo

```sh
undo service uninstall                       # system service: sudo ~/undo/services/linux/uninstall_service.sh --system
uv tool uninstall undo-cli
rm -rf ~/.local/share/undo                   # only if you also want to delete the history
```

The desktop app cannot connect to a server from another computer. On purpose, the daemon's API
listens on `127.0.0.1` only and needs the token in the data directory. Use `undo tui` over SSH.

---

## Linux desktop

Build the release archive on a Linux machine with uv and Flutter:

```sh
cd ~/undo
python3 scripts/build.py                     # writes dist/undo-linux.tar.gz
```

Install it:

```sh
tar xzf dist/undo-linux.tar.gz && cd undo-linux
./installer/install.sh                       # options: --no-service, --no-desktop
```

`install.sh`:

* installs the `undo` command (uv, else pipx, else pip),
* runs `undo init` and installs the systemd user service,
* copies the app to `~/.local/opt/undo`,
* adds a menu entry, `~/.local/share/applications/undo-desktop.desktop`.

Then raise the inotify limit (step 4 above) and track folders from the app or with `undo track`.

* A `.desktop` file is how Linux desktops (GNOME, KDE, Xfce and others) list an application in
  their menu, launcher and search. It is the Linux equivalent of a Start-menu shortcut.
* The template is `packaging/linux/undo-desktop.desktop`.
* `install.sh` fills in the app's path, the `undo` command's path and the icon (`undo.png`).

`./installer/uninstall.sh` removes everything except your history (`--remove-data` deletes that
too).

To build only the app:

```sh
sudo apt install clang cmake ninja-build pkg-config libgtk-3-dev zenity
cd gui/undo_desktop && flutter build linux --release
```

The app's folder picker uses `zenity` or `kdialog`, whichever is installed.

---

## From source (development)

```sh
git clone https://github.com/Madhur-Prakash/Undo.git && cd Undo
uv sync --all-packages          # .venv with backend, CLI and dev tools (Python 3.12 via .python-version)
uv run undo init
uv run undo --help
```

To put the `undo` command on your `PATH`, editable so it follows the checkout:

```sh
uv tool install --editable ./cli --with-editable ./backend    # = make install / ./make.sh install
```

Without uv: `python3.12 -m pip install --user ./backend ./cli`.

Then run `undo track PATH` and `undo start`, and `make gui` (or `./make.sh gui`) to run the app
with Flutter.

* **Windows:** `undo service install` registers `pythonw -m undo_core.daemon` in the per-user Run
  key, so no console window opens. The installed build registers `undo-daemon.exe` instead.
* **Linux:** it installs the systemd user unit.

Do not run a development daemon and an installed one against the same data directory. Only one
daemon can own it at a time. The `make` targets avoid this by using `.dev-home/`.

The full development workflow, including tests and trying changes on a real install with the
update scripts, is in [Development](DEVELOPMENT.md).

* The app uses no Flutter plugins. Its folder picker is native code in
  `gui/undo_desktop/windows/runner/flutter_window.cpp`, so Windows Developer Mode is not needed.
* To build the app alone:

```sh
cd gui/undo_desktop
flutter build windows --release      # writes build\windows\x64\runner\Release\Undo.exe
```

* `make build` (or `python scripts/build.py`) writes the Python wheels to `dist/python/`.
* On Linux it also writes the desktop bundle and `dist/undo-linux.tar.gz`.
* On Windows, ship `Undo-Setup-<version>.exe` from `gui/installer/Undo.iss` instead.

---

## Using Undo (any platform)

```sh
undo status                                   # daemon state, totals, recent errors
undo history FILE                             # every version of a file, newest first
undo cat 42                                   # content of version 42
undo diff 41 42                               # what changed between two versions
undo restore FILE --version 42 --dry-run      # preview
undo restore FILE --version 42 --overwrite    # replace the file (its current content is versioned first)
undo restore FILE --at 2h --to /tmp/          # as it was 2 hours ago, into /tmp
undo recover                                  # list deleted files
undo recover FILE                             # bring one back
undo tui                                      # full-screen dashboard
```

In `undo tui`:

* **3** opens *Files*: search, then press **Enter** on a file to see its history.
* On a version, press **v** to view it, **d** to diff it with the previous version, **i** for
  details, and **r** to restore it.
* Press **x** to delete the selected version, or **f** to delete the file's history (all of it,
  or only versions older than e.g. `30d`). Both preview and ask first.
* The restore dialog shows a **Preview** before anything is written.

Every command and option: [CLI.md](CLI.md). Getting files back in common situations:
[RECOVERY.md](RECOVERY.md). Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

Related: [CLI reference](CLI.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md)
