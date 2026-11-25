// Overview: daemon status, totals, savings, tracked roots, recent changes and snapshots.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../history/forget_dialog.dart';
import '../history/version_details_dialog.dart';
import '../restore/merge_editor.dart';
import '../restore/rollback_dialog.dart';

class OverviewPage extends ConsumerWidget {
  const OverviewPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(statusProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: 'Overview',
        subtitle: 'What Undo is protecting right now',
        actions: [
          FilledButton.icon(onPressed: () => _addRoot(context, ref), icon: const Icon(Icons.add), label: const Text('Track folder')),
          IconButton(tooltip: 'Refresh', onPressed: () => refreshAll(ref), icon: const Icon(Icons.refresh)),
        ],
      ),
      Expanded(
        child: AsyncView<StatusInfo>(
          value: status,
          onRetry: () => ref.invalidate(statusProvider),
          builder: (s) => ListView(padding: const EdgeInsets.fromLTRB(24, 0, 24, 24), children: [
            _StatsGrid(status: s),
            const SizedBox(height: 16),
            if (s.daemon != null) _DaemonCard(health: s.daemon!),
            const SizedBox(height: 16),
            const _RootsCard(),
            const SizedBox(height: 16),
            const _MergeDraftsCard(),
            LayoutBuilder(builder: (context, c) {
              final children = [const _RecentChanges(), const _RecentSnapshots()];
              if (c.maxWidth < 1000) {
                return Column(children: [children[0], const SizedBox(height: 16), children[1]]);
              }
              return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(flex: 3, child: children[0]),
                const SizedBox(width: 16),
                Expanded(flex: 2, child: children[1]),
              ]);
            }),
          ]),
        ),
      ),
    ]);
  }

  static Future<void> _addRoot(BuildContext context, WidgetRef ref) async {
    final dir = await pickFolder('Choose a folder to track');
    if (dir == null || !context.mounted) return;
    final root = await runAction(context, () => ref.read(apiProvider).addRoot(dir),
        success: 'Tracking $dir — the initial scan runs in the background');
    if (root != null) refreshAll(ref);
  }
}

class _StatsGrid extends StatelessWidget {
  const _StatsGrid({required this.status});
  final StatusInfo status;

  @override
  Widget build(BuildContext context) {
    final saved = (status.logicalBytes - status.storedBytes).clamp(0, 1 << 62);
    final cards = [
      StatCard(
        label: 'Daemon',
        value: status.daemonRunning ? 'Running' : 'Stopped',
        note: status.daemon != null ? 'up ${formatDuration(status.daemon!.uptimeSeconds)}' : null,
        icon: Icons.monitor_heart_outlined,
        color: status.daemonRunning ? Colors.green.shade600 : Colors.orange.shade700,
      ),
      StatCard(label: 'Tracked roots', value: '${status.rootCount}', icon: Icons.folder_special_outlined),
      StatCard(label: 'Tracked files', value: '${status.fileCount}', note: '${status.deletedFileCount} deleted', icon: Icons.description_outlined),
      StatCard(label: 'Total versions', value: '${status.versionCount}', note: '${status.snapshotCount} snapshots', icon: Icons.layers_outlined),
      StatCard(label: 'Original data size', value: formatBytes(status.logicalBytes), icon: Icons.data_usage),
      StatCard(label: 'Actual storage used', value: formatBytes(status.storedBytes), icon: Icons.save_outlined),
      StatCard(
        label: 'Space saved',
        value: formatBytes(saved),
        note: '${percent(saved, status.logicalBytes)} via dedup + compression',
        icon: Icons.compress,
        color: Colors.green.shade600,
      ),
      StatCard(
        label: 'Skipped files',
        value: '${status.skippedCount}',
        note: 'excluded, too large or unreadable',
        icon: Icons.block,
      ),
    ];
    return LayoutBuilder(builder: (context, c) {
      final columns = c.maxWidth > 1200 ? 4 : (c.maxWidth > 700 ? 2 : 1);
      final width = (c.maxWidth - (columns - 1) * 12) / columns;
      return Wrap(spacing: 12, runSpacing: 12, children: [for (final card in cards) SizedBox(width: width, child: card)]);
    });
  }
}

class _DaemonCard extends ConsumerWidget {
  const _DaemonCard({required this.health});
  final HealthInfo health;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return SectionCard(
      title: 'Daemon',
      trailing: TextButton.icon(
        onPressed: () async {
          final ok = await confirmDialog(context,
              title: 'Stop the daemon?', message: 'Changes will not be recorded until it is started again.', confirm: 'Stop');
          if (ok) await ref.read(connectionProvider.notifier).stopDaemon();
        },
        icon: const Icon(Icons.stop_circle_outlined),
        label: const Text('Stop'),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 24, runSpacing: 6, children: [
          Text('PID ${health.pid} · v${health.version}'),
          Text('Event queue ${health.queueDepth}/${health.queueCapacity}'),
          Text('Pending captures ${health.pendingCaptures}'),
          Text('Events ${health.eventsReceived} (dropped ${health.eventsDropped})'),
          Text('Last full reconcile ${formatRelative(health.lastReconcileAt)}${health.reconciling ? ' · reconciling now' : ''}'),
        ]),
        const SizedBox(height: 8),
        for (final w in health.watchers)
          Row(children: [
            StatusDot(ok: w.healthy && w.error == null, size: 8),
            const SizedBox(width: 8),
            Expanded(child: Text('${w.path} — ${w.mode}${w.error != null ? ' (${w.error})' : ''}', overflow: TextOverflow.ellipsis)),
          ]),
        if (health.recentErrors.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final e in health.recentErrors.reversed.take(3))
            Text(e, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error)),
        ],
      ]),
    );
  }
}

