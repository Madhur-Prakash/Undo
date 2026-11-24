<div align="center">

<img src="../gui/assets/undo.png" alt="Undo logo" width="96" height="96">

<h1>Undo documentation</h1>

<p>Everything about installing, using, developing and understanding Undo.</p>

</div>

---

## Start here

| I want to… | Read |
|---|---|
| Install Undo on Windows, a Linux server or a Linux desktop | [Installation](INSTALLATION.md) |
| Choose which folders to track, and what is skipped | [Installation › Choosing what to track](INSTALLATION.md#choosing-what-to-track) |
| Get a file back, see old versions, recover deleted files | [Recovery](RECOVERY.md) and [CLI › Restoration](CLI.md#restoration) |
| Look up a command or setting | [CLI reference](CLI.md) |
| Fix something that is not working | [Troubleshooting](TROUBLESHOOTING.md) |
| Update an install to the latest code | [Installation › Windows › Updating](INSTALLATION.md#updating) or [Linux server › Updating](INSTALLATION.md#updating-1) |
| Work on Undo's code, run tests, try changes on a real install | [Development](DEVELOPMENT.md) |
| Understand how it works inside | [Architecture](ARCHITECTURE.md) and [Storage](STORAGE.md) |
| Call the daemon from my own scripts | [Local API](API.md) |

## All documents

| Document | Contents |
|---|---|
| [Installation](INSTALLATION.md) | What to track · Windows installer, autostart, updating, building the installer · Linux server step by step (systemd, linger, inotify) · Linux desktop · from source |
| [CLI reference](CLI.md) | Every `undo` command and option, exit codes, every setting, the terminal dashboard's keys |
| [Recovery](RECOVERY.md) | What can be restored and how, restore guarantees, crash recovery, repairing storage, ransomware |
| [Troubleshooting](TROUBLESHOOTING.md) | Symptoms and fixes, logs, resetting |
| [Development](DEVELOPMENT.md) | Repository layout, dev setup, running each part, tests and checks, testing your changes on a real install with the update scripts, releasing |
| [Architecture](ARCHITECTURE.md) | Components, how clients talk to the daemon, concurrency, event flow, reconciliation, scheduled jobs, packaging |
| [Storage](STORAGE.md) | Data directory layout, hashing, capture and publishing, compression, deduplication, database tables, retention, garbage collection, verification |
| [Local API](API.md) | Endpoints, authentication, errors, examples ([OpenAPI schema](API_OPENAPI.json)) |

Elsewhere in the repository:

| Document | Contents |
|---|---|
| [README](../README.md) | What Undo is, features, quick start |
| [Desktop app](../gui/undo_desktop/README.md) | The Flutter app: screens, how it finds the daemon, building it, code layout |
| [Windows installer script](../gui/installer/Undo.iss) | Inno Setup script; the comments at the top explain the build |
| [Changelog](../CHANGELOG.md) | Changes in each version |
| [License](../LICENSE) | MIT |

## The parts of Undo in one minute

* **The daemon** (`undo-daemon`) runs in the background. It watches your tracked folders, saves
  a version of every file when it changes, and serves a local API on `127.0.0.1`.
* **Three ways to use it**, all talking to that daemon:
  * the **desktop app**,
  * the **`undo` command**,
  * the **terminal dashboard** (`undo tui`).
* **The data directory** (`%LOCALAPPDATA%\Undo` or `~/.local/share/undo`) holds everything Undo
  stores: the database, the compressed file contents, the settings and the API token. Your
  tracked files are never moved or changed, except when you restore.
