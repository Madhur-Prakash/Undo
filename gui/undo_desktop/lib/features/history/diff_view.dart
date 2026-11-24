// Side-by-side comparison of two versions, like an editor's git diff: the old version on the
// left, the new one on the right, changed characters highlighted, with an inline mode.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/models/models.dart';
import '../../core/util/format.dart';

enum DiffMode { sideBySide, inline }

const _mono = TextStyle(
  fontFamily: 'Consolas',
  fontFamilyFallback: ['Cascadia Mono', 'DejaVu Sans Mono', 'monospace'],
  fontSize: 12.5,
  height: 1.45,
);

class _Palette {
  _Palette(ColorScheme scheme)
    : delete = Colors.red.withValues(alpha: 0.13),
      deleteStrong = Colors.red.withValues(alpha: 0.38),
      insert = Colors.green.withValues(alpha: 0.13),
      insertStrong = Colors.green.withValues(alpha: 0.38),
      empty = scheme.onSurface.withValues(alpha: 0.035),
      hunk = scheme.primaryContainer.withValues(alpha: 0.45),
      lineNo = scheme.onSurfaceVariant.withValues(alpha: 0.7);
  final Color delete, deleteStrong, insert, insertStrong, empty, hunk, lineNo;
}

/// The whole comparison: header with stats, mode switch, then the rows.
class DiffView extends StatefulWidget {
  const DiffView({super.key, required this.diff});
  final VersionDiff diff;

  @override
  State<DiffView> createState() => _DiffViewState();
}

class _DiffViewState extends State<DiffView> {
  DiffMode mode = DiffMode.sideBySide;

  @override
  Widget build(BuildContext context) {
    final d = widget.diff;
    final scheme = Theme.of(context).colorScheme;
    final p = _Palette(scheme);
    final items = <Object>[
      for (final h in d.hunks) ...[h, ...h.rows],
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            _Stat(text: '+${d.added}', color: Colors.green),
            const SizedBox(width: 6),
            _Stat(text: '−${d.removed}', color: Colors.red),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                [
                  'size ${d.sizeDelta >= 0 ? '+' : ''}${d.sizeDelta} bytes',
                  if (d.note != null) d.note!,
                  if (d.truncated) 'diff truncated',
                ].join(' · '),
                style: Theme.of(context).textTheme.bodySmall,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            SegmentedButton<DiffMode>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(
                  value: DiffMode.sideBySide,
                  icon: Icon(Icons.view_column_outlined),
                  label: Text('Side by side'),
                ),
                ButtonSegment(
                  value: DiffMode.inline,
                  icon: Icon(Icons.view_agenda_outlined),
                  label: Text('Inline'),
                ),
              ],
              selected: {mode},
              onSelectionChanged: (s) => setState(() => mode = s.first),
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (mode == DiffMode.sideBySide)
          Row(
            children: [
              Expanded(
                child: _FileHeader(version: d.a, color: Colors.red),
              ),
              const SizedBox(width: 1),
              Expanded(
                child: _FileHeader(version: d.b, color: Colors.green),
              ),
            ],
          ),
        Expanded(
          child: Container(
            decoration: BoxDecoration(
              color: scheme.surfaceContainerLowest,
              border: Border.all(color: scheme.outlineVariant),
            ),
            child: SelectionArea(
              child: mode == DiffMode.sideBySide
                  ? ListView.builder(
                      itemCount: items.length,
                      itemBuilder: (_, i) =>
                          _sideBySideItem(items[i], p, scheme),
                    )
                  : _inlineList(items, p),
            ),
          ),
        ),
      ],
    );
  }

  Widget _sideBySideItem(Object item, _Palette p, ColorScheme scheme) {
    if (item is DiffHunk) return _HunkHeader(text: item.header, color: p.hunk);
    final r = item as DiffRow;
    final changed = r.kind != 'equal';
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: _Cell(
              no: r.aNo,
              text: r.aText,
              spans: r.kind == 'change' ? r.aSpans : const [],
              background: r.aText == null
                  ? p.empty
                  : (changed ? p.delete : null),
              strong: p.deleteStrong,
              lineNo: p.lineNo,
            ),
          ),
          Container(width: 1, color: scheme.outlineVariant),
          Expanded(
            child: _Cell(
              no: r.bNo,
              text: r.bText,
              spans: r.kind == 'change' ? r.bSpans : const [],
              background: r.bText == null
                  ? p.empty
                  : (changed ? p.insert : null),
              strong: p.insertStrong,
              lineNo: p.lineNo,
            ),
          ),
        ],
      ),
    );
  }

  Widget _inlineList(List<Object> items, _Palette p) {
    // Unified view: a changed line becomes "- old" then "+ new".
    final lines = <Widget Function()>[];
    for (final item in items) {
      if (item is DiffHunk) {
        lines.add(() => _HunkHeader(text: item.header, color: p.hunk));
        continue;
      }
      final r = item as DiffRow;
      if (r.kind == 'equal') {
        lines.add(
          () => _InlineLine(
            aNo: r.aNo,
            bNo: r.bNo,
            marker: ' ',
            text: r.aText ?? '',
            lineNo: p.lineNo,
          ),
        );
        continue;
      }
      if (r.aText != null) {
        lines.add(
          () => _InlineLine(
            aNo: r.aNo,
            marker: '-',
            text: r.aText!,
            spans: r.aSpans,
            background: p.delete,
            strong: p.deleteStrong,
            lineNo: p.lineNo,
          ),
        );
      }
      if (r.bText != null) {
        lines.add(
          () => _InlineLine(
            bNo: r.bNo,
            marker: '+',
            text: r.bText!,
            spans: r.bSpans,
            background: p.insert,
            strong: p.insertStrong,
            lineNo: p.lineNo,
          ),
        );
      }
    }
    return ListView.builder(
      itemCount: lines.length,
      itemBuilder: (_, i) => lines[i](),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.text, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.15),
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(
      text,
      style: TextStyle(color: color, fontWeight: FontWeight.w600),
    ),
  );
}

