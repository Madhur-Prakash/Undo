<div align="center">

<img src="../gui/assets/undo.png" alt="Undo logo" width="96" height="96">

<h1>Undo documentation</h1>

<p>Everything about installing, using, developing and understanding Undo.</p>

</div>

---

## Start here

| I want to… | Read |
|---|---|
| Install Undo | [Installation](INSTALLATION.md) |
| Choose what to track | [What to track](INSTALLATION.md#choosing-what-to-track) |
| Get a file back | [Recovery](RECOVERY.md) |
| Resolve a conflict | [Comparing and resolving](RECOVERY.md#comparing-and-resolving-conflicts) |
| Look up a command or setting | [CLI reference](CLI.md) |
| Fix a problem | [Troubleshooting](TROUBLESHOOTING.md) |
| Check that Undo starts automatically | [Windows](INSTALLATION.md#starting-at-sign-in), [Linux](INSTALLATION.md#5-start-the-daemon-and-keep-it-running) |
| Move the data directory | [Storage › Moving](STORAGE.md#moving-the-data-directory) |
| Update Windows | [Windows › Updating](INSTALLATION.md#updating) |
| Update a Linux server | [Linux › Updating](INSTALLATION.md#updating-1) |
| Work on the code | [Development](DEVELOPMENT.md) |
| Report a bug or open a pull request | [Contributing](../CONTRIBUTING.md) |
| Report a security problem | [Security policy](../SECURITY.md) |
| See how it works inside | [Architecture](ARCHITECTURE.md), [Storage](STORAGE.md) |
| Script against the daemon | [Local API](API.md) |

## All documents

| Document | Contents |
|---|---|
| [Installation](INSTALLATION.md) | Windows, Linux server, Linux desktop, from source |
| [CLI reference](CLI.md) | Commands, settings, TUI keys |
| [Recovery](RECOVERY.md) | Restoring, resolving conflicts, crash recovery |
| [Troubleshooting](TROUBLESHOOTING.md) | Problems and fixes |
| [Development](DEVELOPMENT.md) | Setup, checks, testing on a real install, releasing |
| [Architecture](ARCHITECTURE.md) | Components, concurrency, packaging |
| [Storage](STORAGE.md) | Data directory, retention, garbage collection |
| [Local API](API.md) | Endpoints and examples ([OpenAPI schema](API_OPENAPI.json)) |

Elsewhere in the repository:

| Document | Contents |
|---|---|
| [README](../README.md) | What Undo is, quick start |
| [Desktop app](../gui/undo_desktop/README.md) | The app's screens and code |
| [Windows installer script](../gui/installer/Undo.iss) | How the installer is built |
| [Contributing](../CONTRIBUTING.md) | Bugs, ideas, pull requests |
| [Security policy](../SECURITY.md) | Reporting a vulnerability |
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
