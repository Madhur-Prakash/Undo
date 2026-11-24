# Architecture

Undo is a monorepo with one source of truth, the **Python backend** (`backend/src/undo_core`),
and three clients that contain no business logic: the **CLI** (`cli/undo_cli`), the **Textual
TUI** (`cli/undo_cli/tui`) and the **Flutter desktop app** (`gui/undo_desktop`).

```
                 ┌───────────────────────────── undo daemon (one per data directory) ─────────────────────────────┐
 Filesystem ───► │ WatcherManager ──► EventProcessor ──► CaptureEngine ──► BlobStore ──► blobs/, chunks/          │
                 │   (watchdog)        (queue, debounce,   (locks, retries,   (BLAKE3, zstd,                       │
                 │                      backpressure)       stability)         staging, verify)                    │
                 │        ▲                                      │                                                 │
                 │        │ ReconcileQueue ◄── Scheduler          ▼                                                 │
                 │        └── Reconciler (scans) ───────► version_manager ──► SQLite (WAL) undo.db                  │
                 │                                                                   ▲                             │
                 │                       UndoService (facade) ───────────────────────┘                             │
                 │                              ▲                                                                  │
                 │                    FastAPI app (127.0.0.1, bearer token)                                        │
                 └──────────────────────────────┼─────────────────────────────────────────────────────────────────┘
                                                │ HTTP /api/v1
                         ┌──────────────────────┼──────────────────────┐
                    undo CLI (Rich)        undo tui (Textual)     Flutter GUI (Riverpod, Dio)
```

## Components

| Package | Responsibility |
|---|---|
| `config/` | Pydantic `Settings` persisted to `config.json` (atomic writes, validation, live reload); defaults; API token |
| `database/` | SQLAlchemy models, WAL engine with `BEGIN IMMEDIATE` writers, ordered migrations, query repositories |
| `storage/` | Content addressing, compression policy, `BlobStore` (ingest, verify, read, pins), chunk dedup accounting, integrity verification, garbage collection |
| `versioning/` | `CaptureEngine` (safe capture), `version_manager` (create/modify/delete/move bookkeeping), history queries, snapshots, retention, diff |
| `filesystem/` | Exclusions, scanner, `Reconciler`, `EventProcessor`, `WatcherManager`, platform adapters (`linux.py` inotify limits, `windows.py` ReadDirectoryChangesW + USN probe) |
| `recovery/` | Restore safety primitives, file/tree restore engine, point-in-time and snapshot entry resolution, deleted-file listing |
| `daemon/` | Process lock, health counters, scheduler, startup recovery and discovery (`lifecycle.py`), `DaemonManager` |
| `api/` | FastAPI app factory, auth dependency, request schemas, routes |
| `platform/` | Paths and the data-directory layout, permissions, autostart integration (systemd / scheduled task) |
| `service.py` | `UndoService`: the only API the outside world uses; returns models from `domain.py` |
| `context.py` | Composition root wiring one data directory's components |

## Communication

* **Daemon ↔ clients.** The daemon binds the API to `127.0.0.1` (configurable loopback address;
  non-loopback requires `api.allow_remote`). Every route except `/api/v1/ping` requires
  `Authorization: Bearer <token>`, the token being generated at `undo init` and stored in
  `<data>/api_token` with owner-only permissions (chmod 600 / icacls). The daemon writes
  `<data>/daemon.json` (pid, host, port) for discovery; clients ping it and read the token.
* **CLI without a daemon.** `undo_cli.client.get_backend()` returns a `RemoteBackend` when a
  daemon answers, otherwise a `LocalBackend` running `UndoService` in-process. Both expose
  `call(op, **kwargs)` with the same operation names and return identical JSON, so rendering
  code does not know which is used. A local *write* first takes the data-directory process lock;
  if a daemon owns it the command is routed to the daemon instead, so two processes never write
  concurrently.
* **GUI.** `Discovery` reads `daemon.json`/`api_token`; if no daemon answers and
  `daemon.autostart` is on, it runs `undo start` (or `$UNDO_CLI start`) once. A watchdog
  re-checks the connection every 15 s.

## Concurrency model

* **Single daemon per data directory**: an OS-level exclusive lock (`fcntl.flock` /
  `msvcrt.locking`) on `undo.lock`, held for the daemon's lifetime. The kernel releases it when the
  process dies, so stale PID files can never block a restart; the PID is informational only.
* **Single writer to metadata**: writes use `BEGIN IMMEDIATE` (serialised across processes by
  SQLite) plus an in-process lock. Readers use WAL snapshots and never block writers.
* **No slow I/O inside write transactions**: files are hashed and compressed before the short
  transaction that records the result.
* **Per-file capture locks** (`KeyedLocks`) make duplicate events for one file serialise; a
  per-hash lock makes concurrent captures of identical content store it once.
* **Bounded resources**: event queue (`monitor.event_queue_size`), capture workers
  (`capture.max_concurrent`), reconciliation workers, streaming I/O with 1 MiB buffers.

## Event flow

1. watchdog delivers an event to `_Handler` → `RawEvent` → `EventProcessor.submit()`.
   If the queue is full the event is dropped, counted, and a reconciliation of the root is
   requested (backpressure without losing changes).
2. The dispatcher thread turns created/modified events into *pending captures* keyed by path;
   new events slide the deadline by `capture.debounce_seconds` (capped at 30 s so continuously
   written files still get captured). Deletes and moves update metadata directly; a new or
   moved-in directory triggers a subtree reconciliation.
3. The debounce thread hands due captures to a bounded thread pool running `CaptureEngine.capture`.

## Reconciliation

`Reconciler.reconcile(root, prefix, deep)` scans the tree, compares with the database, detects
renames (filesystem identity confirmed by name/size, then a unique content-hash match), captures
new and changed files (size+mtime as cheap detector, full re-hash in `deep` mode) and records
deletions. It runs at daemon start (`monitor.initial_scan`), every
`monitor.reconcile_interval_seconds`, after queue overflows and for new directories. A missing root
(for example an unmounted drive) aborts the scan instead of recording mass deletions.

## Scheduled jobs (daemon)

| Job | Interval setting | Purpose |
|---|---|---|
| reconcile | `monitor.reconcile_interval_seconds` | full rescan of enabled roots |
| retention | `retention.interval_seconds` | apply policy (then GC if versions were removed) |
| gc | `daemon.gc_interval_seconds` | delete unreferenced data |
| verify | `daemon.verify_interval_seconds` (0 = off) | full integrity verification |
| maintenance | 30 s | restart dead observers, sync watches with roots, purge stale pins |
| checkpoint | 10 min | WAL checkpoint |