class _FileHeader extends StatelessWidget {
  const _FileHeader({required this.version, required this.color});
  final VersionInfo version;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    color: color.withValues(alpha: 0.10),
    child: Text(
      'v${version.id} · ${version.relativePath} · ${formatDateTime(version.timestamp)}',
      style: Theme.of(context).textTheme.labelLarge,
      overflow: TextOverflow.ellipsis,
    ),
  );
}

class _HunkHeader extends StatelessWidget {
  const _HunkHeader({required this.text, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    color: color,
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
    child: Text(
      text,
      style: _mono.copyWith(
        color: Theme.of(context).colorScheme.onPrimaryContainer,
      ),
    ),
  );
}

String _tabs(String s) => s.replaceAll('	', '    ');

/// Text with the changed character ranges highlighted. Spans index the original text, so tabs
/// are expanded per piece, after splitting.
TextSpan _highlighted(String text, List<DiffSpan> spans, Color strong) {
  if (spans.isEmpty) return TextSpan(text: _tabs(text));
  final children = <TextSpan>[];
  var pos = 0;
  for (final (start, end) in spans) {
    final s = math.min(math.max(start, pos), text.length);
    final e = math.min(math.max(end, s), text.length);
    if (s > pos) children.add(TextSpan(text: _tabs(text.substring(pos, s))));
    if (e > s) {
      children.add(
        TextSpan(
          text: _tabs(text.substring(s, e)),
          style: TextStyle(backgroundColor: strong),
        ),
      );
    }
    pos = e;
  }
  if (pos < text.length) {
    children.add(TextSpan(text: _tabs(text.substring(pos))));
  }
  return TextSpan(children: children);
}

class _Cell extends StatelessWidget {
  const _Cell({
    required this.no,
    required this.text,
    required this.spans,
    required this.background,
    required this.strong,
    required this.lineNo,
  });
  final int? no;
  final String? text;
  final List<DiffSpan> spans;
  final Color? background;
  final Color strong;
  final Color lineNo;

  @override
  Widget build(BuildContext context) => Container(
    color: background,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 52,
          child: Padding(
            padding: const EdgeInsets.only(right: 10),
            child: Text(
              no?.toString() ?? '',
              textAlign: TextAlign.right,
              style: _mono.copyWith(color: lineNo),
            ),
          ),
        ),
        Expanded(
          child: Text.rich(
            _highlighted((text ?? '').replaceAll('\t', '    '), spans, strong),
            style: _mono,
          ),
        ),
      ],
    ),
  );
}

class _InlineLine extends StatelessWidget {
  const _InlineLine({
    this.aNo,
    this.bNo,
    required this.marker,
    required this.text,
    this.spans = const [],
    this.background,
    this.strong = Colors.transparent,
    required this.lineNo,
  });
  final int? aNo;
  final int? bNo;
  final String marker;
  final String text;
  final List<DiffSpan> spans;
  final Color? background;
  final Color strong;
  final Color lineNo;

  @override
  Widget build(BuildContext context) => Container(
    color: background,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final n in [aNo, bNo])
          SizedBox(
            width: 48,
            child: Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                n?.toString() ?? '',
                textAlign: TextAlign.right,
                style: _mono.copyWith(color: lineNo),
              ),
            ),
          ),
        SizedBox(
          width: 18,
          child: Text(marker, style: _mono.copyWith(color: lineNo)),
        ),
        Expanded(
          child: Text.rich(
            _highlighted(text.replaceAll('\t', '    '), spans, strong),
            style: _mono,
          ),
        ),
      ],
    ),
  );
}
