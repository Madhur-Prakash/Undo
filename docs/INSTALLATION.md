# Installation

Pick the section for your machine:

| Machine | How | You need |
|---|---|---|
| Windows 10/11 | [`Undo-Setup-<version>.exe`](#windows-installer) | Nothing: Python and the daemon are bundled |
| Linux server (no desktop) | [`undo` command + systemd](#linux-server) | uv (it fetches Python 3.12) |
| Linux desktop | [Release archive](#linux-desktop) with `installer/install.sh` | uv, and a desktop for the app |
| Development, any OS | [From source](#from-source-development) | uv; Flutter for the app |

All of them keep your history in the same place:

| OS | Data directory |
|---|---|
| Windows | `%LOCALAPPDATA%\Undo` |
| Linux | `$XDG_DATA_HOME/undo`, or `~/.local/share/undo` |

Set `UNDO_HOME` (or pass `--data-dir`) to use another directory. The desktop app honours
`UNDO_HOME` too. Uninstalling Undo never deletes this directory unless you ask it to.

> **Tested so far:** everything on Windows 11. The Linux steps below are written for Linux and
> its tests are written to pass there, but they have not yet been run on a Linux machine.

---

## Windows installer

### Installing

Run `Undo-Setup-<version>.exe`. It installs for your account only, with no administrator rights,
into `%LOCALAPPDATA%\Programs\Undo`. Setup offers three options:

| Option | Default | What it does |
|---|---|---|
| Start the Undo daemon when I sign in | on | Registers the logon task *Undo Daemon* (the same as `undo service install`), so changes are recorded even when the app is closed |
| Add the undo command to PATH | on | Adds `…\Undo\backend` to your user `PATH`, so `undo` and `undo tui` work in any new terminal |
| Create a desktop shortcut | off | A desktop icon for the app |

When Setup finishes, open **Undo** from the Start menu, choose *Track folder* and pick a folder.
Undo records its current state and then every change.

The installed files:

```
%LOCALAPPDATA%\Programs\Undo\
  Undo.exe                 the desktop app
  data\, flutter_windows.dll
  backend\
    undo.exe               the command line and `undo tui`
    undo-daemon.exe        the daemon (no console window)
    _internal\             Python runtime and libraries
```

The app starts the daemon by itself when it is not running. On first run it also creates the data
directory (`undo-daemon.exe --init`). The Start menu also has **Undo (terminal dashboard)**, which
opens `undo tui`.

### Upgrading and uninstalling

* **Upgrade:** run the newer `Undo-Setup-<version>.exe`. It asks you to close the app if it is
  open and stops the daemon cleanly (pending captures finish first). Then it replaces the programs.
  Your history and settings are untouched.
* **Uninstall:** use *Settings > Apps > Undo > Uninstall*. It stops the daemon, removes the logon
  task and the `PATH` entry, then asks whether to delete your version history. The default is
  **No**: if you keep it, reinstalling picks it up again.

### Building the installer

`gui/installer/Undo.iss` is an Inno Setup 7 script that builds everything from the repository.
On the build machine you need:

* [uv](https://docs.astral.sh/uv/),
* [Flutter](https://flutter.dev) on `PATH`,
* Visual Studio 2022 with the *Desktop development with C++* workload,
* Inno Setup 7.

Open `Undo.iss` in Inno Setup and choose **Build > Compile**, or from a terminal run
`ISCC gui\installer\Undo.iss`. Compiling:

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
paths. Example: `MSYS_NO_PATHCONV=1 ISCC /DBuildApp=0 gui/installer/Undo.iss`.

The version comes from `gui/undo_desktop/pubspec.yaml`. `python scripts/release.py X.Y.Z` updates
it together with the Python packages. The icon is `gui/assets/undo.ico`, drawn by
`scripts/make_icon.py`.

### Machine-wide Windows service (optional, advanced)

The installer's logon task runs the daemon while you are signed in, which suits a personal PC.
To record changes for an account that is not signed in, run the daemon as a Windows service
instead. This needs administrator rights and a Python install with pywin32
(`pip install "undo-core[windows-service]"`):

```powershell
undo --data-dir D:\UndoData init
python services\windows\install_service.py --data-dir D:\UndoData [--user .\alice --password ***]
python services\windows\uninstall_service.py
```

A service running as LocalSystem can only see files LocalSystem can read. Use `--user` to run it
as the account that owns the tracked folders. This path has not been tested yet.

---

## Linux server

On a server there is no desktop. You use the daemon, the `undo` command and the terminal
dashboard `undo tui`, all of which work over SSH. Do every step as the user who owns the files
you want to track, unless the step says `sudo`.

### 1. Install uv and Undo

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"          # also add this line to ~/.bashrc
```

Then use **either** a copy of the repository **or** a release archive.

**From the repository:** copy it to the server (`git clone`, `rsync` or `scp`), then from its
folder run:

```sh
uv tool install --python 3.12 ./cli --with ./backend
```

**From a release archive:** run `python scripts/build.py` on any Linux machine with uv. It writes
`dist/undo-linux.tar.gz`. Copy that to the server, then:

```sh
tar xzf undo-linux.tar.gz && cd undo-linux
./installer/install.sh --no-desktop          # does steps 1-3 below for you
```

`install.sh` installs the `undo` command and runs `undo init`. If a systemd user session is
available, it also installs the user service.

### 2. Set up and choose folders

```sh
undo init                     # data directory, database, API token
undo track /srv/data          # repeat for each folder; records its current state
undo doctor                   # checks permissions, disk space, the inotify limit
```

### 3. Keep the daemon running

Choose **one** of these.

**User service** (no root needed for the service itself):

```sh
undo service install                  # ~/.config/systemd/user/undo.service, enabled and started
sudo loginctl enable-linger "$USER"   # required on servers: keep it running after you log out
```

Without `enable-linger`, systemd stops user services when your last SSH session closes.

**System service** (starts at boot, runs as the account you name):

```sh
sudo services/linux/install_service.sh --system --user alice
sudo -u alice undo track /srv/data
```

This installs `/etc/systemd/system/undo.service` running as `alice`
(`WantedBy=multi-user.target`, `Nice=10`, idle IO class, `MemoryHigh=512M`). The script finds the
Python that has Undo installed; pass `--python PATH` or `--data-dir DIR` to override.

Check that it runs:

```sh
undo status
systemctl --user status undo          # or: sudo systemctl status undo   (system service)
journalctl --user -u undo -f          # or: undo logs
```

### 4. Raise the inotify limit for large trees

Linux needs one inotify watch per watched directory, and the default limit is often 8,192 or
65,536. When a tree needs more, Undo falls back to polling for that folder. `undo status` and
`undo doctor` say so. Raise the limit once:

```sh
echo fs.inotify.max_user_watches=524288 | sudo tee /etc/sysctl.d/90-undo.conf && sudo sysctl --system
```

### 5. Use it

```sh
undo status
undo tui                                       # full-screen dashboard over SSH
undo history /srv/data/config.yml
undo restore /srv/data/config.yml --version 12 --overwrite
undo restore /srv/data/config.yml --at 2h --to /tmp/    # as it was two hours ago, into /tmp
undo recover                                   # list deleted files
undo recover /srv/data/deleted.txt
```

Every command: [CLI.md](CLI.md).

The desktop app cannot connect to a server from another computer. On purpose, the daemon's API
listens on `127.0.0.1` only and needs the token in the data directory. Use `undo tui` over SSH.

### Updating and removing

* **Update:** get the new code or archive, run the same `uv tool install` command again with
  `--force` (or rerun `install.sh`), then restart the service: `systemctl --user restart undo`
  or `sudo systemctl restart undo`.
* **Remove:** run `undo service uninstall`, or `sudo services/linux/uninstall_service.sh --system`
  for a system service. Then run `uv tool uninstall undo-cli`. With a release archive,
  `./installer/uninstall.sh` does all of it. History stays in `~/.local/share/undo` unless you add
  `--remove-data` or delete it yourself.

---

## Linux desktop

Build the release archive on a Linux machine with uv and Flutter: run `python scripts/build.py`
to get `dist/undo-linux.tar.gz`. Then:

```sh
tar xzf undo-linux.tar.gz && cd undo-linux
./installer/install.sh                 # options: --no-service, --no-desktop
```

This:

* installs the `undo` command (uv, else pipx, else pip),
* runs `undo init` and installs the systemd user service,
* copies the app to `~/.local/opt/undo`,
* puts a menu entry in `~/.local/share/applications/undo-desktop.desktop`.

A `.desktop` file is how Linux desktops (GNOME, KDE, Xfce and others) list an application in their
menu, launcher and search. It is the Linux equivalent of a Start-menu shortcut. The template is
`packaging/linux/undo-desktop.desktop`; `install.sh` fills in the app's path, the `undo` command's
path and the icon (`undo.png`).

`./installer/uninstall.sh` removes everything except your history (`--remove-data` deletes that
too).

To build only the app: install `clang cmake ninja-build pkg-config libgtk-3-dev`, then run
`cd gui/undo_desktop && flutter build linux --release`. The app's folder picker uses `zenity` or
`kdialog`, whichever is installed.

---

## From source (development)

```sh
uv sync --all-packages          # .venv with backend, CLI and dev tools (Python 3.12 via .python-version)
uv run undo init
uv run undo --help
```

To put the `undo` command on your `PATH`, editable so it follows the checkout:

```sh
uv tool install --editable ./cli --with-editable ./backend    # = make install / ./make.sh install
```

Without uv: `python3.12 -m pip install --user ./backend ./cli`.

Then `undo track PATH`, `undo start`, and `make gui` (or `./make.sh gui`) to run the app with
Flutter. On Windows, `undo service install` registers the logon task with `pythonw`, so no
console window opens. On Linux it installs the systemd user unit.

The app uses no Flutter plugins. Its folder picker is native code in
`gui/undo_desktop/windows/runner/flutter_window.cpp`, so Windows Developer Mode is not needed.
`cd gui/undo_desktop && flutter build windows --release` writes
`build\windows\x64\runner\Release\Undo.exe`.

`make build` / `python scripts/build.py` writes the Python wheels to `dist/python/`. On Linux it
also writes the desktop bundle and `dist/undo-linux.tar.gz`. On Windows, ship
`Undo-Setup-<version>.exe` from `gui/installer/Undo.iss` instead.