class _RootsCard extends ConsumerWidget {
  const _RootsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final roots = ref.watch(rootsProvider);
    final api = ref.read(apiProvider);
    return SectionCard(
      title: 'Tracked roots',
      padding: EdgeInsets.zero,
      child: AsyncView<List<RootInfo>>(
        value: roots,
        onRetry: () => ref.invalidate(rootsProvider),
        isEmpty: (l) => l.isEmpty,
        empty: EmptyState(
          icon: Icons.create_new_folder_outlined,
          title: 'No folders tracked yet',
          message: 'Choose a folder and Undo will start keeping its history.',
          action: FilledButton.icon(
            onPressed: () => OverviewPage._addRoot(context, ref),
            icon: const Icon(Icons.add),
            label: const Text('Track folder'),
          ),
        ),
        builder: (list) => Column(children: [
          for (final r in list)
            ListTile(
              leading: Icon(r.enabled ? Icons.folder : Icons.folder_off_outlined),
              title: Text(r.path),
              subtitle: Text('${r.fileCount} files · ${r.deletedFileCount} deleted · ${r.versionCount} versions · '
                  'scanned ${formatRelative(r.lastScanAt)} · ${r.enabled ? (r.watchMode ?? 'not watched') : 'paused'}'),
              // Open the Files page showing only this folder's files.
              onTap: () {
                final q = ref.read(fileQueryProvider);
                ref.read(fileQueryProvider.notifier).update(q.copyWith(text: '', rootId: r.id));
                context.go('/files');
              },
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(
                  tooltip: 'Scan now (find missed changes)',
                  icon: const Icon(Icons.sync),
                  onPressed: () async {
                    final reports = await runAction(context, () => api.scan(target: r.id));
                    if (reports != null && reports.isNotEmpty && context.mounted) {
                      final rep = reports.first;
                      showMessage(context,
                          'Scan: ${rep.newFiles} new, ${rep.modified} modified, ${rep.deleted} deleted, ${rep.renamed} moved, ${rep.skipped} skipped');
                    }
                    refreshAll(ref);
                  },
                ),
                IconButton(
                  tooltip: 'Roll back this folder to a point in time',
                  icon: const Icon(Icons.history),
                  onPressed: () async {
                    final res = await showRollbackDialog(context, ref, r);
                    if (res != null) refreshAll(ref);
                  },
                ),
                IconButton(
                  tooltip: r.enabled
                      ? 'Pause monitoring (history is kept; resume any time)'
                      : 'Resume monitoring (scans for changes made while paused)',
                  icon: Icon(r.enabled ? Icons.pause_circle_outline : Icons.play_circle_outline),
                  onPressed: () async {
                    await runAction(context, () => api.setRootEnabled(r.id, !r.enabled));
                    refreshAll(ref);
                  },
                ),
                IconButton(
                  tooltip: 'Delete history of this folder or a subfolder (all, or only old versions)',
                  icon: const Icon(Icons.delete_sweep_outlined),
                  onPressed: () async {
                    final res = await showForgetDialog(context, path: r.path, folderRoot: r.path);
                    if (res == null || !context.mounted) return;
                    showMessage(context, 'Removed ${res.versionsRemoved} version(s) of ${res.filesAffected} file(s). ${res.note ?? ''}'.trim());
                    refreshAll(ref);
                  },
                ),
                IconButton(
                  tooltip: 'Stop tracking and delete its history',
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: () async {
                    final ok = await confirmDialog(context,
                        title: 'Stop tracking and delete history?',
                        message: '${r.path}\n\n'
                            'Undo stops watching this folder and deletes everything it recorded for it: '
                            '${r.versionCount} versions of ${r.fileCount + r.deletedFileCount} files, and its snapshots. '
                            'Old versions can no longer be restored. The files in the folder itself are not touched.\n\n'
                            'To stop recording but keep the history, use Pause instead.',
                        confirm: 'Delete history',
                        destructive: true);
                    if (!ok || !context.mounted) return;
                    await runAction(context, () => api.removeRoot(r.id, purge: true),
                        success: 'Stopped tracking ${r.path} and deleted its history');
                    final q = ref.read(fileQueryProvider);
                    if (q.rootId == r.id) ref.read(fileQueryProvider.notifier).update(q.copyWith(clearRoot: true));
                    refreshAll(ref);
                  },
                ),
              ]),
            ),
        ]),
      ),
    );
  }
}

