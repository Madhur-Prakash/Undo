// Resolve a restore like a merge conflict: for each difference between the file on disk (left)
// and a stored version (right) choose "Keep disk", "Use version" or "Both", or edit the merged
// result by hand, then save it to the file. Unsaved work can be kept as a draft and resumed.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

const _mono = TextStyle(
  fontFamily: 'Consolas',
  fontFamilyFallback: ['Cascadia Mono', 'DejaVu Sans Mono', 'monospace'],
  fontSize: 12.5,
  height: 1.45,
);

/// Opens the merge editor for [versionId] against the file at [path] (default: the version's
/// file). Returns true when the merged result was written to the file.
Future<bool> showMergeEditor(BuildContext context, {required int versionId, String? path}) async {
  final size = MediaQuery.sizeOf(context);
  final written = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => Dialog(
      insetPadding: EdgeInsets.symmetric(
        horizontal: math.max(16, size.width * 0.04),
        vertical: math.max(16, size.height * 0.04),
      ),
      child: _MergeEditor(versionId: versionId, path: path),
    ),
  );
  return written ?? false;
}

enum _Choice { disk, version, both }

class _MergeEditor extends ConsumerStatefulWidget {
  const _MergeEditor({required this.versionId, this.path});
  final int versionId;
  final String? path;

  @override
  ConsumerState<_MergeEditor> createState() => _MergeEditorState();
}

class _MergeEditorState extends ConsumerState<_MergeEditor> {
  MergeSource? _source;
  Object? _loadError;
  final _result = TextEditingController();
  final Map<int, _Choice> _choices = {};
  bool _edited = false; // the result was changed by hand
  bool _dirty = false; // changes not saved to the file or a draft
  bool _busy = false;
  bool _applyingChoice = false;
  String _lastText = '';
  String? _savedNote;

  @override
  void initState() {
    super.initState();
    _result.addListener(() {
      // The controller also notifies on cursor moves: only real text changes count as edits.
      if (_applyingChoice || _result.text == _lastText) return;
      _lastText = _result.text;
      if (!_edited || !_dirty) {
        setState(() {
          _edited = true;
          _dirty = true;
        });
      }
    });
    _load();
  }

