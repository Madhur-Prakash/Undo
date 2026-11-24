import 'package:go_router/go_router.dart';

import '../features/dashboard/overview_page.dart';
import '../features/file_explorer/file_history_page.dart';
import '../features/file_explorer/files_page.dart';
import '../features/history/history_page.dart';
import '../features/settings/settings_page.dart';
import '../features/snapshots/snapshots_page.dart';
import '../features/storage/storage_page.dart';
import 'shell.dart';

class NavItem {
  const NavItem(this.path, this.label);
  final String path;
  final String label;
}

const navItems = [
  NavItem('/overview', 'Overview'),
  NavItem('/files', 'Files'),
  NavItem('/history', 'History'),
  NavItem('/snapshots', 'Snapshots'),
  NavItem('/storage', 'Storage'),
  NavItem('/settings', 'Settings'),
];

final router = GoRouter(
  initialLocation: '/overview',
  routes: [
    ShellRoute(
      builder: (context, state, child) => AppShell(location: state.uri.path, child: child),
      routes: [
        GoRoute(path: '/overview', builder: (_, _) => const OverviewPage()),
        GoRoute(
          path: '/files',
          builder: (_, _) => const FilesPage(),
          routes: [
            GoRoute(
              path: ':id',
              builder: (_, state) => FileHistoryPage(fileId: int.parse(state.pathParameters['id']!)),
            ),
          ],
        ),
        GoRoute(path: '/history', builder: (_, _) => const HistoryPage()),
        GoRoute(path: '/snapshots', builder: (_, _) => const SnapshotsPage()),
        GoRoute(path: '/storage', builder: (_, _) => const StoragePage()),
        GoRoute(path: '/settings', builder: (_, _) => const SettingsPage()),
      ],
    ),
  ],
);
