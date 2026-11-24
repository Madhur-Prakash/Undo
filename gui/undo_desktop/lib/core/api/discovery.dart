// Locates the Undo data directory, the running daemon and its API token, and can
// start the daemon (the bundled backend, or the `undo` CLI).
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:path/path.dart' as p;

class DaemonEndpoint {
  const DaemonEndpoint({
    required this.baseUrl,
    required this.token,
    required this.pid,
  });
  final String baseUrl;
  final String token;
  final int pid;
}

class Discovery {
  /// Same rules as the Python backend (undo_core/platform/paths.py).
  static String dataDir() {
    final env = Platform.environment;
    final override = env['UNDO_HOME'];
    if (override != null && override.isNotEmpty) return override;
    if (Platform.isWindows) {
      final local =
          env['LOCALAPPDATA'] ??
          p.join(env['USERPROFILE'] ?? '', 'AppData', 'Local');
      return p.join(local, 'Undo');
    }
    if (Platform.isMacOS) {
      return p.join(
        env['HOME'] ?? '',
        'Library',
        'Application Support',
        'Undo',
      );
    }
    final xdg = env['XDG_DATA_HOME'];
    return p.join(
      xdg != null && xdg.isNotEmpty
          ? xdg
          : p.join(env['HOME'] ?? '', '.local', 'share'),
      'undo',
    );
  }

  static bool isInitialized() =>
      File(p.join(dataDir(), 'config.json')).existsSync() &&
      File(p.join(dataDir(), 'undo.db')).existsSync();

  /// Reads `daemon.autostart` from config.json (the API may not be up yet).
  static bool autostartEnabled() {
    try {
      final cfg = jsonDecode(
        File(p.join(dataDir(), 'config.json')).readAsStringSync(),
      ) as Map<String, dynamic>;
      final daemon = cfg['daemon'] as Map<String, dynamic>?;
      return (daemon?['autostart'] as bool?) ?? true;
    } catch (_) {
      return true;
    }
  }

  static Future<DaemonEndpoint?> find() async {
    final dir = dataDir();
    final infoFile = File(p.join(dir, 'daemon.json'));
    final tokenFile = File(p.join(dir, 'api_token'));
    if (!infoFile.existsSync() || !tokenFile.existsSync()) return null;
    try {
      final info =
          jsonDecode(await infoFile.readAsString()) as Map<String, dynamic>;
      final host = info['host'] as String;
      final port = info['port'] as int;
      final hostPart = host.contains(':') ? '[$host]' : host;
      final baseUrl = 'http://$hostPart:$port/api/v1';
      final dio = Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 2),
          receiveTimeout: const Duration(seconds: 2),
        ),
      );
      final resp = await dio.get<Map<String, dynamic>>('$baseUrl/ping');
      if (resp.data?['app'] != 'undo') return null;
      final token = (await tokenFile.readAsString()).trim();
      return DaemonEndpoint(
        baseUrl: baseUrl,
        token: token,
        pid: info['pid'] as int,
      );
    } catch (_) {
      return null;
    }
  }

  /// The backend bundled by the Windows installer: `<app>\backend\undo-daemon.exe`.
  static String? bundledDaemon() {
    final dir = p.join(p.dirname(Platform.resolvedExecutable), 'backend');
    final exe = p.join(
      dir,
      Platform.isWindows ? 'undo-daemon.exe' : 'undo-daemon',
    );
    return File(exe).existsSync() ? exe : null;
  }

  /// Candidate commands for the CLI: $UNDO_CLI, the bundled `undo`, then `undo` on PATH.
  static List<String> _cliCandidates() {
    final env = Platform.environment;
    final bundled = p.join(
      p.dirname(Platform.resolvedExecutable),
      'backend',
      Platform.isWindows ? 'undo.exe' : 'undo',
    );
    return [
      if ((env['UNDO_CLI'] ?? '').isNotEmpty) env['UNDO_CLI']!,
      if (File(bundled).existsSync()) bundled,
      'undo',
    ];
  }

  /// Waits for a daemon to answer, up to [timeout].
  static Future<DaemonEndpoint?> waitFor(Duration timeout) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      final found = await find();
      if (found != null) return found;
      await Future<void>.delayed(const Duration(milliseconds: 400));
    }
    return null;
  }

  /// Starts the daemon. Returns null on success, else an error message.
  ///
  /// With the installed backend, the windowless `undo-daemon --init` is launched
  /// directly (no console window flashes). Otherwise `undo init` + `undo start` run.
  static Future<String?> startDaemon() async {
    final errors = <String>[];
    final daemon = bundledDaemon();
    if (daemon != null) {
      try {
        await Process.start(daemon, [
          '--init',
        ], mode: ProcessStartMode.detached);
        if (await waitFor(const Duration(seconds: 40)) != null) return null;
        errors.add(
          '$daemon did not answer; see the log in ${p.join(dataDir(), 'logs')}',
        );
      } catch (e) {
        errors.add('$daemon: $e');
      }
    }
    for (final cli in _cliCandidates()) {
      try {
        if (!isInitialized()) {
          final init = await Process.run(cli, ['init'], runInShell: true);
          if (init.exitCode != 0) {
            errors.add('$cli init: ${init.stderr}'.trim());
            continue;
          }
        }
        final result = await Process.run(cli, [
          'start',
        ], runInShell: true).timeout(const Duration(seconds: 40));
        if (result.exitCode == 0) return null;
        errors.add(
          '$cli start: ${(result.stderr as String).trim()} ${(result.stdout as String).trim()}'
              .trim(),
        );
      } catch (e) {
        errors.add('$cli: $e');
      }
    }
    return errors.isEmpty
        ? 'The undo command was not found'
        : errors.join('\n');
  }
}