  @override
  void dispose() {
    _result.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final source = await ref.read(apiProvider).mergeSource(widget.versionId, path: widget.path);
      if (!mounted) return;
      setState(() => _source = source);
      for (var i = 0; i < source.hunks.length; i++) {
        _choices[i] = _Choice.disk;
      }
      _setResult(_compose());
      _dirty = false;
      final draft = source.draft;
      if (draft != null && draft.versionId == widget.versionId) {
        WidgetsBinding.instance.addPostFrameCallback((_) => _offerResume(draft));
      }
    } catch (e) {
      if (mounted) setState(() => _loadError = e);
    }
  }

  Future<void> _offerResume(MergeDraft draft) async {
    final resume = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Resume saved progress?'),
        content: Text('You saved an unfinished merge of this file on ${formatDateTime(draft.updatedAt)}.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Start over')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Resume')),
        ],
      ),
    );
    if (resume != true || !mounted) return;
    setState(() {
      for (final e in draft.choices.entries) {
        final i = int.tryParse(e.key);
        final c = _Choice.values.where((c) => c.name == e.value).firstOrNull;
        if (i != null && c != null) _choices[i] = c;
      }
      _edited = draft.edited;
    });
    _setResult(draft.text);
    _dirty = false;
    _savedNote = 'Resumed progress saved ${formatDateTime(draft.updatedAt)}';
  }

  void _setResult(String text) {
    _applyingChoice = true;
    _result.text = text;
    _lastText = text;
    _applyingChoice = false;
  }

  /// The merged text from the per-difference choices, built from the file's lines.
  String _compose() {
    final source = _source!;
    final a = source.currentLines;
    final out = <String>[];
    var pos = 0;
    for (var h = 0; h < source.hunks.length; h++) {
      final hunk = source.hunks[h];
      final start = math.max(0, hunk.aStart - 1);
      while (pos < start && pos < a.length) {
        out.add(a[pos++]);
      }
      final choice = _choices[h] ?? _Choice.disk;
      final pendingA = <String>[];
      final pendingB = <String>[];
      void flush() {
        if (choice != _Choice.version) out.addAll(pendingA);
        if (choice != _Choice.disk) out.addAll(pendingB);
        pendingA.clear();
        pendingB.clear();
      }

      for (final r in hunk.rows) {
        if (r.kind == 'equal') {
          flush();
          out.add(r.aText ?? '');
          continue;
        }
        if (r.aText != null) pendingA.add(r.aText!);
        if (r.bText != null) pendingB.add(r.bText!);
      }
      flush();
      pos = start + hunk.aCount;
    }
    while (pos < a.length) {
      out.add(a[pos++]);
    }
    return out.join('\n');
  }

  Future<void> _choose(int hunk, _Choice choice) => _chooseMany({hunk: choice});

  Future<void> _chooseAll(_Choice choice) =>
      _chooseMany({for (var i = 0; i < (_source?.hunks.length ?? 0); i++) i: choice});

  Future<void> _chooseMany(Map<int, _Choice> picks) async {
    if (_edited) {
      final ok = await confirmDialog(
        context,
        title: 'Replace your edits?',
        message: 'You edited the result by hand. Applying a choice rebuilds the result from the '
            'choices and replaces those edits.',
        confirm: 'Replace edits',
        destructive: true,
      );
      if (!ok) return;
    }
    setState(() {
      _choices.addAll(picks);
      _edited = false;
      _dirty = true;
    });
    _setResult(_compose());
  }

  Future<void> _saveDraft() async {
    final source = _source;
    if (source == null) return;
    setState(() => _busy = true);
    final draft = await runAction(
      context,
      () => ref.read(apiProvider).saveMergeDraft(
            source.path,
            versionId: widget.versionId,
            text: _result.text,
            choices: {for (final e in _choices.entries) '${e.key}': e.value.name},
            edited: _edited,
          ),
      success: 'Progress saved. Open this file\'s merge again to resume.',
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (draft != null) {
        _dirty = false;
        _savedNote = 'Progress saved ${formatDateTime(draft.updatedAt)}';
      }
    });
  }

  Future<void> _write() async {
    final source = _source;
    if (source == null) return;
    final ok = await confirmDialog(
      context,
      title: 'Save the merged result to the file?',
      message: '${source.path}\n\n'
          '${source.exists ? 'The file\'s current content is saved as a version first, so this can be undone.' : 'The file is created.'}',
      confirm: 'Save to file',
    );
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    final r = await runAction(
      context,
      () => ref.read(apiProvider).mergeWrite(
            source.path,
            _result.text,
            versionId: widget.versionId,
            expectedHash: source.currentHash,
          ),
      success: 'Merged result saved to ${source.path}',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (r != null) {
      refreshAll(ref);
      Navigator.pop(context, true);
    }
  }

  /// Leaving with unsaved changes asks: save progress, discard, or keep editing.
  Future<void> _close() async {
    if (!_dirty) {
      Navigator.pop(context, false);
      return;
    }
    final choice = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Unsaved changes'),
        content: const Text('Save your progress to resume this merge later, or discard the changes?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, 'keep'), child: const Text('Keep editing')),
          TextButton(onPressed: () => Navigator.pop(ctx, 'discard'), child: const Text('Discard')),
          FilledButton(onPressed: () => Navigator.pop(ctx, 'save'), child: const Text('Save progress')),
        ],
      ),
    );
    if (!mounted) return;
    if (choice == 'save') {
      await _saveDraft();
      if (mounted && !_dirty) Navigator.pop(context, false);
    } else if (choice == 'discard') {
      Navigator.pop(context, false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final source = _source;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _close();
      },
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const Icon(Icons.merge_type),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                source == null ? 'Resolve' : 'Resolve: ${source.path}',
                style: theme.textTheme.titleLarge,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(tooltip: 'Close', onPressed: _busy ? null : _close, icon: const Icon(Icons.close)),
          ]),
          const SizedBox(height: 8),
          if (_loadError != null)
            Expanded(child: ErrorView(message: _loadError.toString()))
          else if (source == null)
            const Expanded(child: Center(child: CircularProgressIndicator()))
          else if (source.identical)
            const Expanded(
              child: EmptyState(
                icon: Icons.check_circle_outline,
                title: 'Identical: nothing to resolve',
                message: 'The file on disk already has exactly this version\'s content.',
              ),
            )
          else ...[
            Text(
              'Left: the file on disk now${source.exists ? '' : ' (does not exist yet)'} · '
              'Right: version ${source.version.id} from ${formatDateTime(source.version.timestamp)}. '
              'Choose for each difference, or edit the result below.',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 8),
            Row(children: [
              Text('${source.hunks.length} difference(s)', style: theme.textTheme.titleSmall),
              const Spacer(),
              TextButton(onPressed: _busy ? null : () => _chooseAll(_Choice.disk), child: const Text('Keep disk for all')),
              TextButton(
                  onPressed: _busy ? null : () => _chooseAll(_Choice.version), child: const Text('Use version for all')),
            ]),
            Expanded(
              flex: 3,
              child: Container(
                decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant)),
                child: ListView.builder(
                  itemCount: source.hunks.length,
                  itemBuilder: (_, i) => _HunkCard(
                    index: i,
                    hunk: source.hunks[i],
                    choice: _choices[i] ?? _Choice.disk,
                    onChoose: _busy ? null : (c) => _choose(i, c),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Text('Result', style: theme.textTheme.titleSmall),
              const SizedBox(width: 8),
              Text(
                _edited ? '(edited by hand)' : '(from your choices; you can edit it)',
                style: theme.textTheme.bodySmall,
              ),
              const Spacer(),
              if (_dirty)
                Text('Unsaved changes', style: TextStyle(color: scheme.error))
              else if (_savedNote != null)
                Text(_savedNote!, style: theme.textTheme.bodySmall),
            ]),
            const SizedBox(height: 4),
            Expanded(
              flex: 2,
              child: TextField(
                controller: _result,
                enabled: !_busy,
                expands: true,
                maxLines: null,
                style: _mono,
                textAlignVertical: TextAlignVertical.top,
                decoration: const InputDecoration(border: OutlineInputBorder(), contentPadding: EdgeInsets.all(10)),
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              if (_busy) const SizedBox(width: 160, child: LinearProgressIndicator()),
              const Spacer(),
              TextButton(onPressed: _busy ? null : _close, child: const Text('Close')),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _busy ? null : _saveDraft,
                icon: const Icon(Icons.save_outlined),
                label: const Text('Save progress'),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: _busy ? null : _write,
                icon: const Icon(Icons.restore),
                label: const Text('Save to file'),
              ),
            ]),
          ],
        ]),
      ),
    );
  }
}

