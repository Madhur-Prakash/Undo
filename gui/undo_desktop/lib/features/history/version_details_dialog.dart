// Version details: timestamp, size, hash, compression; restore, compare and preview actions.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../restore/merge_editor.dart';
import '../restore/restore_dialog.dart';
import 'diff_view.dart';

Future<void> showVersionDetails(BuildContext context, int versionId) =>
    showDialog<void>(
      context: context,
      builder: (_) => VersionDetailsDialog(versionId: versionId),
    );

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
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
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
                onPressed: () =>
                    showDiff(context, ref, d.previousVersionId!, d.version.id),
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
                    source:
                        '${d.version.relativePath} · ${formatDateTime(d.version.timestamp)} · ${formatBytes(d.version.fileSize)}',
                    originalLocation: d.file.absolutePath,
                    run: (dest, overwrite, dry) => api.restoreVersion(
                      d.version.id,
                      destination: dest,
                      overwrite: overwrite,
                      dryRun: dry,
                    ),
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
      if (v.metadata['from_path'] != null)
        ('Moved from', v.metadata['from_path'].toString()),
      if (b != null) ...[
        (
          'Storage',
          '${b.storageKind}${b.chunkCount > 0 ? ' (${b.chunkCount} chunks)' : ''}',
        ),
        (
          'Compression',
          '${b.compressionAlgorithm}${b.compressionLevel != null ? ' level ${b.compressionLevel}' : ''}',
        ),
        (
          'Stored size',
          '${formatBytes(b.compressedSize)} of ${formatBytes(b.originalSize)}',
        ),
        (
          'Integrity',
          '${b.status}${b.verifiedAt != null ? ' · verified ${formatRelative(b.verifiedAt)}' : ''}',
        ),
        ('Shared by', '${b.referenceCount} version(s)/snapshot(s)'),
      ],
    ];
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final (label, value) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 150,
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                ),
                Expanded(child: SelectableText(value)),
                if (label == 'Hash (BLAKE3)' && v.blobHash != null)
                  IconButton(
                    tooltip: 'Copy hash',
                    iconSize: 16,
                    onPressed: () =>
                        Clipboard.setData(ClipboardData(text: v.blobHash!)),
                    icon: const Icon(Icons.copy),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Compare two versions side by side. "Edit and merge" merges version [b] into the file on disk.
Future<void> showDiff(BuildContext context, WidgetRef ref, int a, int b) => showDiffDialog(
      context,
      title: 'Compare v$a → v$b',
      future: ref.read(apiProvider).diff(a, b),
      onEdit: () => showMergeEditor(context, versionId: b),
    );

Future<void> showPreview(
  BuildContext context,
  WidgetRef ref,
  VersionInfo v,
) async {
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
            if (!snap.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            final c = snap.data!;
            if (!c.isText) {
              return EmptyState(
                icon: Icons.insert_drive_file_outlined,
                title: 'Binary content (${formatBytes(c.size)})',
              );
            }
            return Container(
              color: Theme.of(ctx).colorScheme.surfaceContainerLowest,
              padding: const EdgeInsets.all(8),
              child: SingleChildScrollView(
                child: SelectableText(
                  '${c.text}${c.truncated ? '\n\n[… truncated …]' : ''}',
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                  ),
                ),
              ),
            );
          },
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Close'),
        ),
      ],
    ),
  );
}
