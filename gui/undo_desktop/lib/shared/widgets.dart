// Shared UI building blocks: async state handling, cards, chips, dialogs.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme/theme.dart';

/// Renders loading / error / empty / data states of an AsyncValue consistently.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.value,
    required this.builder,
    this.onRetry,
    this.isEmpty,
    this.empty,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) builder;
  final VoidCallback? onRetry;
  final bool Function(T data)? isEmpty;
  final Widget? empty;

  @override
  Widget build(BuildContext context) {
    return value.when(
      skipLoadingOnRefresh: true,
      data: (data) => (isEmpty?.call(data) ?? false) && empty != null ? empty! : builder(data),
      loading: () => const Center(child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator())),
      error: (e, _) => ErrorView(message: e.toString(), onRetry: onRetry),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.error_outline, color: scheme.error, size: 36),
          const SizedBox(height: 12),
          SelectableText(message, textAlign: TextAlign.center),
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('Retry')),
          ],
        ]),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action});
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 40, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Text(title, style: theme.textTheme.titleMedium),
          if (message != null) ...[
            const SizedBox(height: 6),
            Text(message!, textAlign: TextAlign.center, style: theme.textTheme.bodyMedium),
          ],
          if (action != null) ...[const SizedBox(height: 16), action!],
        ]),
      ),
    );
  }
}

class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, this.subtitle, this.actions = const []});
  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: theme.textTheme.headlineSmall),
            if (subtitle != null)
              Text(subtitle!, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          ]),
        ),
        ...actions.expand((w) => [w, const SizedBox(width: 8)]),
      ]),
    );
  }
}

class StatCard extends StatelessWidget {
  const StatCard({super.key, required this.label, required this.value, this.note, this.icon, this.color});
  final String label;
  final String value;
  final String? note;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            if (icon != null) ...[Icon(icon, size: 18, color: color ?? theme.colorScheme.primary), const SizedBox(width: 8)],
            Expanded(
              child: Text(label,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelLarge?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            ),
          ]),
          const SizedBox(height: 8),
          Text(value, style: theme.textTheme.headlineSmall?.copyWith(color: color)),
          if (note != null) Text(note!, style: theme.textTheme.bodySmall),
        ]),
      ),
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, required this.child, this.trailing, this.padding = const EdgeInsets.all(16)});
  final String title;
  final Widget child;
  final Widget? trailing;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
          child: Row(children: [
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
            ?trailing,
          ]),
        ),
        const Divider(),
        Padding(padding: padding, child: child),
      ]),
    );
  }
}

class OperationChip extends StatelessWidget {
  const OperationChip(this.operation, {super.key});
  final String operation;

  @override
  Widget build(BuildContext context) {
    final color = operationColor(context, operation);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(operation, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.ok, this.size = 10});
  final bool ok;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(shape: BoxShape.circle, color: ok ? Colors.green.shade500 : Colors.orange.shade600),
      );
}

Future<bool> confirmDialog(BuildContext context,
    {required String title, required String message, String confirm = 'Confirm', bool destructive = false}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(
          style: destructive ? FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error) : null,
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(confirm),
        ),
      ],
    ),
  );
  return result ?? false;
}

void showMessage(BuildContext context, String message, {bool error = false}) {
  final scheme = Theme.of(context).colorScheme;
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: error ? scheme.error : null,
    behavior: SnackBarBehavior.floating,
    width: 520,
  ));
}

/// Runs an async backend action with success/error feedback.
Future<T?> runAction<T>(BuildContext context, Future<T> Function() action, {String? success}) async {
  try {
    final result = await action();
    if (context.mounted && success != null) showMessage(context, success);
    return result;
  } catch (e) {
    if (context.mounted) showMessage(context, e.toString(), error: true);
    return null;
  }
}

const _native = MethodChannel('undo/native');

/// Native folder picker returning a filesystem path, or null when cancelled.
///
/// Windows: the system folder dialog, through the runner's "undo/native" channel.
/// Linux: zenity, then kdialog, whichever is installed.
Future<String?> pickFolder(String title) async {
  if (Platform.isWindows) {
    return _native.invokeMethod<String>('pickFolder', {'title': title});
  }
  final tools = <List<String>>[
    ['zenity', '--file-selection', '--directory', '--title=$title'],
    ['kdialog', '--getexistingdirectory', Platform.environment['HOME'] ?? '/', '--title', title],
  ];
  for (final cmd in tools) {
    try {
      final result = await Process.run(cmd.first, cmd.sublist(1));
      final out = (result.stdout as String).trim();
      return result.exitCode == 0 && out.isNotEmpty ? out : null;
    } on ProcessException {
      continue; // not installed: try the next one
    }
  }
  throw Exception('No folder picker found: install zenity or kdialog, or type the path.');
}