class _RecentChanges extends ConsumerWidget {
  const _RecentChanges();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activity = ref.watch(activityProvider(15));
    return SectionCard(
      title: 'Recent file changes',
      trailing: TextButton(onPressed: () => context.go('/history'), child: const Text('All history')),
      padding: EdgeInsets.zero,
      child: AsyncView<List<VersionInfo>>(
        value: activity,
        isEmpty: (l) => l.isEmpty,
        empty: const EmptyState(icon: Icons.history, title: 'No changes recorded yet'),
        builder: (list) => Column(children: [
          for (final v in list)
            ListTile(
              leading: SizedBox(width: 72, child: Align(alignment: Alignment.centerLeft, child: OperationChip(v.operation))),
              title: Text(v.name, overflow: TextOverflow.ellipsis),
              subtitle: Text(v.absolutePath, overflow: TextOverflow.ellipsis),
              trailing: Text(formatRelative(v.timestamp)),
              onTap: () => showVersionDetails(context, v.id),
            ),
        ]),
      ),
    );
  }
}

class _RecentSnapshots extends ConsumerWidget {
  const _RecentSnapshots();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snaps = ref.watch(snapshotsProvider);
    return SectionCard(
      title: 'Recent snapshots',
      trailing: TextButton(onPressed: () => context.go('/snapshots'), child: const Text('All snapshots')),
      padding: EdgeInsets.zero,
      child: AsyncView<List<SnapshotInfo>>(
        value: snaps,
        isEmpty: (l) => l.isEmpty,
        empty: const EmptyState(icon: Icons.photo_library_outlined, title: 'No snapshots yet'),
        builder: (list) => Column(children: [
          for (final s in list.take(8))
            ListTile(
              leading: const Icon(Icons.bookmark_outline),
              title: Text(s.name),
              subtitle: Text('${s.fileCount} files · ${formatBytes(s.totalSize)}'),
              trailing: Text(formatRelative(s.createdAt)),
            ),
        ]),
      ),
    );
  }
}


/// Saved merges: unfinished ones ("Save progress") and resolutions waiting for a restore.
/// Hidden when none.
class _MergeDraftsCard extends ConsumerWidget {
  const _MergeDraftsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final drafts = ref.watch(mergeDraftsProvider).value ?? const <MergeDraft>[];
    if (drafts.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: SectionCard(
        title: 'Saved merges (${drafts.length})',
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (final d in drafts)
            ListTile(
              leading: Icon(d.resolved ? Icons.task_alt : Icons.merge_type),
              title: Text(d.path, overflow: TextOverflow.ellipsis),
              subtitle: Text(d.resolved
                  ? 'Version ${d.versionId} · resolved ${formatRelative(d.updatedAt)} · applied when you restore this version'
                  : 'Version ${d.versionId} · progress saved ${formatRelative(d.updatedAt)}'),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                TextButton(
                  onPressed: () async {
                    final ok = await confirmDialog(
                      context,
                      title: d.resolved ? 'Discard the resolution?' : 'Discard saved progress?',
                      message: '${d.path}\n\nThe saved merge is deleted. The file is not touched.',
                      confirm: 'Discard',
                      destructive: true,
                    );
                    if (!ok || !context.mounted) return;
                    await runAction(context, () => ref.read(apiProvider).deleteMergeDraft(d.path));
                    ref.invalidate(mergeDraftsProvider);
                  },
                  child: const Text('Discard'),
                ),
                if (d.resolved) ...[
                  TextButton(
                    onPressed: () async {
                      await showMergeEditor(context, versionId: d.versionId, path: d.path);
                      ref.invalidate(mergeDraftsProvider);
                    },
                    child: const Text('Edit'),
                  ),
                  FilledButton.icon(
                    icon: const Icon(Icons.restore),
                    label: const Text('Restore'),
                    onPressed: () async {
                      final ok = await confirmDialog(
                        context,
                        title: 'Restore with your resolution?',
                        message: '${d.path}\n\nThe resolved text is written to the file. Its current '
                            'content is saved as a version first, so this can be undone.',
                        confirm: 'Restore',
                      );
                      if (!ok || !context.mounted) return;
                      final r = await runAction(
                        context,
                        () => ref.read(apiProvider).restoreVersion(d.versionId, destination: d.path, dryRun: false),
                      );
                      if (r != null && context.mounted) {
                        final item = r.items.firstOrNull;
                        final ok = item != null && (item.action == 'overwrite' || item.action == 'create' || item.action == 'identical');
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                          content: Text(ok ? 'Restored ${d.path}' : 'Not restored: ${item?.detail ?? 'unknown reason'}'),
                        ));
                      }
                      refreshAll(ref);
                    },
                  ),
                ] else
                  FilledButton.icon(
                    icon: const Icon(Icons.play_arrow),
                    label: const Text('Resume'),
                    onPressed: () async {
                      await showMergeEditor(context, versionId: d.versionId, path: d.path);
                      ref.invalidate(mergeDraftsProvider);
                    },
                  ),
              ]),
            ),
        ]),
      ),
    );
  }
}

