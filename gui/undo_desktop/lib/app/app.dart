import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers/providers.dart';
import '../core/theme/theme.dart';
import 'router.dart';

class UndoApp extends ConsumerWidget {
  const UndoApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected =
        ref.watch(connectionProvider).phase == ConnectionPhase.connected;
    final mode = connected ? ref.watch(themeModeProvider) : ThemeMode.system;
    return MaterialApp.router(
      title: 'Undo',
      debugShowCheckedModeBanner: false,
      theme: UndoTheme.light(),
      darkTheme: UndoTheme.dark(),
      themeMode: mode,
      routerConfig: router,
    );
  }
}
