# Troubleshooting

Start with `undo doctor` and `undo status`, then `undo logs -n 200`.

| Symptom | Cause / fix |
|---|---|
| `Undo is not initialised` | Run `undo init` (check `--data-dir` / `UNDO_HOME` point where you expect). |
| `The Undo data directory is in use by another process` (exit 6) | The daemon (or another `undo` command) holds the lock. Commands are routed to a running daemon automatically; if it is still starting, wait. If no daemon answers, see `undo.owner` for the pid. |
| `Daemon exited during startup` | `undo start --foreground` shows the error on the console; also `undo logs`. |
| Changes not captured | `undo status`: is the daemon running, is the root `enabled`, which monitor mode? `undo skipped` lists excluded / too large / unreadable files. `undo scan` reconciles immediately. |
| Watch mode `polling` on Linux | inotify limit reached (`undo doctor` shows `max_user_watches`). Raise it (INSTALLATION.md) and `undo restart`. |
| `temporarily_unavailable` for some files | Another program holds an exclusive lock (common on Windows for databases, Outlook PST, VM disks). Undo retries `capture.max_retries` times; exclude such files or close the program. |
| `permission_denied` | The daemon's account cannot read the file. Run the daemon as the file owner. |
| `too_large` | Raise `capture.max_file_size` (e.g. `undo settings set capture.max_file_size 20GB`). |
| Restore reports `conflict` (exit 5) | The destination exists with different content. Use `--overwrite` (current content is versioned first) or `--to DIR`. |
| Restore reports `error: stored data failed verification` | The stored object is damaged. Run `undo storage verify`; it repairs blobs whose content still exists in a tracked file. Other versions remain restorable. |
| `undo storage verify` exits 8 | Damaged/missing objects remain (listed). Restore from your independent backup if needed. |
| GUI shows "Not connected" | Click *Start daemon*. If `undo` is not on `PATH`, set `UNDO_CLI` to the full path of `undo` (`undo.exe`). Check that the GUI and CLI use the same `UNDO_HOME`. |
| `flutter build windows` fails about symlinks | Only happens if a Flutter plugin is added (the app uses none): enable Developer Mode (`start ms-settings:developers`). |
| `undo service install` says "schtasks failed: Access is denied" | Fixed: builds before this change used a scheduled task, which Windows only lets administrators create. Update Undo; autostart now uses the per-user Run key and needs no admin. |
| Installer compile fails | Read the log it names in `gui/installer/build` (`uv.log`, `pyinstaller.log`, `flutter.log`). |
| API port 47821 busy | The daemon picks a random free port automatically and publishes it in `daemon.json`; set `api.port` to choose another fixed one. |
| High CPU during initial scan | Expected once: every file is hashed and compressed. Lower `capture.max_concurrent` to 1 and `compression.level` to 1 on small machines. Later scans only hash changed files. |
| Disk usage growing | Configure retention (`retention.keep_all false`, `retention.keep_days 30`, or `retention.max_storage_bytes 50GB`), then `undo storage gc --retention`. Exclude build outputs and caches. |
| Database errors after a crash | Restart the daemon: startup recovery runs automatically. `undo doctor` runs `quick_check`. |

## Log format

`logs/undo.log` holds JSON lines (`ts`, `level`, `logger`, `msg` plus context fields such as
`path`, `root`, `status`). `undo logs --raw` prints them unchanged for `jq`; `daemon.log_level`
controls verbosity.

## Resetting

Stop the daemon and delete the data directory to start over; your tracked files are not affected.
