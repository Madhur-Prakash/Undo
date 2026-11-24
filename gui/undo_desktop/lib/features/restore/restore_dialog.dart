// Restore confirmation: always preview (dry run) first; overwriting must be ticked explicitly.
import '../../shared/widgets.dart';

import 'package:flutter/material.dart';

import '../../core/models/models.dart';
import '../../core/util/format.dart';

typedef RestoreRunner = Future<RestoreResult> Function(
  String? destination,
  bool overwrite,
  bool dryRun,
);

Future<RestoreResult?> showRestoreDialog(
  BuildContext context, {
  required String title,
  required String source,
  required String originalLocation,
  required RestoreRunner run,
}) {
  return showDialog<RestoreResult>(
    context: context,
    builder: (_) => RestoreDialog(
      title: title,
      source: source,
      originalLocation: originalLocation,
      run: run,
    ),
  );
}

class RestoreDialog extends StatefulWidget {
  const RestoreDialog({
    super.key,
    required this.title,
    required this.source,
    required this.originalLocation,
    required this.run,
  });
  final String title;
  final String source;
  final String originalLocation;
  final RestoreRunner run;

  @override
  State<RestoreDialog> createState() => _RestoreDialogState();
}

class _RestoreDialogState extends State<RestoreDialog> {
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

  String? get _destination =>
      _dest.text.trim().isEmpty ? null : _dest.text.trim();

  void _invalidate() => setState(() {
    _plan = null;
    _done = null;
  });

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
      _dest.text = dir.endsWith('/') || dir.endsWith('\\')
          ? dir
          : '$dir${dir.contains('\\') ? '\\' : '/'}';
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
        width: 760,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row(context, 'Source', widget.source),
            _row(context, 'Original location', widget.originalLocation),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _dest,
                    enabled: !_busy && _done == null,
                    decoration: const InputDecoration(
                      labelText: 'Destination (leave empty to restore to the original location)',
                      hintText:
                          'Folder ending with a separator, or a full file path',
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
              ],
            ),
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
              subtitle: const Text(
                'The current content of overwritten files is saved as a new version first.',
              ),
            ),
            if (_overwrite && (_plan?.overwritten ?? 0) > 0)
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: scheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    Icon(Icons.warning_amber, color: scheme.onErrorContainer),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${_plan!.overwritten} existing file(s) will be replaced.',
                        style: TextStyle(color: scheme.onErrorContainer),
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            if (_busy) const LinearProgressIndicator(),
            if (_error != null)
              Text(_error!, style: TextStyle(color: scheme.error)),
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
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 260),
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: shown.items.length,
                  separatorBuilder: (_, _) => const Divider(),
                  itemBuilder: (_, i) {
                    final item = shown.items[i];
                    final color = switch (item.action) {
                      'conflict' || 'error' => scheme.error,
                      'overwrite' => Colors.orange.shade700,
                      'identical' => scheme.outline,
                      _ => Colors.green.shade600,
                    };
                    return ListTile(
                      leading: SizedBox(
                        width: 80,
                        child: Text(
                          item.action.toUpperCase(),
                          style: TextStyle(
                            color: color,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      title: Text(
                        item.destination,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        [
                          if (item.versionId != null)
                            'version ${item.versionId}',
                          formatBytes(item.size),
                          if (item.detail != null) item.detail!,
                        ].join(' · '),
                      ),
                    );
                  },
                ),
              ),
              if (shown.conflicts > 0 && _done == null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Conflicting files are never replaced silently. Tick "Overwrite" or choose another destination.',
                    style: TextStyle(color: scheme.error),
                  ),
                ),
              if (_done != null && _done!.metadataNotRestored.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Not restored: ${_done!.metadataNotRestored.join(', ')}',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context, _done),
          child: Text(_done != null ? 'Close' : 'Cancel'),
        ),
        if (_done == null) ...[
          OutlinedButton(
            onPressed: _busy ? null : _preview,
            child: const Text('Preview'),
          ),
          FilledButton.icon(
            onPressed: _busy || _plan == null || _plan!.writes == 0
                ? null
                : _restore,
            icon: const Icon(Icons.restore),
            label: Text(
              _plan == null ? 'Restore' : 'Restore ${_plan!.writes} file(s)',
            ),
          ),
        ],
      ],
    );
  }

  Widget _row(BuildContext context, String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 140,
          child: Text(label, style: Theme.of(context).textTheme.labelLarge),
        ),
        Expanded(child: SelectableText(value)),
      ],
    ),
  );
}
