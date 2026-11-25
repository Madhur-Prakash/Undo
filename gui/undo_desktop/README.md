# Undo desktop app

The desktop app for [Undo](../../README.md):

* browse the version history of your tracked folders,
* compare and restore earlier versions, and recover deleted files,
* manage snapshots, storage and settings.

Built with Flutter (Material 3), Riverpod, GoRouter and Dio. Runs on Windows and Linux.

The app is a window onto the Undo daemon. It never reads Undo's database or stored file
contents itself; every action goes through the daemon's local API (`127.0.0.1`, bearer token).

## Screens

| Screen | What you can do |
|---|---|
| Overview | Daemon status, tracked folders, storage, recent activity, unfinished merges |
| Files | Find a file and open its history |
| History | Recent changes in all tracked folders |
| Snapshots | Create, compare, restore and delete named snapshots of a folder |
| Storage | Usage, verify, retention, garbage collection |
| Settings | Every setting the CLI can change |

**On a tracked folder** (*Overview*): roll back to a point in time, delete history, pause, scan
now, stop tracking.

**On a file** (its history): restore a version, compare two versions, compare a version with the
file on disk, delete a version or the file's older history.

**Restoring:**

* Always shows a preview first.
* The preview can be filtered by outcome; conflicts and errors are listed first.
* Any item can be compared with the file on disk.
* Conflicts can be resolved in the merge editor: keep disk, use version, or both, or edit the
  result. Unfinished merges can be saved and resumed.
* A file is never overwritten without confirmation, and its current content is saved as a
  version first.

More: [Recovery › Comparing and resolving conflicts](../../docs/RECOVERY.md#comparing-and-resolving-conflicts).

## How it finds the daemon

1. It reads `daemon.json` and `api_token` from the data directory: `%LOCALAPPDATA%\Undo` on
   Windows, `~/.local/share/undo` on Linux, or `UNDO_HOME` if set.
2. If no daemon answers and `daemon.autostart` is on (the default), it starts one:
   * installed with the Windows installer: `backend\undo-daemon.exe --init` next to `Undo.exe`
     (no console window; `--init` creates the data directory on first run);
   * otherwise: `undo init` and `undo start`, using `UNDO_CLI` if set, else `undo` on `PATH`.

## Run and build

Run it in development from the repository root. The daemon comes from the `undo` command, so
initialise first:

```sh
make init
make gui            # or: ./make.sh gui   (flutter run -d windows / -d linux)
```

```sh
flutter pub get
flutter analyze
flutter test
flutter build windows --release   # build/windows/x64/runner/Release/Undo.exe
flutter build linux --release     # build/linux/x64/release/bundle/undo_desktop
```

* **Windows** needs Visual Studio 2022 with the "Desktop development with C++" workload. The app
  uses no Flutter plugins, so Developer Mode is not needed.
* **Linux** needs `clang cmake ninja-build pkg-config libgtk-3-dev`. The folder picker uses
  `zenity` or `kdialog`, whichever is installed.

To ship it on Windows, compile [`../installer/Undo.iss`](../installer/Undo.iss) with Inno Setup 7.
It bundles this app with the backend (`undo.exe`, `undo-daemon.exe`) into one setup program.

## Layout

| Path | Contents |
|---|---|
| `lib/main.dart` | Entry point |
| `lib/app/` | App widget, routes (GoRouter), the sidebar shell |
| `lib/core/api/` | Finding and starting the daemon; the API client |
| `lib/core/models/` | Data classes for API responses |
| `lib/core/providers/` | Riverpod providers: the daemon connection and backend-backed data |
| `lib/core/theme/`, `lib/core/util/` | Light and dark themes; size, time and path formatting |
| `lib/features/` | One folder per screen, plus the dialogs |
| `lib/shared/widgets.dart` | Shared widgets, confirmation dialogs, the folder picker |
| `windows/runner/` | Native Windows host (see below) |
| `linux/` | Native Linux host |
| `assets/undo.png` | Sidebar logo (the app icon, 256 px) |
| `test/` | Unit and widget tests |

Notes:

* `lib/core/api/discovery.dart` finds the data directory and the daemon, and starts the daemon.
  `undo_api.dart` is the typed API client (Dio).
* `windows/runner/flutter_window.cpp` implements the native folder picker on the `undo/native`
  channel, so the app needs no Flutter plugins.
* `windows/runner/main.cpp` sets the window title and size, and holds the `UndoDesktopRunning`
  mutex the installer checks for.
* `lib/features/restore/merge_editor.dart` is the merge editor; `lib/features/history/diff_view.dart`
  the side-by-side comparison.

---

More: [Documentation index](../../docs/README.md) · [Installation](../../docs/INSTALLATION.md) · [Development](../../docs/DEVELOPMENT.md) · [Architecture](../../docs/ARCHITECTURE.md) · [Troubleshooting › Desktop app](../../docs/TROUBLESHOOTING.md#desktop-app-and-api) · [Contributing](../../CONTRIBUTING.md) · [Security](../../SECURITY.md)
