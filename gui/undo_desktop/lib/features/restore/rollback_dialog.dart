// Roll back a tracked folder (or a subfolder) to how it was at a point in time, without a
// snapshot: choose the folder and the time here, then the restore dialog previews the result.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path/path.dart' as p;

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import 'restore_dialog.dart';

/// Opens the rollback flow for [root]. Returns the restore result when something was restored.
Future<RestoreResult?> showRollbackDialog(
  BuildContext context,
  WidgetRef ref,
  RootInfo root,
) async {
  final choice = await showDialog<(String, DateTime)>(
    context: context,
    builder: (_) => _RollbackDialog(root: root),
  );
  if (choice == null || !context.mounted) return null;
  final (folder, at) = choice;
  final api = ref.read(apiProvider);
  return showRestoreDialog(
    context,
    title: 'Roll back folder',
    source: '$folder\nas it was on ${formatDateTime(at)}',
    originalLocation: folder,
    run: (dest, overwrite, dry) => api.restoreAt(
      folder,
      at,
      destination: dest,
      overwrite: overwrite,
      dryRun: dry,
    ),
  );
}

class _Preset {
  const _Preset(this.label, this.ago);
  final String label;
  final Duration ago;
}

const _presets = [
  _Preset('15 minutes ago', Duration(minutes: 15)),
  _Preset('1 hour ago', Duration(hours: 1)),
  _Preset('3 hours ago', Duration(hours: 3)),
  _Preset('Yesterday', Duration(days: 1)),
  _Preset('1 week ago', Duration(days: 7)),
];

class _RollbackDialog extends StatefulWidget {
  const _RollbackDialog({required this.root});
  final RootInfo root;

  @override
  State<_RollbackDialog> createState() => _RollbackDialogState();
}

class _RollbackDialogState extends State<_RollbackDialog> {
  late String _folder = widget.root.path;
  DateTime _at = DateTime.now().subtract(const Duration(hours: 1));
  String? _preset = '1 hour ago';
  String? _error;

  bool _inside(String child, String parent) {
    final c = p.normalize(child).toLowerCase();
    final pr = p.normalize(parent).toLowerCase();
    return c == pr || p.isWithin(pr, c);
  }

  Future<void> _chooseFolder() async {
    final dir = await pickFolder(
      'Folder to roll back (inside ${widget.root.path})',
    );
    if (dir == null) return;
    setState(() {
      if (_inside(dir, widget.root.path)) {
        _folder = dir;
        _error = null;
      } else {
        _error = 'Choose ${widget.root.path} or a folder inside it.';
      }
    });
  }

  Future<void> _chooseTime() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _at,
      firstDate: DateTime(now.year - 5),
      lastDate: now,
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_at),
    );
    if (time == null) return;
    setState(() {
      _at = DateTime(date.year, date.month, date.day, time.hour, time.minute);
      _preset = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final future = _at.isAfter(DateTime.now());
    return AlertDialog(
      title: const Text('Roll back a folder'),
      content: SizedBox(
        width: 560,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Puts every file in the folder back the way it was at the chosen time. '
              'Files created later are left alone and nothing is deleted. You see a preview before anything is written.',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            Text('Folder', style: theme.textTheme.labelLarge),
            const SizedBox(height: 4),
            Row(
              children: [
                Expanded(child: SelectableText(_folder)),
                TextButton.icon(
                  onPressed: _chooseFolder,
                  icon: const Icon(Icons.folder_open),
                  label: const Text('Choose subfolder'),
                ),
              ],
            ),
            if (_error != null)
              Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
            const SizedBox(height: 16),
            Text('Point in time', style: theme.textTheme.labelLarge),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final preset in _presets)
                  ChoiceChip(
                    label: Text(preset.label),
                    selected: _preset == preset.label,
                    onSelected: (_) => setState(() {
                      _preset = preset.label;
                      _at = DateTime.now().subtract(preset.ago);
                    }),
                  ),
                ActionChip(
                  avatar: const Icon(Icons.event, size: 18),
                  label: const Text('Pick date and time'),
                  onPressed: _chooseTime,
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              'As it was on ${formatDateTime(_at)}',
              style: theme.textTheme.titleSmall?.copyWith(
                color: future ? theme.colorScheme.error : null,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton.icon(
          onPressed: future
              ? null
              : () => Navigator.pop(context, (_folder, _at)),
          icon: const Icon(Icons.preview_outlined),
          label: const Text('Preview'),
        ),
      ],
    );
  }
}
