import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api/discovery.dart';
import '../core/providers/providers.dart';
import '../shared/widgets.dart';
import 'router.dart';

const _icons = [
  (Icons.space_dashboard_outlined, Icons.space_dashboard),
  (Icons.folder_outlined, Icons.folder),
  (Icons.history_outlined, Icons.history),
  (Icons.photo_library_outlined, Icons.photo_library),
  (Icons.storage_outlined, Icons.storage),
  (Icons.settings_outlined, Icons.settings),
];

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.location, required this.child});
  final String location;
  final Widget child;

  int _index() {
    final i = navItems.indexWhere((n) => location.startsWith(n.path));
    return i < 0 ? 0 : i;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conn = ref.watch(connectionProvider);
    final wide = MediaQuery.sizeOf(context).width >= 1100;
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            extended: wide,
            minExtendedWidth: 200,
            selectedIndex: _index(),
            onDestinationSelected: (i) => context.go(navItems[i].path),
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Image.asset('assets/undo.png', width: 28, height: 28),
                  if (wide) ...[
                    const SizedBox(width: 8),
                    Text('Undo', style: Theme.of(context).textTheme.titleLarge),
                  ],
                ],
              ),
            ),
            trailing: Expanded(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: _ConnectionBadge(wide: wide),
                ),
              ),
            ),
            destinations: [
              for (var i = 0; i < navItems.length; i++)
                NavigationRailDestination(
                  icon: Icon(_icons[i].$1),
                  selectedIcon: Icon(_icons[i].$2),
                  label: Text(navItems[i].label),
                ),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: conn.phase == ConnectionPhase.connected
                ? child
                : const _OfflinePage(),
          ),
        ],
      ),
    );
  }
}

class _ConnectionBadge extends ConsumerWidget {
  const _ConnectionBadge({required this.wide});
  final bool wide;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conn = ref.watch(connectionProvider);
    final ok = conn.phase == ConnectionPhase.connected;
    final label = switch (conn.phase) {
      ConnectionPhase.connected => 'Daemon running',
      ConnectionPhase.connecting => 'Connecting',
      ConnectionPhase.starting => 'Starting',
      ConnectionPhase.offline => 'Daemon offline',
    };
    return Tooltip(
      message: ok
          ? 'Connected to ${conn.api!.endpoint.baseUrl} (pid ${conn.api!.endpoint.pid})'
          : (conn.message ?? label),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          StatusDot(ok: ok),
          if (wide) ...[
            const SizedBox(width: 8),
            Text(label, style: Theme.of(context).textTheme.labelMedium),
          ],
        ],
      ),
    );
  }
}

class _OfflinePage extends ConsumerWidget {
  const _OfflinePage();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conn = ref.watch(connectionProvider);
    final notifier = ref.read(connectionProvider.notifier);
    final busy =
        conn.phase == ConnectionPhase.connecting ||
        conn.phase == ConnectionPhase.starting;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(busy ? Icons.sync : Icons.cloud_off_outlined),
                    const SizedBox(width: 12),
                    Text(
                      busy
                          ? (conn.message ?? 'Connecting ...')
                          : 'Not connected',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                if (busy) const LinearProgressIndicator(),
                if (!busy) ...[
                  SelectableText(
                    conn.message ?? 'The Undo daemon is not running.',
                  ),
                  const SizedBox(height: 12),
                  SelectableText(
                    'Data directory: ${Discovery.dataDir()}\n'
                    'The app starts the daemon with the `undo` command (set UNDO_CLI to its full path if it is not on PATH). '
                    'You can also run `undo start` in a terminal or install autostart with `undo service install`.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      FilledButton.icon(
                        onPressed: notifier.startDaemon,
                        icon: const Icon(Icons.play_arrow),
                        label: const Text('Start daemon'),
                      ),
                      const SizedBox(width: 12),
                      OutlinedButton.icon(
                        onPressed: notifier.connect,
                        icon: const Icon(Icons.refresh),
                        label: const Text('Retry'),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
