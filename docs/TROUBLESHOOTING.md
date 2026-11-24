# Troubleshooting

> **Undo docs** · [Index](README.md) · [Installation](INSTALLATION.md) · [CLI](CLI.md) · [Recovery](RECOVERY.md) · **Troubleshooting** · [Development](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Storage](STORAGE.md) · [API](API.md)

Symptoms and fixes, grouped by area. Start with these three commands; they answer most questions:

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
* [Desktop app](#desktop-app)
* [Building](#building)
* [Logs and resetting](#logs-and-resetting)

---

## Installing and starting

| Symptom | Cause and fix |
|---|---|
| `undo: command not found` / not recognised (Windows) | The terminal was open before Setup added `undo` to `PATH`. Open a new terminal; in VS Code, restart VS Code. The full path always works: `%LOCALAPPDATA%\Programs\Undo\backend\undo.exe`. |
| `undo: command not found` (Linux) | `~/.local/bin` is not on `PATH`: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc` |
| `Undo is not initialised` | Run `undo init`. Check that `--data-dir` / `UNDO_HOME` point where you expect. |
| `undo service install` says *"schtasks failed: Access is denied"* | Builds before the fix used a scheduled task, which Windows only lets administrators create. Update Undo ([how](INSTALLATION.md#updating)): autostart now uses the per-user Run key and needs no admin. |
| `undo service status` says *not installed* after Setup | The option was unticked, or the old build above. Run `undo service install`. |
| Linux service stops when you log out, or does not start at boot | Linger is off: `sudo loginctl enable-linger $USER`. Check with `loginctl show-user $USER -p Linger`. |
| `systemctl is-enabled undo` says *"could not be found"* | That checks the system service. For the per-user service use `systemctl --user …` ([details](INSTALLATION.md#5-start-the-daemon-and-keep-it-running)). |
| *"The Undo data directory is in use by another process"* (exit 6) | The daemon (or another `undo` command) holds the directory. If you used `kill`, the daemon is still finishing its current step. Stop it properly with `systemctl --user stop undo` (Linux) or `undo stop`. If it hangs: `systemctl --user kill -s KILL undo`; this is safe for your data. |
| `Daemon exited during startup` | `undo start --foreground` shows the error on the console; also see `undo logs`. |
| Behaviour is still old after an update | The old build is still installed. Windows: check that `undo --version` and the install time are new; rerun `bash scripts/update_windows.sh`. Linux: reinstall with `--reinstall` (the [update script](INSTALLATION.md#updating-1) does) and restart the service. |

## Tracking

| Symptom | Cause and fix |
|---|---|
| `undo track .` tracked your **home folder**, or said *"Cannot track Undo's own data directory"* | Builds before the fix sent `.` as typed, and the daemon resolved it from its own working directory. Update, or pass a full path (`undo track ~/project`, `undo track $PWD`). Remove the wrong folder with `undo untrack PATH --purge -y`, then `undo storage gc`. |
| *"is inside Undo's program folder"* | You picked `…\Programs\Undo` in the folder picker. Choose the folder that holds your files. |
| *"… is inside tracked root …"* or *"contains tracked root …"* | Tracked folders cannot overlap. Track the parent once, or untrack the inner one first. |
| `undo track` shows *"Tracking … ..."* for a long time | With no daemon running, the first scan happens in your terminal. Large trees take minutes, and nothing is shown until the scan ends. Press Ctrl+C (safe: the folder stays tracked) and start the daemon; it scans in the background. Or use `--no-scan`. |
| First scan is huge | Check what is big (`du -sh FOLDER/* | sort -h`) and exclude generated folders (`undo exclude add "dist/"`) before scanning. Package folders (`node_modules/`, `venv/`, `target/`, …) are skipped by default. See [Choosing what to track](INSTALLATION.md#choosing-what-to-track). |

## Capturing changes

| Symptom | Cause and fix |
|---|---|
| Changes not captured | `undo status`: is the daemon running, and is the folder enabled? `undo skipped` lists excluded, too-large and unreadable files. `undo scan` reconciles immediately. |
| *"inotify watch limit reached … using polling"* (Linux) | Raise the limit, then restart: `echo fs.inotify.max_user_watches=524288 \| sudo tee /etc/sysctl.d/90-undo.conf && sudo sysctl --system && systemctl --user restart undo`. Polling still captures changes, only later. |
| `temporarily_unavailable` for some files | Another program holds an exclusive lock (common on Windows for databases, Outlook PST, VM disks). Undo retries `capture.max_retries` times; exclude such files or close the program. |
| `permission_denied` | The daemon's account cannot read the file. Run the daemon as the file owner. |
| `too_large` | Raise the limit: `undo settings set capture.max_file_size 20GB`. |
| High CPU during the first scan | Expected once: every file is hashed and compressed. On small machines run `undo settings set capture.max_concurrent 1` and `undo settings set compression.level 1`. Later scans only hash changed files. |

## Restoring

| Symptom | Cause and fix |
|---|---|
| Restore reports `conflict` (exit 5) | The destination exists with different content. Use `--overwrite` (the current content is versioned first) or `--to DIR`. |
| *"stored data failed verification"* | That stored version is damaged. Run `undo storage verify`; it repairs from live files when possible. Other versions remain restorable. See [Repairing damaged storage](RECOVERY.md#repairing-damaged-storage). |
| `undo storage verify` exits 8 | Damaged or missing objects remain (they are listed). Restore those files from your independent backup. |
| *"No history for PATH"* | The path was never inside a tracked folder, or it is excluded. `undo search NAME` also finds former names. |

## Storage and disk space

| Symptom | Cause and fix |
|---|---|
| *stored* is larger than *original* in `undo status` | Content of history you removed (for example `untrack --purge`) is only freed by garbage collection: `undo storage gc --dry-run`, then `undo storage gc`. |
| Disk usage keeps growing | Configure retention, then collect: `undo settings set retention.keep_all false`, `undo settings set retention.keep_days 30` (or `retention.max_storage_bytes 50GB`), then `undo storage gc --retention`. Exclude build outputs and caches. |
| *"job checkpoint failed … database table is locked"* in the app | Fixed in later builds. It never affected data, because SQLite checkpoints on its own. Update to make the message stop. |
| Database errors after a crash | Restart the daemon: startup recovery runs automatically. `undo doctor` runs `quick_check`. |

## Desktop app

| Symptom | Cause and fix |
|---|---|
| App shows *"Not connected"* | Click *Start daemon*. The installed app starts its bundled `backend\undo-daemon.exe`; a development build uses `undo` from `PATH` or `UNDO_CLI`. Check that the app and the CLI use the same `UNDO_HOME`. |
| Browser shows `{"detail":"Not Found"}` at `127.0.0.1:47821` | That is the daemon; it has no page at `/`. The API lives under `/api/v1/` and the interactive docs at `/api/v1/docs` ([Local API](API.md)). |
| API port 47821 busy | The daemon picks a free port automatically and publishes it in `daemon.json`; `undo status` shows it. Set `api.port` for a different fixed port. |

## Building

| Symptom | Cause and fix |
|---|---|
| Installer compile fails | Read the log the error names in `gui/installer/build/` (`uv.log`, `pyinstaller.log`, `flutter.log`). |
| *"EndUpdateResource failed, try excluding the Output folder from your antivirus"* | An antivirus scan briefly locked the new setup file. Compile again; `update_windows.sh` retries by itself. |
| *"The Flutter directory is not a clone"* while compiling | `flutter.bat` was called by a bare name. `Undo.iss` resolves its full path from `PATH`; otherwise pass `/DFlutter=C:\path\to\flutter.bat`. |
| `flutter build windows` fails about symlinks | Only if a Flutter plugin is added (the app uses none). Enable Developer Mode: `start ms-settings:developers`. |

## Logs and resetting

`logs/undo.log` in the data directory holds JSON lines (`ts`, `level`, `logger`, `msg`, plus
context such as `path`, `root`, `status`). `undo logs` pretty-prints it, `undo logs -f` follows
it, and `undo logs --raw` prints it unchanged for `jq`. `undo settings set daemon.log_level DEBUG`
makes it more detailed. On Linux, systemd's own log is `journalctl --user -u undo`.

To start over completely, stop the daemon and delete the data directory (see
[Storage › Data directory layout](STORAGE.md#data-directory-layout)). Your tracked files are not
affected, but all history is gone.

---

Related: [Installation](INSTALLATION.md) · [CLI reference](CLI.md) · [Recovery](RECOVERY.md)
