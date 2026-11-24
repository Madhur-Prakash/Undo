// Version details: timestamp, size, hash, compression; restore, compare and preview actions.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../restore/restore_dialog.dart';

Future<void> showVersionDetails(BuildContext context, int versionId) =>
    showDialog<void>(context: context, builder: (_) => VersionDetailsDialog(versionId: versionId));

class VersionDetailsDialog extends ConsumerWidget {
  const VersionDetailsDialog({super.key, required this.versionId});
  final int versionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(versionDetailProvider(versionId));
    return AlertDialog(
      title: Text('Version $versionId'),
      content: SizedBox(
        width: 640,
        child: AsyncView<VersionDetail>(
          value: detail,
          onRetry: () => ref.invalidate(versionDetailProvider(versionId)),
          builder: (d) => _DetailBody(detail: d),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
        ...detail.maybeWhen(
          data: (d) => [
            if (d.version.hasContent && d.isText)
              OutlinedButton.icon(
                onPressed: () => showPreview(context, ref, d.version),
                icon: const Icon(Icons.visibility_outlined),
                label: const Text('Preview'),
              ),
            if (d.version.hasContent && d.previousVersionId != null)
              OutlinedButton.icon(
                onPressed: () => showDiff(context, ref, d.previousVersionId!, d.version.id),
                icon: const Icon(Icons.compare_arrows),
                label: const Text('Compare with previous'),
              ),
            if (d.version.hasContent)
              FilledButton.icon(
                onPressed: () async {
                  final api = ref.read(apiProvider);
                  final res = await showRestoreDialog(
                    context,
                    title: 'Restore version ${d.version.id}',
                    source: '${d.version.relativePath} · ${formatDateTime(d.version.timestamp)} · ${formatBytes(d.version.fileSize)}',
                    originalLocation: d.file.absolutePath,
                    run: (dest, overwrite, dry) =>
                        api.restoreVersion(d.version.id, destination: dest, overwrite: overwrite, dryRun: dry),
                  );
                  if (res != null) refreshAll(ref);
                },
                icon: const Icon(Icons.restore),
                label: const Text('Restore'),
              ),
          ],
          orElse: () => <Widget>[],
        ),
      ],
    );
  }
}

class _DetailBody extends StatelessWidget {
  const _DetailBody({required this.detail});
  final VersionDetail detail;

  @override
  Widget build(BuildContext context) {
    final v = detail.version;
    final b = detail.blob;
    final rows = <(String, String)>[
      ('File', v.absolutePath),
      ('Operation', v.operation),
      ('Timestamp', formatDateTime(v.timestamp)),
      ('Size', v.hasContent ? formatBytes(v.fileSize) : '— (deletion marker)'),
      ('Hash (BLAKE3)', v.blobHash ?? '—'),
      ('Previous version', detail.previousVersionId?.toString() ?? '—'),
      ('Next version', detail.nextVersionId?.toString() ?? '—'),
      if (v.metadata['from_path'] != null) ('Moved from', v.metadata['from_path'].toString()),
      if (b != null) ...[
        ('Storage', '${b.storageKind}${b.chunkCount > 0 ? ' (${b.chunkCount} chunks)' : ''}'),
        ('Compression', '${b.compressionAlgorithm}${b.compressionLevel != null ? ' level ${b.compressionLevel}' : ''}'),
        ('Stored size', '${formatBytes(b.compressedSize)} of ${formatBytes(b.originalSize)}'),
        ('Integrity', '${b.status}${b.verifiedAt != null ? ' · verified ${formatRelative(b.verifiedAt)}' : ''}'),
        ('Shared by', '${b.referenceCount} version(s)/snapshot(s)'),
      ],
    ];
    return Column(mainAxisSize: MainAxisSize.min, children: [
      for (final (label, value) in rows)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 150, child: Text(label, style: Theme.of(context).textTheme.labelLarge)),
            Expanded(child: SelectableText(value)),
            if (label == 'Hash (BLAKE3)' && v.blobHash != null)
              IconButton(
                tooltip: 'Copy hash',
                iconSize: 16,
                onPressed: () => Clipboard.setData(ClipboardData(text: v.blobHash!)),
                icon: const Icon(Icons.copy),
              ),
          ]),
        ),
    ]);
  }
}

Future<void> showDiff(BuildContext context, WidgetRef ref, int a, int b) async {
  final api = ref.read(apiProvider);
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('Compare v$a → v$b'),
      content: SizedBox(
        width: 900,
        height: 560,
        child: FutureBuilder<VersionDiff>(
          future: api.diff(a, b),
          builder: (ctx, snap) {
            if (snap.hasError) return ErrorView(message: snap.error.toString());
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final d = snap.data!;
            if (d.diff == null || d.diff!.isEmpty) {
              return EmptyState(icon: Icons.compare_arrows, title: d.note ?? 'No textual differences',
                  message: 'Size change: ${d.sizeDelta >= 0 ? '+' : ''}${d.sizeDelta} bytes');
            }
            final scheme = Theme.of(ctx).colorScheme;
            final lines = d.diff!.split('\n');
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (d.truncated) Text('Diff truncated', style: TextStyle(color: scheme.error)),
              Expanded(
                child: Container(
                  color: scheme.surfaceContainerLowest,
                  child: ListView.builder(
                    itemCount: lines.length,
                    itemBuilder: (_, i) {
                      final line = lines[i];
                      Color? bg;
                      if (line.startsWith('+') && !line.startsWith('+++')) bg = Colors.green.withValues(alpha: 0.15);
                      if (line.startsWith('-') && !line.startsWith('---')) bg = Colors.red.withValues(alpha: 0.15);
                      if (line.startsWith('@@')) bg = scheme.primaryContainer.withValues(alpha: 0.5);
                      return Container(
                        color: bg,
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        child: Text(line, style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5)),
                      );
                    },
                  ),
                ),
              ),
            ]);
          },
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))],
    ),
  );
}

Future<void> showPreview(BuildContext context, WidgetRef ref, VersionInfo v) async {
  final api = ref.read(apiProvider);
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${v.name} · version ${v.id}'),
      content: SizedBox(
        width: 900,
        height: 560,
        child: FutureBuilder<VersionContent>(
          future: api.preview(v.id),
          builder: (ctx, snap) {
            if (snap.hasError) return ErrorView(message: snap.error.toString());
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final c = snap.data!;
            if (!c.isText) return EmptyState(icon: Icons.insert_drive_file_outlined, title: 'Binary content (${formatBytes(c.size)})');
            return Container(
              color: Theme.of(ctx).colorScheme.surfaceContainerLowest,
              padding: const EdgeInsets.all(8),
              child: SingleChildScrollView(
                child: SelectableText(
                  '${c.text}${c.truncated ? '\n\n[… truncated …]' : ''}',
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5),
                ),
              ),
            );
          },
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))],
    ),
  );
}
