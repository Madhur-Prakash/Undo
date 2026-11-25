// Restore confirmation: always preview (dry run) first; overwriting must be ticked explicitly.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers/providers.dart';
import '../../shared/widgets.dart';
import '../history/diff_view.dart';
import 'merge_editor.dart';

import '../../core/models/models.dart';
import '../../core/util/format.dart';

typedef RestoreRunner = Future<RestoreResult> Function(String? destination, bool overwrite, bool dryRun);

Future<RestoreResult?> showRestoreDialog(
  BuildContext context, {
  required String title,
  required String source,
  required String originalLocation,
  required RestoreRunner run,
}) {
  return showDialog<RestoreResult>(
    context: context,
    builder: (_) => RestoreDialog(title: title, source: source, originalLocation: originalLocation, run: run),
  );
}

class RestoreDialog extends ConsumerStatefulWidget {
  const RestoreDialog({super.key, required this.title, required this.source, required this.originalLocation, required this.run});
  final String title;
  final String source;
  final String originalLocation;
  final RestoreRunner run;

  @override
  ConsumerState<RestoreDialog> createState() => _RestoreDialogState();
}

/// Preview order: what needs attention first.
const _actionOrder = {'conflict': 0, 'error': 1, 'missing_blob': 2, 'overwrite': 3, 'create': 4, 'identical': 5};

class _RestoreDialogState extends ConsumerState<RestoreDialog> {
  /// Which outcome to list ('all', or one action such as 'conflict').
  String _filter = 'all';
  final _dest = TextEditingController();
  bool _overwrite = false;
  bool _busy = false;
  RestoreResult? _plan;
  RestoreResult? _done;
  String? _error;

  @override
  void initState() {
    super.initState();
    _preview();
  }

  @override
  void dispose() {
    _dest.dispose();
    super.dispose();
  }

  String? get _destination => _dest.text.trim().isEmpty ? null : _dest.text.trim();

  void _invalidate() => setState(() {
        _plan = null;
        _done = null;
        _filter = 'all';
      });

  /// Items of [r] for the current filter, conflicts and errors first.
  List<RestoreItem> _visible(RestoreResult r) {
    final items = [for (final i in r.items) if (_filter == 'all' || i.action == _filter) i];
    items.sort((x, y) {
      final byAction = (_actionOrder[x.action] ?? 9).compareTo(_actionOrder[y.action] ?? 9);
      return byAction != 0 ? byAction : x.destination.compareTo(y.destination);
    });
    return items;
  }

  void _compare(RestoreItem item) {
    final api = ref.read(apiProvider);
    showDiffDialog(
      context,
      title: 'Disk vs version ${item.versionId}: ${item.relativePath}',
      future: api.diffWithFile(item.versionId!, path: item.destination),
      onEdit: item.action == 'identical' ? null : () => _resolve(item),
    );
  }

  /// Merge the version into the file, like resolving a merge conflict. Re-previews afterwards.
  Future<void> _resolve(RestoreItem item) async {
    final written = await showMergeEditor(context, versionId: item.versionId!, path: item.destination);
    if (written && mounted && _done == null) await _preview();
  }

  Widget _filters(RestoreResult r) {
    final counts = <String, int>{};
    for (final i in r.items) {
      counts[i.action] = (counts[i.action] ?? 0) + 1;
    }
    const labels = {
      'conflict': 'Conflicts',
      'error': 'Errors',
      'missing_blob': 'Missing data',
      'overwrite': 'Overwrite',
      'create': 'Create',
      'identical': 'Identical',
    };
    final keys = counts.keys.toList()..sort((a, b) => (_actionOrder[a] ?? 9).compareTo(_actionOrder[b] ?? 9));
    return Wrap(spacing: 8, runSpacing: 6, children: [
      ChoiceChip(
        label: Text('All (${r.items.length})'),
        selected: _filter == 'all',
        onSelected: (_) => setState(() => _filter = 'all'),
      ),
      for (final k in keys)
        ChoiceChip(
          label: Text('${labels[k] ?? k} (${counts[k]})'),
          selected: _filter == k,
          onSelected: (_) => setState(() => _filter = k),
        ),
    ]);
  }

