// Snapshots: create, compare, restore, delete.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../restore/restore_dialog.dart';

class SnapshotsPage extends ConsumerStatefulWidget {
  const SnapshotsPage({super.key});

  @override
  ConsumerState<SnapshotsPage> createState() => _SnapshotsPageState();
}

class _SnapshotsPageState extends ConsumerState<SnapshotsPage> {
  final Set<int> _selected = {};

  @override
  Widget build(BuildContext context) {
    final snaps = ref.watch(snapshotsProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: 'Snapshots',
        subtitle: 'Named records of a root\'s complete state. They reference stored data; nothing is copied.',
        actions: [
          OutlinedButton.icon(
            onPressed: _selected.length == 2 ? () => _compare(snaps.value ?? const []) : null,
            icon: const Icon(Icons.compare),
            label: Text('Compare (${_selected.length}/2)'),
          ),
          FilledButton.icon(onPressed: _create, icon: const Icon(Icons.add_a_photo_outlined), label: const Text('Create snapshot')),
          IconButton(tooltip: 'Refresh', onPressed: () => ref.invalidate(snapshotsProvider), icon: const Icon(Icons.refresh)),
        ],
      ),
      Expanded(
        child: AsyncView<List<SnapshotInfo>>(
          value: snaps,
          onRetry: () => ref.invalidate(snapshotsProvider),
          isEmpty: (l) => l.isEmpty,
          empty: EmptyState(
            icon: Icons.photo_library_outlined,
            title: 'No snapshots yet',
            message: 'Create one before risky changes, e.g. "before-upgrade".',
            action: FilledButton(onPressed: _create, child: const Text('Create snapshot')),
          ),
          builder: (list) => ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: list.length,
            separatorBuilder: (_, _) => const Divider(),
            itemBuilder: (_, i) {
              final s = list[i];
              return ListTile(
                leading: Checkbox(
                  value: _selected.contains(s.id),
                  onChanged: (v) => setState(() {
                    if (v == true) {
                      if (_selected.length == 2) _selected.remove(_selected.first);
                      _selected.add(s.id);
                    } else {
                      _selected.remove(s.id);
                    }
                  }),
                ),
                title: Text(s.name),
                subtitle: Text([
                  if (s.description != null && s.description!.isNotEmpty) s.description!,
                  formatDateTime(s.createdAt),
                  s.rootPath,
                  '${s.fileCount} files · ${formatBytes(s.totalSize)}',
                ].join(' · ')),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  TextButton.icon(onPressed: () => _restore(s), icon: const Icon(Icons.restore), label: const Text('Restore')),
                  IconButton(tooltip: 'Delete snapshot', onPressed: () => _delete(s), icon: const Icon(Icons.delete_outline)),
                ]),
              );
            },
          ),
        ),
      ),
    ]);
  }

  Future<void> _create() async {
    final roots = await ref.read(rootsProvider.future);
    if (!mounted) return;
    if (roots.isEmpty) {
      showMessage(context, 'Track a folder first', error: true);
      return;
    }
    final name = TextEditingController();
    final desc = TextEditingController();
    var rootId = roots.first.id;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Create snapshot'),
          content: SizedBox(
            width: 520,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: name, autofocus: true, decoration: const InputDecoration(labelText: 'Name')),
              const SizedBox(height: 12),
              TextField(controller: desc, decoration: const InputDecoration(labelText: 'Description (optional)')),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: rootId,
                decoration: const InputDecoration(labelText: 'Root'),
                items: [for (final r in roots) DropdownMenuItem(value: r.id, child: Text(r.path))],
                onChanged: (v) => setLocal(() => rootId = v ?? rootId),
              ),
              const SizedBox(height: 12),
              Text('The root is scanned first so the snapshot reflects its current state.',
                  style: Theme.of(ctx).textTheme.bodySmall),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok != true || name.text.trim().isEmpty || !mounted) return;
    final snap = await runAction(
      context,
      () => ref.read(apiProvider).createSnapshot(name.text.trim(),
          description: desc.text.trim().isEmpty ? null : desc.text.trim(), rootId: rootId),
      success: 'Snapshot "${name.text.trim()}" created',
    );
    if (snap != null) refreshAll(ref);
  }

  Future<void> _restore(SnapshotInfo s) async {
    final api = ref.read(apiProvider);
    final res = await showRestoreDialog(
      context,
      title: 'Restore snapshot "${s.name}"',
      source: '${s.fileCount} files from ${formatDateTime(s.createdAt)}',
      originalLocation: s.rootPath,
      run: (dest, overwrite, dry) => api.restoreSnapshot(s.id, destination: dest, overwrite: overwrite, dryRun: dry),
    );
    if (res != null) refreshAll(ref);
  }

  Future<void> _delete(SnapshotInfo s) async {
    final ok = await confirmDialog(context,
        title: 'Delete snapshot?',
        message: '"${s.name}" will be deleted. File versions are kept; data only referenced by this snapshot '
            'can be reclaimed by garbage collection.',
        confirm: 'Delete',
        destructive: true);
    if (!ok || !mounted) return;
    await runAction(context, () => ref.read(apiProvider).deleteSnapshot(s.id), success: 'Snapshot deleted');
    _selected.remove(s.id);
    refreshAll(ref);
  }

  Future<void> _compare(List<SnapshotInfo> all) async {
    final chosen = all.where((s) => _selected.contains(s.id)).toList()..sort((a, b) => a.createdAt.compareTo(b.createdAt));
    if (chosen.length != 2) return;
    final api = ref.read(apiProvider);
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${chosen[0].name} → ${chosen[1].name}'),
        content: SizedBox(
          width: 760,
          height: 520,
          child: FutureBuilder<SnapshotDiff>(
            future: api.diffSnapshots(chosen[0].id, chosen[1].id),
            builder: (ctx, snap) {
              if (snap.hasError) return ErrorView(message: snap.error.toString());
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              final d = snap.data!;
              final rows = [
                for (final c in d.added) ('+', c, Colors.green.shade600),
                for (final c in d.removed) ('−', c, Theme.of(ctx).colorScheme.error),
                for (final c in d.modified) ('~', c, Theme.of(ctx).colorScheme.primary),
              ];
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('${d.added.length} added · ${d.removed.length} removed · ${d.modified.length} modified · ${d.unchanged} unchanged'),
                const SizedBox(height: 8),
                Expanded(
                  child: rows.isEmpty
                      ? const EmptyState(icon: Icons.check_circle_outline, title: 'The snapshots are identical')
                      : ListView.builder(
                          itemCount: rows.length,
                          itemBuilder: (_, i) {
                            final (sign, c, color) = rows[i];
                            return ListTile(
                              leading: Text(sign, style: TextStyle(color: color, fontSize: 18, fontWeight: FontWeight.bold)),
                              title: Text(c.relativePath),
                              subtitle: Text('${c.aSize != null ? formatBytes(c.aSize) : '—'} → ${c.bSize != null ? formatBytes(c.bSize) : '—'}'),
                            );
                          },
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
}
