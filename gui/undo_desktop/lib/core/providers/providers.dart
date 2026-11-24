// Riverpod providers: connection lifecycle and backend-backed data.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/discovery.dart';
import '../api/undo_api.dart';
import '../models/models.dart';

enum ConnectionPhase { connecting, starting, connected, offline }

class DaemonConnection {
  const DaemonConnection(this.phase, {this.api, this.message});
  final ConnectionPhase phase;
  final UndoApi? api;
  final String? message;
}

class ConnectionNotifier extends Notifier<DaemonConnection> {
  bool _autostartTried = false;
  Timer? _watchdog;

  @override
  DaemonConnection build() {
    ref.onDispose(() => _watchdog?.cancel());
    Future.microtask(connect);
    return const DaemonConnection(ConnectionPhase.connecting);
  }

  Future<void> connect() async {
    state = const DaemonConnection(ConnectionPhase.connecting);
    final endpoint = await Discovery.find();
    if (endpoint != null) {
      _setConnected(endpoint);
      return;
    }
    if (!_autostartTried && Discovery.autostartEnabled()) {
      _autostartTried = true;
      await startDaemon();
      return;
    }
    state = DaemonConnection(ConnectionPhase.offline,
        message: Discovery.isInitialized()
            ? 'The Undo daemon is not running.'
            : 'Undo is not initialised on this computer yet.');
  }

  Future<void> startDaemon() async {
    state = const DaemonConnection(ConnectionPhase.starting, message: 'Starting the Undo daemon ...');
    final error = await Discovery.startDaemon();
    final endpoint = await Discovery.find();
    if (endpoint != null) {
      _setConnected(endpoint);
    } else {
      state = DaemonConnection(ConnectionPhase.offline,
          message: 'Could not start the daemon automatically.${error != null ? '\n$error' : ''}');
    }
  }

  Future<void> stopDaemon() async {
    final api = state.api;
    if (api == null) return;
    try {
      await api.shutdown();
    } catch (_) {}
    _watchdog?.cancel();
    _autostartTried = true; // do not immediately restart what the user stopped
    state = const DaemonConnection(ConnectionPhase.offline, message: 'The daemon was stopped.');
  }

  void _setConnected(DaemonEndpoint endpoint) {
    state = DaemonConnection(ConnectionPhase.connected, api: UndoApi(endpoint));
    _watchdog?.cancel();
    _watchdog = Timer.periodic(const Duration(seconds: 15), (_) async {
      if (state.phase != ConnectionPhase.connected) return;
      final still = await Discovery.find();
      if (still == null) {
        state = const DaemonConnection(ConnectionPhase.offline, message: 'Lost connection to the daemon.');
      }
    });
  }
}

final connectionProvider = NotifierProvider<ConnectionNotifier, DaemonConnection>(ConnectionNotifier.new);

/// The API client; throws when not connected so dependent providers show an error state.
final apiProvider = Provider<UndoApi>((ref) {
  final conn = ref.watch(connectionProvider);
  final api = conn.api;
  if (api == null) throw ApiException('connection', conn.message ?? 'Not connected');
  return api;
});

final statusProvider = FutureProvider.autoDispose<StatusInfo>((ref) => ref.watch(apiProvider).status());
final rootsProvider = FutureProvider.autoDispose<List<RootInfo>>((ref) => ref.watch(apiProvider).roots());
final activityProvider =
    FutureProvider.autoDispose.family<List<VersionInfo>, int>((ref, limit) => ref.watch(apiProvider).activity(limit: limit));
final snapshotsProvider = FutureProvider.autoDispose<List<SnapshotInfo>>((ref) => ref.watch(apiProvider).snapshots());
final storageProvider = FutureProvider.autoDispose<StorageStats>((ref) => ref.watch(apiProvider).storageStats());
final settingsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) => ref.watch(apiProvider).settings());
final exclusionsProvider = FutureProvider.autoDispose<List<ExclusionInfo>>((ref) => ref.watch(apiProvider).exclusions());
final fileHistoryProvider =
    FutureProvider.autoDispose.family<FileHistory, int>((ref, id) => ref.watch(apiProvider).fileHistory(id));
final versionDetailProvider =
    FutureProvider.autoDispose.family<VersionDetail, int>((ref, id) => ref.watch(apiProvider).version(id));

class FileQuery {
  const FileQuery({this.text = '', this.includeDeleted = false, this.rootId});
  final String text;
  final bool includeDeleted;
  final int? rootId;

  FileQuery copyWith({String? text, bool? includeDeleted, int? rootId, bool clearRoot = false}) => FileQuery(
        text: text ?? this.text,
        includeDeleted: includeDeleted ?? this.includeDeleted,
        rootId: clearRoot ? null : (rootId ?? this.rootId),
      );
}

class FileQueryNotifier extends Notifier<FileQuery> {
  @override
  FileQuery build() => const FileQuery();
  void update(FileQuery q) => state = q;
}

final fileQueryProvider = NotifierProvider<FileQueryNotifier, FileQuery>(FileQueryNotifier.new);

final filesProvider = FutureProvider.autoDispose<FilePage>((ref) {
  final q = ref.watch(fileQueryProvider);
  return ref.watch(apiProvider).files(query: q.text, includeDeleted: q.includeDeleted, rootId: q.rootId);
});

/// Theme mode follows the backend setting `ui.theme` once connected.
final themeModeProvider = Provider<ThemeMode>((ref) {
  final settings = ref.watch(settingsProvider);
  final theme = settings.maybeWhen(data: (s) => (s['ui'] as Map?)?['theme'] as String?, orElse: () => null);
  return switch (theme) {
    'light' => ThemeMode.light,
    'dark' => ThemeMode.dark,
    _ => ThemeMode.system,
  };
});

/// Refresh everything shown from the backend.
void refreshAll(WidgetRef ref) {
  ref.invalidate(statusProvider);
  ref.invalidate(rootsProvider);
  ref.invalidate(activityProvider);
  ref.invalidate(snapshotsProvider);
  ref.invalidate(storageProvider);
  ref.invalidate(settingsProvider);
  ref.invalidate(exclusionsProvider);
  ref.invalidate(filesProvider);
  ref.invalidate(fileHistoryProvider);
}