  Future<void> _preview() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final plan = await widget.run(_destination, _overwrite, true);
      setState(() => _plan = plan);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _restore() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.run(_destination, _overwrite, false);
      setState(() => _done = result);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _browse() async {
    final dir = await pickFolder('Restore into folder');
    if (dir != null) {
      _dest.text = dir.endsWith('/') || dir.endsWith('\\') ? dir : '$dir${dir.contains('\\') ? '\\' : '/'}';
      _invalidate();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final shown = _done ?? _plan;
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 820,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          _row(context, 'Source', widget.source),
          _row(context, 'Original location', widget.originalLocation),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _dest,
                enabled: !_busy && _done == null,
                decoration: const InputDecoration(
                  labelText: 'Destination (leave empty to restore to the original location)',
                  hintText: 'Folder ending with a separator, or a full file path',
                ),
                onChanged: (_) => _invalidate(),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: _busy || _done != null ? null : _browse,
              icon: const Icon(Icons.folder_open),
              label: const Text('Browse'),
            ),
          ]),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: _overwrite,
            onChanged: _busy || _done != null
                ? null
                : (v) {
                    _overwrite = v ?? false;
                    _invalidate();
                  },
            title: const Text('Overwrite existing files'),
            subtitle: const Text('The current content of overwritten files is saved as a new version first.'),
          ),
          if (_overwrite && (_plan?.overwritten ?? 0) > 0)
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: scheme.errorContainer, borderRadius: BorderRadius.circular(8)),
              child: Row(children: [
                Icon(Icons.warning_amber, color: scheme.onErrorContainer),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('${_plan!.overwritten} existing file(s) will be replaced.',
                      style: TextStyle(color: scheme.onErrorContainer)),
                ),
              ]),
            ),
          const SizedBox(height: 12),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) Text(_error!, style: TextStyle(color: scheme.error)),
          if (shown != null) ...[
            Text(
              _done != null
                  ? 'Restored: ${shown.created} created, ${shown.overwritten} overwritten, ${shown.identical} identical, '
                      '${shown.conflicts} conflicts, ${shown.errors} errors'
                  : 'Preview: ${shown.created} to create, ${shown.overwritten} to overwrite, ${shown.identical} identical, '
                      '${shown.conflicts} conflicts, ${shown.errors} errors',
              style: theme.textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            _filters(shown),
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 300),
              child: Builder(builder: (context) {
                final visible = _visible(shown);
                return ListView.separated(
                shrinkWrap: true,
                itemCount: visible.length,
                separatorBuilder: (_, _) => const Divider(),
                itemBuilder: (_, i) {
                  final item = visible[i];
                  final color = switch (item.action) {
                    'conflict' || 'error' => scheme.error,
                    'overwrite' => Colors.orange.shade700,
                    'identical' => scheme.outline,
                    _ => Colors.green.shade600,
                  };
                  return ListTile(
                    leading: SizedBox(
                      width: 80,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(item.action.toUpperCase(), style: TextStyle(color: color, fontWeight: FontWeight.w600)),
                          if (item.resolved)
                            Text('RESOLVED', style: TextStyle(color: scheme.primary, fontSize: 11, fontWeight: FontWeight.w600)),
                        ],
                      ),
                    ),
                    title: Text(item.destination), // full path; long paths wrap
                    subtitle: Text([
                      if (item.versionId != null) 'version ${item.versionId}',
                      formatBytes(item.size),
                      if (item.detail != null) item.detail!,
                    ].join(' · ')),
                    trailing: item.versionId == null
                        ? null
                        : Row(mainAxisSize: MainAxisSize.min, children: [
                            IconButton(
                              tooltip: 'Compare: what is on disk now vs what would be restored',
                              icon: const Icon(Icons.compare_arrows),
                              onPressed: () => _compare(item),
                            ),
                            if (_done == null && item.action != 'identical')
                              TextButton.icon(
                                icon: const Icon(Icons.merge_type, size: 18),
                                label: Text(item.resolved ? 'Edit resolution' : 'Resolve'),
                                onPressed: _busy ? null : () => _resolve(item),
                              ),
                          ]),
                  );
                },
              );
              }),
            ),
            if (shown.conflicts > 0 && _done == null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Conflicting files are never replaced silently. Tick "Overwrite" or choose another destination.',
                    style: TextStyle(color: scheme.error)),
              ),
            if (_done != null && _done!.metadataNotRestored.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Not restored: ${_done!.metadataNotRestored.join(', ')}', style: theme.textTheme.bodySmall),
              ),
          ],
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context, _done), child: Text(_done != null ? 'Close' : 'Cancel')),
        if (_done == null) ...[
          OutlinedButton(onPressed: _busy ? null : _preview, child: const Text('Preview')),
          FilledButton.icon(
            onPressed: _busy || _plan == null || _plan!.writes == 0 ? null : _restore,
            icon: const Icon(Icons.restore),
            label: Text(_plan == null ? 'Restore' : 'Restore ${_plan!.writes} file(s)'),
          ),
        ],
      ],
    );
  }

  Widget _row(BuildContext context, String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 140, child: Text(label, style: Theme.of(context).textTheme.labelLarge)),
          Expanded(child: SelectableText(value)),
        ]),
      );
}
