// One file's versions, path history and restore/recover actions.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../history/forget_dialog.dart';
import '../history/diff_view.dart';
import '../history/version_details_dialog.dart';
import '../restore/merge_editor.dart';
import '../restore/restore_dialog.dart';

class FileHistoryPage extends ConsumerWidget {
  const FileHistoryPage({super.key, required this.fileId});
  final int fileId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final history = ref.watch(fileHistoryProvider(fileId));
    return AsyncView<FileHistory>(
      value: history,
      onRetry: () => ref.invalidate(fileHistoryProvider(fileId)),
      builder: (h) => _body(context, ref, h),
    );
  }

  Widget _body(BuildContext context, WidgetRef ref, FileHistory h) {
    final f = h.file;
    final api = ref.read(apiProvider);
    final former = h.paths.length > 1 ? h.paths.sublist(0, h.paths.length - 1) : <PathHistoryInfo>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: f.name,
        subtitle: f.absolutePath,
        actions: [
          OutlinedButton.icon(onPressed: () => context.go('/files'), icon: const Icon(Icons.arrow_back), label: const Text('Files')),
          if (f.isDeleted)
            FilledButton.icon(
              icon: const Icon(Icons.restore_from_trash),
              label: const Text('Recover deleted file'),
              onPressed: () async {
                final res = await showRestoreDialog(
                  context,
                  title: 'Recover ${f.name}',
                  source: 'Latest stored content of ${f.relativePath}',
                  originalLocation: f.absolutePath,
                  run: (dest, overwrite, dry) => api.recover(f.absolutePath, destination: dest, overwrite: overwrite, dryRun: dry),
                );
                if (res != null) refreshAll(ref);
              },
            ),
          OutlinedButton.icon(
            icon: const Icon(Icons.delete_sweep_outlined),
            label: const Text('Delete history'),
            onPressed: () async {
              final r = await showForgetDialog(context, path: f.absolutePath);
              if (r == null || !context.mounted) return;
              showMessage(context, 'Removed ${r.versionsRemoved} version(s). ${r.note ?? ''}'.trim());
              refreshAll(ref);
              if (r.filesRemoved > 0) {
                context.go('/files'); // the file has no history left
              } else {
                ref.invalidate(fileHistoryProvider(fileId));
              }
            },
          ),
          IconButton(tooltip: 'Refresh', onPressed: () => ref.invalidate(fileHistoryProvider(fileId)), icon: const Icon(Icons.refresh)),
        ],
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Wrap(spacing: 24, runSpacing: 8, children: [
          _fact(context, 'State', f.isDeleted ? 'Deleted ${formatDateTime(f.deletedAt)}' : 'Live'),
          _fact(context, 'Size', formatBytes(f.size)),
          _fact(context, 'Versions', '${h.versions.length}'),
          _fact(context, 'Tracked since', formatDateTime(f.createdAt)),
          if (former.isNotEmpty) _fact(context, 'Former paths', former.map((p) => p.relativePath).join(', ')),
        ]),
      ),
      const SizedBox(height: 12),
      const Divider(),
      Expanded(
        child: ListView.separated(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          itemCount: h.versions.length,
          separatorBuilder: (_, _) => const Divider(),
          itemBuilder: (_, i) {
            final v = h.versions[i];
            final older = h.versions.skip(i + 1).where((x) => x.hasContent).firstOrNull;
            return ListTile(
              leading: SizedBox(width: 72, child: Align(alignment: Alignment.centerLeft, child: OperationChip(v.operation))),
              title: Text('Version ${v.id} · ${formatDateTime(v.timestamp)}'),
              subtitle: Text([
                if (v.hasContent) formatBytes(v.fileSize) else 'deletion recorded',
                if (v.hasContent) shortHash(v.blobHash),
                if (v.metadata['from_path'] != null) 'from ${v.metadata['from_path']}',
                v.relativePath,
              ].join(' · ')),
              onTap: () => showVersionDetails(context, v.id),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                if (v.hasContent && !f.isDeleted)
                  IconButton(
                    tooltip: 'Compare with the file on disk (and merge)',
                    icon: const Icon(Icons.difference_outlined),
                    onPressed: () => showDiffDialog(
                      context,
                      title: 'Disk vs version ${v.id}: ${f.name}',
                      future: api.diffWithFile(v.id),
                      onEdit: () async {
                        if (await showMergeEditor(context, versionId: v.id)) {
                          ref.invalidate(fileHistoryProvider(fileId));
                        }
                      },
                    ),
                  ),
                if (v.hasContent && older != null)
                  IconButton(
                    tooltip: 'Compare with version ${older.id}',
                    onPressed: () => showDiff(context, ref, older.id, v.id),
                    icon: const Icon(Icons.compare_arrows),
                  ),
                if (i > 0) // the latest version keeps the file restorable; "Delete history" removes it
                  IconButton(
                    tooltip: 'Delete this version',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () async {
                      if (await deleteSingleVersion(context, ref, v)) {
                        ref.invalidate(fileHistoryProvider(fileId));
                        refreshAll(ref);
                      }
                    },
                  ),
                if (v.hasContent)
                  TextButton.icon(
                    icon: const Icon(Icons.restore),
                    label: const Text('Restore'),
                    onPressed: () async {
                      final res = await showRestoreDialog(
                        context,
                        title: 'Restore version ${v.id}',
                        source: '${v.relativePath} · ${formatDateTime(v.timestamp)} · ${formatBytes(v.fileSize)}',
                        originalLocation: f.absolutePath,
                        run: (dest, overwrite, dry) =>
                            api.restoreVersion(v.id, destination: dest, overwrite: overwrite, dryRun: dry),
                      );
                      if (res != null) refreshAll(ref);
                    },
                  ),
              ]),
            );
          },
        ),
      ),
    ]);
  }

  Widget _fact(BuildContext context, String label, String value) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          Text(value),
        ],
      );
}
