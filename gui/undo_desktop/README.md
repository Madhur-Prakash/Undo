# Undo desktop app

The desktop app for [Undo](../../README.md): browse the version history of your tracked folders,
compare and restore earlier versions, recover deleted files, and manage snapshots, storage and
settings. Built with Flutter (Material 3), Riverpod, GoRouter and Dio. Runs on Windows and Linux.

The app is a window onto the Undo daemon. It never reads Undo's database or stored file
contents itself; every action goes through the daemon's local API (`127.0.0.1`, bearer token).

## Screens

| Screen | What you can do |
|---|---|
| Overview | Daemon status, tracked folders (add, pause, rescan, remove), storage summary, recent activity |
| Files | Browse a tracked folder, open any file's history, restore a version |
| History | Recent changes across all tracked folders; version details, content preview and diff against another version |
| Snapshots | Create, compare, restore and delete named snapshots of a folder |
| Storage | Usage and deduplication savings, verify stored data, apply retention, garbage collection |
| Settings | All daemon settings (capture, retention, exclusions, monitoring) |

Restoring always shows what will happen first. A file is never overwritten without confirmation,
and the current content is saved as a version before it is replaced.

## How it finds the daemon

1. It reads `daemon.json` and `api_token` from the data directory: `%LOCALAPPDATA%\Undo` on
   Windows, `~/.local/share/undo` on Linux, or `UNDO_HOME` if set.
2. If no daemon answers and `daemon.autostart` is on (the default), it starts one:
   * installed with the Windows installer: `backend\undo-daemon.exe --init` next to `Undo.exe`
     (no console window; `--init` creates the data directory on first run);
   * otherwise: `undo init` and `undo start`, using `UNDO_CLI` if set, else `undo` on `PATH`.

## Run and build

From the repository root, `make gui` or `./make.sh gui` runs it in development
(`flutter run -d windows` or `-d linux`). The daemon comes from the `undo` command, so run
`make init` first.

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
| `lib/core/api/` | `discovery.dart`: data directory, daemon discovery and start. `undo_api.dart`: typed API client (Dio) |
| `lib/core/models/` | Data classes for API responses |
| `lib/core/providers/` | Riverpod providers: the daemon connection and backend-backed data |
| `lib/core/theme/`, `lib/core/util/` | Light and dark themes; size, time and path formatting |
| `lib/features/` | One folder per screen, plus the version-details and restore dialogs |
| `lib/shared/widgets.dart` | Shared widgets, confirmation dialogs, the folder picker |
| `windows/runner/` | Native Windows host. `flutter_window.cpp` implements the folder picker on the `undo/native` channel. `main.cpp` sets the window title and size and holds the `UndoDesktopRunning` mutex the installer checks for. |
| `linux/` | Native Linux host |
| `assets/undo.png` | Sidebar logo (the app icon, 256 px) |
| `test/` | Unit tests for models and formatting |
