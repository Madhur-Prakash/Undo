// Storage usage, savings, verification and garbage collection.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

class StoragePage extends ConsumerStatefulWidget {
  const StoragePage({super.key});

  @override
  ConsumerState<StoragePage> createState() => _StoragePageState();
}

class _StoragePageState extends ConsumerState<StoragePage> {
  bool _busy = false;
  String? _lastResult;

  Future<void> _run(Future<String> Function() action) async {
    setState(() => _busy = true);
    final text = await runAction(context, action);
    if (mounted) {
      setState(() {
        _busy = false;
        if (text != null) _lastResult = text;
      });
    }
    ref.invalidate(storageProvider);
  }

  @override
  Widget build(BuildContext context) {
    final stats = ref.watch(storageProvider);
    final api = ref.read(apiProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: 'Storage',
        subtitle: 'Content-addressed (BLAKE3) blobs, Zstandard compressed and deduplicated',
        actions: [IconButton(tooltip: 'Refresh', onPressed: () => ref.invalidate(storageProvider), icon: const Icon(Icons.refresh))],
      ),
      Expanded(
        child: AsyncView<StorageStats>(
          value: stats,
          onRetry: () => ref.invalidate(storageProvider),
          builder: (s) => ListView(padding: const EdgeInsets.fromLTRB(24, 0, 24, 24), children: [
            LayoutBuilder(builder: (context, c) {
              final columns = c.maxWidth > 1100 ? 4 : (c.maxWidth > 650 ? 2 : 1);
              final w = (c.maxWidth - (columns - 1) * 12) / columns;
              final cards = [
                StatCard(label: 'Blob storage on disk', value: formatBytes(s.blobDiskBytes), note: '${s.blobCount} blobs · ${s.chunkCount} chunks', icon: Icons.inventory_2_outlined),
                StatCard(label: 'Database', value: formatBytes(s.databaseBytes), note: '${s.versionCount} versions', icon: Icons.table_chart_outlined),
                StatCard(label: 'Original size (all versions)', value: formatBytes(s.logicalBytes), icon: Icons.data_usage),
                StatCard(label: 'Compressed size', value: formatBytes(s.storedBytes), note: 'unique content ${formatBytes(s.uniqueBytes)}', icon: Icons.compress),
                StatCard(label: 'Deduplication savings', value: formatBytes(s.dedupSavingsBytes), note: percent(s.dedupSavingsBytes, s.logicalBytes), icon: Icons.copy_all_outlined, color: Colors.green.shade600),
                StatCard(label: 'Compression savings', value: formatBytes(s.compressionSavingsBytes), note: percent(s.compressionSavingsBytes, s.uniqueBytes), icon: Icons.archive_outlined, color: Colors.green.shade600),
                StatCard(
                  label: 'Verification',
                  value: s.lastVerifyAt == null ? 'Never run' : (s.lastVerifyOk == true ? 'Healthy' : 'Problems found'),
                  note: s.lastVerifyAt == null ? null : 'last run ${formatRelative(s.lastVerifyAt)}',
                  icon: Icons.verified_outlined,
                  color: s.lastVerifyOk == false || s.unhealthyBlobs > 0 ? Theme.of(context).colorScheme.error : null,
                ),
                StatCard(label: 'Unhealthy blobs', value: '${s.unhealthyBlobs}', note: 'missing or corrupt', icon: Icons.report_problem_outlined,
                    color: s.unhealthyBlobs > 0 ? Theme.of(context).colorScheme.error : null),
              ];
              return Wrap(spacing: 12, runSpacing: 12, children: [for (final card in cards) SizedBox(width: w, child: card)]);
            }),
            const SizedBox(height: 16),
            SectionCard(
              title: 'Maintenance',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Data directory: ${s.dataDir}'),
                Text('Compression: ${s.compressionAlgorithms.entries.map((e) => '${e.key} × ${e.value}').join(', ')}'),
                Text('Last garbage collection: ${formatRelative(s.lastGcAt)}'),
                const SizedBox(height: 12),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  FilledButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _run(() async {
                              final r = await api.verify();
                              return r.healthy
                                  ? 'Verified ${r.checkedBlobs} blobs and ${r.checkedChunks} chunks: all healthy (${r.durationSeconds}s)'
                                  : 'Problems: ${r.missing.length} missing, ${r.corrupt.length} corrupt, ${r.repaired.length} repaired';
                            }),
                    icon: const Icon(Icons.verified),
                    label: const Text('Verify integrity'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _run(() async {
                              final r = await api.gc(dryRun: true);
                              return 'GC preview: ${r.candidateBlobs} unreferenced blobs, ${r.orphanFiles} orphan files, '
                                  '${formatBytes(r.reclaimableBytes + r.orphanBytes)} reclaimable (${r.protectedByGrace} protected by grace period)';
                            }),
                    icon: const Icon(Icons.preview),
                    label: const Text('Preview garbage collection'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () async {
                            final ok = await confirmDialog(context,
                                title: 'Run garbage collection?',
                                message: 'Stored data that no version or snapshot references will be deleted.',
                                confirm: 'Run');
                            if (!ok) return;
                            await _run(() async {
                              final r = await api.gc(dryRun: false);
                              return 'Garbage collection reclaimed ${formatBytes(r.reclaimedBytes)}';
                            });
                          },
                    icon: const Icon(Icons.cleaning_services_outlined),
                    label: const Text('Run garbage collection'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _run(() async {
                              final r = await api.retention(dryRun: true);
                              return 'Retention preview: ${r.versionsRemoved} of ${r.versionsExamined} versions would be removed '
                                  '(${r.filesAffected} files, ~${formatBytes(r.estimatedReclaimBytes)})';
                            }),
                    icon: const Icon(Icons.rule),
                    label: const Text('Preview retention'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () async {
                            final preview = await runAction(context, () => api.retention(dryRun: true));
                            if (preview == null || !context.mounted) return;
                            if (preview.versionsRemoved == 0) {
                              showMessage(context, 'Retention: nothing to remove with the current policy');
                              return;
                            }
                            final ok = await confirmDialog(
                              context,
                              title: 'Apply retention now?',
                              message: '${preview.versionsRemoved} old versions of ${preview.filesAffected} files will be '
                                  'removed from history, freeing about ${formatBytes(preview.estimatedReclaimBytes)}.\n\n'
                                  'Your files are not touched. The latest version of every file, the last content of '
                                  'deleted files and snapshot versions are always kept.',
                              confirm: 'Remove old versions',
                              destructive: true,
                            );
                            if (!ok) return;
                            await _run(() async {
                              final r = await api.retention(dryRun: false);
                              final g = await api.gc(dryRun: false);
                              return 'Retention removed ${r.versionsRemoved} versions; '
                                  'garbage collection freed ${formatBytes(g.reclaimedBytes)}';
                            });
                          },
                    icon: const Icon(Icons.auto_delete_outlined),
                    label: const Text('Apply retention now'),
                  ),
                ]),
                if (_busy) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
                if (_lastResult != null) Padding(padding: const EdgeInsets.only(top: 12), child: SelectableText(_lastResult!)),
              ]),
            ),
          ]),
        ),
      ),
    ]);
  }
}
