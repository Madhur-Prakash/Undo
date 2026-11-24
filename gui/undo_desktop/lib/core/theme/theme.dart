import 'package:flutter/material.dart';

/// Neutral Material 3 themes: slate seed, neutral variant, no decorative gradients.
class UndoTheme {
  static const _seed = Color(0xFF3D5A80);

  static ThemeData _base(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(
      seedColor: _seed,
      brightness: brightness,
      dynamicSchemeVariant: DynamicSchemeVariant.neutral,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.standard,
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant, space: 1),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        isDense: true,
      ),
      listTileTheme: const ListTileThemeData(dense: true),
    );
  }

  static ThemeData light() => _base(Brightness.light);
  static ThemeData dark() => _base(Brightness.dark);
}

/// Semantic colours for operations and states.
Color operationColor(BuildContext context, String op) {
  final scheme = Theme.of(context).colorScheme;
  return switch (op) {
    'CREATE' => Colors.green.shade600,
    'MODIFY' => scheme.primary,
    'DELETE' => scheme.error,
    'RENAME' || 'MOVE' => Colors.purple.shade400,
    _ => scheme.outline,
  };
}
