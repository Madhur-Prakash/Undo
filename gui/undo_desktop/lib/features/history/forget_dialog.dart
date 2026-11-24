// Remove history on purpose: a file's or a folder's whole history, or only its older versions.
// Always previews first (dry run), then asks to confirm. The files themselves are never touched.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path/path.dart' as p;

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

/// Opens the dialog for [path] (a file, or a folder when [folderRoot] is given: the tracked
/// folder it lives in, so a subfolder can be chosen). Returns the result when history was removed.
Future<ForgetResult?> showForgetDialog(
  BuildContext context, {
  required String path,
  String? folderRoot,
}) =>
    showDialog<ForgetResult>(
      context: context,
      builder: (_) => _ForgetDialog(path: path, folderRoot: folderRoot),
    );

class _Age {
  const _Age(this.label, this.duration);
  final String label;
  final Duration duration;
}

const _ages = [
  _Age('1 week', Duration(days: 7)),
  _Age('1 month', Duration(days: 30)),
  _Age('3 months', Duration(days: 90)),
  _Age('6 months', Duration(days: 182)),
  _Age('1 year', Duration(days: 365)),
];

class _ForgetDialog extends ConsumerStatefulWidget {
  const _ForgetDialog({required this.path, this.folderRoot});
  final String path;
  final String? folderRoot;

  @override
  ConsumerState<_ForgetDialog> createState() => _ForgetDialogState();
}

class _ForgetDialogState extends ConsumerState<_ForgetDialog> {
  late String _path = widget.path;
  bool _everything = true; // false: only versions older than _before
  DateTime _before = DateTime.now().subtract(const Duration(days: 30));
  String? _ageLabel = '1 month';
  ForgetResult? _preview;
  bool _busy = false;
  String? _error;

  bool get _isFolder => widget.folderRoot != null;

  void _changed(VoidCallback update) => setState(() {
        update();
        _preview = null; // the plan changed: preview again
        _error = null;
      });

  Future<void> _chooseSubfolder() async {
    final root = widget.folderRoot!;
    final dir = await pickFolder('Folder to clean up (inside $root)');
    if (dir == null) return;
    final inside = p.equals(dir.toLowerCase(), root.toLowerCase()) ||
        p.isWithin(root.toLowerCase(), dir.toLowerCase());
    if (!inside) {
      setState(() => _error = 'Choose $root or a folder inside it.');
      return;
    }
    _changed(() => _path = dir);
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _before,
      firstDate: DateTime(now.year - 10),
      lastDate: now,
    );
    if (date == null) return;
    _changed(() {
      _before = DateTime(date.year, date.month, date.day);
      _ageLabel = null;
    });
  }

  Future<void> _run({required bool dryRun}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await ref.read(apiProvider).forget(_path, before: _everything ? null : _before, dryRun: dryRun);
      if (!mounted) return;
      if (dryRun) {
        setState(() => _preview = r);
      } else {
        Navigator.pop(context, r);
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final preview = _preview;
    return AlertDialog(
      title: Text(_isFolder ? 'Delete folder history' : 'Delete file history'),
      content: SizedBox(
        width: 600,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            'Removes recorded versions from Undo. Your files are not touched. '
            'Versions that belong to a snapshot are kept.',
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: 16),
          Text(_isFolder ? 'Folder' : 'File', style: theme.textTheme.labelLarge),
          const SizedBox(height: 4),
          Row(children: [
            Expanded(child: SelectableText(_path)),
            if (_isFolder)
              TextButton.icon(
                onPressed: _busy ? null : _chooseSubfolder,
                icon: const Icon(Icons.folder_open),
                label: const Text('Choose subfolder'),
              ),
          ]),
          const SizedBox(height: 16),
          Text('What to remove', style: theme.textTheme.labelLarge),
          RadioGroup<bool>(
            groupValue: _everything,
            onChanged: (v) => _changed(() => _everything = v ?? true),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              RadioListTile<bool>(
                contentPadding: EdgeInsets.zero,
                value: true,
                title: const Text('All history'),
                subtitle: Text(_isFolder
                    ? 'Every version of every file in this folder. Files that still exist start a new history.'
                    : 'Every version of this file. If it still exists, it starts a new history.'),
              ),
              RadioListTile<bool>(
                contentPadding: EdgeInsets.zero,
                value: false,
                title: const Text('Only versions older than a date'),
                subtitle: const Text('The latest version of each file is always kept.'),
              ),
            ]),
          ),
          if (!_everything) ...[
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final age in _ages)
                ChoiceChip(
                  label: Text('Older than ${age.label}'),
                  selected: _ageLabel == age.label,
                  onSelected: (_) => _changed(() {
                    _ageLabel = age.label;
                    _before = DateTime.now().subtract(age.duration);
                  }),
                ),
              ActionChip(
                avatar: const Icon(Icons.event, size: 18),
                label: const Text('Pick a date'),
                onPressed: _busy ? null : _pickDate,
              ),
            ]),
            const SizedBox(height: 8),
            Text('Removes versions saved before ${formatDateTime(_before)}', style: theme.textTheme.titleSmall),
          ],
          if (preview != null) ...[
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: preview.versionsRemoved > 0 ? scheme.errorContainer.withValues(alpha: 0.4) : scheme.surfaceContainerHigh,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                preview.versionsRemoved == 0
                    ? 'Nothing to remove.${preview.versionsKeptInSnapshots > 0 ? ' ${preview.versionsKeptInSnapshots} version(s) are kept because they belong to a snapshot.' : ''}'
                    : '${preview.versionsRemoved} version(s) of ${preview.filesAffected} file(s) will be removed.'
                        '${preview.filesRemoved > 0 ? ' ${preview.filesRemoved} file(s) will have no history left.' : ''}'
                        '${preview.versionsKeptInSnapshots > 0 ? ' ${preview.versionsKeptInSnapshots} version(s) are kept (in a snapshot).' : ''}'
                        ' This cannot be undone.',
              ),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: scheme.error)),
          ],
          if (_busy) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        OutlinedButton.icon(
          onPressed: _busy ? null : () => _run(dryRun: true),
          icon: const Icon(Icons.preview_outlined),
          label: const Text('Preview'),
        ),
        FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: scheme.error, foregroundColor: scheme.onError),
          onPressed: _busy || preview == null || preview.versionsRemoved == 0 ? null : () => _run(dryRun: false),
          icon: const Icon(Icons.delete_forever_outlined),
          label: const Text('Delete'),
        ),
      ],
    );
  }
}

/// Deletes one version after confirming. The latest version is refused by the backend.
Future<bool> deleteSingleVersion(BuildContext context, WidgetRef ref, VersionInfo v) async {
  final ok = await confirmDialog(
    context,
    title: 'Delete version ${v.id}?',
    message: '${v.relativePath} · ${formatDateTime(v.timestamp)}'
        '${v.hasContent ? ' · ${formatBytes(v.fileSize)}' : ''}\n\n'
        'This version is removed from history and cannot be restored any more. '
        'Your file is not touched.',
    confirm: 'Delete version',
    destructive: true,
  );
  if (!ok || !context.mounted) return false;
  final r = await runAction(
    context,
    () => ref.read(apiProvider).deleteVersions([v.id]),
    success: 'Version ${v.id} deleted. Run garbage collection on the Storage page to free the space.',
  );
  return r != null;
}
