# Troubleshooting

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · [Recovery](RECOVERY.md) · **Troubleshooting** · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md)

Each problem below has its cause and a fix you can copy and run.

## First, look

These three commands answer most questions:

```sh
undo status        # is the daemon running, what is tracked, recent errors
undo doctor        # checks permissions, database, disk space, token, inotify limit
undo logs -n 200   # the daemon's log, pretty-printed
```

**On this page:**

* [Installing and starting](#installing-and-starting)
* [Tracking](#tracking)
* [Capturing changes](#capturing-changes)
* [Restoring](#restoring)
* [Storage and disk space](#storage-and-disk-space)
* [Desktop app and API](#desktop-app-and-api)
* [Building the installer](#building-the-installer)
* [Logs and resetting](#logs-and-resetting)

---

## Installing and starting

### `undo` is not recognised (Windows)

* **Cause:** the terminal was opened before Setup added `undo` to `PATH`.
* **Fix:** open a new terminal. In VS Code, close and reopen VS Code. Then:

```powershell
undo --version
```

* **Or** use the full path, which always works:

```powershell
& "$env:LOCALAPPDATA\Programs\Undo\backend\undo.exe" status
```

### `undo: command not found` (Linux)

* **Cause:** `~/.local/bin` is not on `PATH`.
* **Fix:**

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
undo --version
```

### `Undo is not initialised`

* **Cause:** no data directory yet, or `--data-dir` / `UNDO_HOME` points somewhere else.
* **Fix:**

```sh
undo init
undo config        # shows which data directory is used
```

### `undo service install` says *"schtasks failed: Access is denied"* (Windows)

* **Cause:** older builds used a scheduled task, which Windows only lets administrators create.
* **Fix:** update Undo. Autostart now uses the per-user Run key and needs no admin
  ([how to update](INSTALLATION.md#updating)). Then:

```powershell
undo service install
undo service status      # autostart at sign-in: installed
```

### `undo service status` says *not installed*

* **Cause:** the *Start at sign-in* option was unticked in Setup, or an older build.
* **Fix:**

```sh
undo service install
undo service status
```

### Linux service stops when you log out, or does not start at boot

* **Cause:** linger is off, so systemd only runs user services while you are logged in.
* **Check:**

```sh
loginctl show-user "$USER" -p Linger      # Linger=no means off
```

* **Fix:**

```sh
sudo loginctl enable-linger "$USER"
```

### `systemctl is-enabled undo` says *"could not be found"*

* **Cause:** that command checks the **system** service. `undo service install` installs a
  **user** service.
* **Fix:** add `--user`:

```sh
systemctl --user is-enabled undo
systemctl --user status undo
```

### *"The Undo data directory is in use by another process"* (exit 6)

* **Cause:** the daemon, or another `undo` command, holds the data directory. After `kill`, the
  daemon is still finishing its current step.
* **Fix (Linux):** stop it through systemd and wait until it is inactive:

```sh
systemctl --user stop undo
systemctl --user is-active undo           # repeat until: inactive
```

* **If it hangs**, force it. This is safe for your data: writes are crash-safe.

```sh
systemctl --user kill -s KILL undo
```

* **Fix (Windows, or no systemd):**

```sh
undo stop
```

### *"Daemon exited during startup"*

* **Cause:** the daemon hit an error before it could answer.
* **Fix:** run it in the foreground to see the error:

```sh
undo start --foreground
undo logs -n 50
```

### Behaviour is still the old one after an update

* **Cause:** the old build is still installed.
* **Fix (Windows, Git Bash, in the repository):**

```sh
bash scripts/update_windows.sh
```

* **Fix (Linux):**

```sh
bash ~/undo/scripts/update_linux.sh
```

* **Check:**

```sh
undo --version
undo status
```

---

## Tracking

### `undo track .` tracked your home folder, or said *"Cannot track Undo's own data directory"*

* **Cause:** older builds sent `.` as typed, and the daemon resolved it from its own working
  directory.
* **Fix:** update Undo, or pass a full path:

```sh
undo track ~/project                 # Linux
undo track "$PWD"                    # PowerShell or bash: the current folder
```

* **Remove the wrong folder** and free its space:

```sh
undo roots                           # find the wrong path
undo untrack /home/you --purge -y    # replace with that path
undo storage gc
```

### *"is inside Undo's program folder"*

* **Cause:** you picked `…\Programs\Undo` in the folder picker.
* **Fix:** choose the folder that holds your files, for example:

```powershell
undo track "$env:USERPROFILE\Documents"
```

### *"… is inside tracked root …"* or *"… contains tracked root …"*

* **Cause:** tracked folders cannot overlap. A tracked folder already covers everything below it.
* **Fix:** keep the parent only:

```sh
undo roots
undo untrack /path/to/inner/folder
```

### `undo track` shows *"Tracking …"* for a long time

* **Cause:** with no daemon running, the first scan happens in your terminal and prints nothing
  until it ends. Large trees take minutes.
* **Fix:** press **Ctrl+C**. That is safe: the folder stays tracked. Then let the daemon scan in
  the background:

```sh
undo roots                           # the folder is listed
systemctl --user start undo          # Linux; on Windows: undo start
undo status                          # "reconciling yes", counts going up
```

* **Next time**, skip the scan in the terminal:

```sh
undo track ~/project --no-scan
```

### The first scan is huge

* **Cause:** generated or downloaded files in the folder. Package folders (`node_modules/`,
  `venv/`, `target/`, …) are already skipped; build outputs and data are not.
* **Fix:** find what is big, exclude it, then scan:

```sh
du -sh ~/project/* ~/project/.[!.]* 2>/dev/null | sort -h | tail -15
undo exclude add "dist/"
undo exclude add "*.csv"
undo scan ~/project
```

* More: [Choosing what to track](INSTALLATION.md#choosing-what-to-track).

---

## Capturing changes

### Changes are not captured

* **Check** that the daemon runs and the folder is enabled, and see what was skipped and why:

```sh
undo status
undo roots
undo skipped | head -20
```

* **Fix:** reconcile now:

```sh
undo scan
```

### *"inotify watch limit reached … using polling"* (Linux)

* **Cause:** the folder tree needs more inotify watches than the system allows. Undo then polls,
  which still captures changes, only later.
* **Fix:** raise the limit once, then restart the daemon:

```sh
echo fs.inotify.max_user_watches=524288 | sudo tee /etc/sysctl.d/90-undo.conf
sudo sysctl --system
systemctl --user restart undo
undo status                          # watch shows "inotify", no recent error
```

### Files skipped as `temporarily_unavailable`

* **Cause:** another program holds an exclusive lock. This is common on Windows for databases,
  Outlook PST files and VM disks. Undo retries `capture.max_retries` times.
* **Fix:** close that program, or exclude those files:

```sh
undo exclude add "*.pst"
```

### Files skipped as `permission_denied`

* **Cause:** the daemon's account cannot read the file.
* **Fix:** run the daemon as the user who owns the files: the per-user service, or
  `install_service.sh --system --user OWNER` on Linux.

### Files skipped as `too_large`

* **Cause:** the file is larger than `capture.max_file_size` (default 4 GiB).
* **Fix:**

```sh
undo settings set capture.max_file_size 20GB
undo scan
```

### High CPU during the first scan

* **Cause:** expected once: every file is hashed and compressed. Later scans only look at
  changed files.
* **Fix (small machines):**

```sh
undo settings set capture.max_concurrent 1
undo settings set compression.level 1
```

---

## Restoring

### Restore reports `conflict` (exit 5)

* **Cause:** the destination exists with different content, and Undo never overwrites silently.
* **Fix:** replace it (its current content is saved as a version first), or restore elsewhere:

```sh
undo restore FILE --version 42 --overwrite
undo restore FILE --version 42 --to /tmp/
```

### *"stored data failed verification"*

* **Cause:** that stored version is damaged. Other versions are unaffected.
* **Fix:** verify and repair. Repair works when a tracked file still has the same content.

```sh
undo storage verify
```

* More: [Repairing damaged storage](RECOVERY.md#repairing-damaged-storage).

### `undo storage verify` exits 8

* **Cause:** damaged or missing objects remain after repair (they are listed).
* **Fix:** restore those files from your independent backup.

### *"No history for PATH"*

* **Cause:** the path was never inside a tracked folder, or it is excluded.
* **Fix:** search by any current or former name:

```sh
undo search report
undo roots
undo exclude list
```

---

## Storage and disk space

### *stored* is larger than *original* in `undo status`

* **Cause:** removed history (`untrack --purge`, retention) only frees space after garbage
  collection.
* **Fix:**

```sh
undo storage gc --dry-run            # what would be freed
undo storage gc
undo status
```

### Disk usage keeps growing

* **Cause:** by default every version is kept (`retention.keep_all`).
* **Fix:** set a retention policy, then collect:

```sh
undo settings set retention.keep_all false
undo settings set retention.keep_days 30
undo storage gc --retention
```

* **Or** cap the total size:

```sh
undo settings set retention.max_storage_bytes 50GB
undo storage gc --retention
```

### *"job checkpoint failed … database table is locked"*

* **Cause:** a bug in older builds. It never affected data, because SQLite also checkpoints on
  its own.
* **Fix:** update Undo ([Windows](INSTALLATION.md#updating), [Linux](INSTALLATION.md#updating-1)).

### Database errors after a crash

* **Cause:** the daemon or the machine stopped mid-write.
* **Fix:** restart the daemon. Startup recovery runs automatically.

```sh
undo restart
undo doctor                          # includes SQLite quick_check
```

---

## Desktop app and API

### The app shows *"Not connected"*

* **Fix:** click **Start daemon** in the app, or:

```sh
undo start
undo status
```

* **Still not connected:**
  * The installed app starts `backend\undo-daemon.exe` itself.
  * A development build needs `undo` on `PATH`, or `UNDO_CLI` set to its full path.
  * The app and the CLI must use the same data directory (`UNDO_HOME`).

### `127.0.0.1:47821` shows `{"detail":"Not Found"}`

* **Cause:** that is the daemon. It has no page at `/`.
* **Fix:** open the interactive API docs instead:

```text
http://127.0.0.1:47821/api/v1/docs
```

* Then click **Authorize** and paste the token from the data directory
  ([how](API.md)).

### Port 47821 is busy

* **Cause:** another program uses the default port. The daemon then picks a free one.
* **Check** which port it uses:

```sh
undo status                          # the "api" line
```

* **Or** choose a fixed port:

```sh
undo settings set api.port 48000
undo restart
```

---

## Building the installer

### The compile fails

* **Fix:** read the log the error names:

```sh
tail -40 gui/installer/build/uv.log
tail -40 gui/installer/build/pyinstaller.log
tail -40 gui/installer/build/flutter.log
```

### *"EndUpdateResource failed, try excluding the Output folder from your antivirus"*

* **Cause:** an antivirus scan briefly locked the new setup file.
* **Fix:** compile again. `scripts/update_windows.sh` retries by itself.

```sh
MSYS_NO_PATHCONV=1 "/c/Program Files/Inno Setup 7/ISCC.exe" /DBuildApp=0 gui/installer/Undo.iss
```

### *"Flutter could not build the desktop app"*, and `flutter.log` shows `MSB3073` / *"cannot find …native_assets/windows"*

* **Cause:** `gui/undo_desktop/build/` was deleted by hand while Flutter's cache in
  `.dart_tool/` was kept. `Undo.iss` now recreates the missing folder.
* **Fix (if it still happens):**

```sh
cd gui/undo_desktop
flutter clean
flutter pub get
cd ../..
bash scripts/update_windows.sh
```

* **Next time**, clean with `make clean` (it runs `flutter clean`), not by deleting `build/`.

### *"The Flutter directory is not a clone"* while compiling

* **Cause:** `flutter.bat` was run by a bare name, which breaks its path detection.
* **Fix:** `Undo.iss` finds the full path on `PATH`. If Flutter is not on `PATH`, pass it:

```sh
MSYS_NO_PATHCONV=1 "/c/Program Files/Inno Setup 7/ISCC.exe" /DFlutter=C:\\flutter\\bin\\flutter.bat gui/installer/Undo.iss
```

### A button in the app has a tooltip but no icon

* **Cause:** a release build keeps only the icons it finds, and an incremental rebuild reused an
  older, smaller icon font, so newly added icons were missing from it.
* **Fix:** the installer and `scripts/build.py` now build with `--no-tree-shake-icons`, which
  ships the whole icon font. Rebuild and reinstall:

```sh
bash scripts/update_windows.sh
```

### `flutter build windows` fails about symlinks

* **Cause:** only happens if a Flutter plugin is added. The app uses none.
* **Fix:** enable Developer Mode:

```powershell
start ms-settings:developers
```

---

## Logs and resetting

### Reading the logs

```sh
undo logs -n 100                     # last 100 lines, pretty-printed
undo logs -f                         # follow
undo logs --raw | jq .               # raw JSON lines
journalctl --user -u undo -n 50      # Linux: systemd's own log
```

* The log file is `logs/undo.log` in the data directory: JSON lines with `ts`, `level`,
  `logger` and `msg`.
* For more detail:

```sh
undo settings set daemon.log_level DEBUG
undo restart
```

### Starting over

* **This deletes all history.** Your tracked files are not touched.

```sh
# Linux
systemctl --user stop undo
rm -rf ~/.local/share/undo
undo init
```

```powershell
# Windows (PowerShell)
undo stop
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Undo"
undo init
```

---

Related: [Installation](INSTALLATION.md) · [CLI reference](CLI.md) · [Recovery](RECOVERY.md)