class _HunkCard extends StatelessWidget {
  const _HunkCard({required this.index, required this.hunk, required this.choice, required this.onChoose});
  final int index;
  final DiffHunk hunk;
  final _Choice choice;
  final ValueChanged<_Choice>? onChoose;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final del = Colors.red.withValues(alpha: 0.13);
    final ins = Colors.green.withValues(alpha: 0.13);
    final empty = scheme.onSurface.withValues(alpha: 0.035);
    final dim = scheme.onSurfaceVariant.withValues(alpha: 0.7);
    Widget cell(int? no, String? text, Color? bg) => Expanded(
          child: Container(
            color: text == null ? empty : bg,
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: 44,
                child: Text(no?.toString() ?? '', textAlign: TextAlign.right, style: _mono.copyWith(color: dim)),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text((text ?? '').replaceAll('\t', '    '), style: _mono)),
            ]),
          ),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        color: scheme.primaryContainer.withValues(alpha: 0.45),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        child: Row(children: [
          Text('Difference ${index + 1}  ·  ${hunk.header}', style: _mono),
          const Spacer(),
          SegmentedButton<_Choice>(
            showSelectedIcon: false,
            style: const ButtonStyle(visualDensity: VisualDensity.compact),
            segments: const [
              ButtonSegment(value: _Choice.disk, label: Text('Keep disk')),
              ButtonSegment(value: _Choice.version, label: Text('Use version')),
              ButtonSegment(value: _Choice.both, label: Text('Both')),
            ],
            selected: {choice},
            onSelectionChanged: onChoose == null ? null : (s) => onChoose!(s.first),
          ),
        ]),
      ),
      for (final r in hunk.rows)
        IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            cell(r.aNo, r.aText, r.kind == 'equal' ? null : del),
            Container(width: 1, color: scheme.outlineVariant),
            cell(r.bNo, r.bText, r.kind == 'equal' ? null : ins),
          ]),
        ),
      const SizedBox(height: 6),
    ]);
  }
}
