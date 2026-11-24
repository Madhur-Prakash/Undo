// Chronological history of every recorded change.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import 'version_details_dialog.dart';

const _sortOptions = [
  SortOption(
    'time',
    'Time',
    descendingFirst: true,
    ascendingHint: 'oldest first',
    descendingHint: 'newest first',
  ),
  SortOption('path', 'Path', ascendingHint: 'A to Z', descendingHint: 'Z to A'),
  SortOption(
    'size',
    'Size',
    descendingFirst: true,
    ascendingHint: 'smallest first',
    descendingHint: 'largest first',
  ),
  SortOption(
    'operation',
    'Operation',
    ascendingHint: 'A to Z',
    descendingHint: 'Z to A',
  ),
];

int _compare(VersionInfo a, VersionInfo b, String key) => switch (key) {
  'path' => a.absolutePath.toLowerCase().compareTo(
    b.absolutePath.toLowerCase(),
  ),
  'size' => (a.hasContent ? a.fileSize : -1).compareTo(
    b.hasContent ? b.fileSize : -1,
  ),
  'operation' => a.operation.compareTo(b.operation),
  _ => a.timestamp.compareTo(b.timestamp),
};

class HistoryPage extends ConsumerStatefulWidget {
  const HistoryPage({super.key});

  @override
  ConsumerState<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends ConsumerState<HistoryPage> {
  String _filter = '';
  String? _operation;
  SortState _sort = (key: 'time', descending: true);
  static const _limit = 500;

  @override
  Widget build(BuildContext context) {
    final activity = ref.watch(activityProvider(_limit));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PageHeader(
          title: 'History',
          subtitle: 'Every captured change (the last $_limit events)',
          actions: [
            IconButton(
              tooltip: 'Refresh',
              onPressed: () => ref.invalidate(activityProvider(_limit)),
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.filter_list),
                    hintText: 'Filter by path',
                  ),
                  onChanged: (v) => setState(() => _filter = v.toLowerCase()),
                ),
              ),
              const SizedBox(width: 12),
              DropdownButton<String?>(
                value: _operation,
                hint: const Text('All operations'),
                items: [
                  const DropdownMenuItem(
                    value: null,
                    child: Text('All operations'),
                  ),
                  for (final op in [
                    'CREATE',
                    'MODIFY',
                    'DELETE',
                    'RENAME',
                    'MOVE',
                  ])
                    DropdownMenuItem(value: op, child: Text(op)),
                ],
                onChanged: (v) => setState(() => _operation = v),
              ),
              const SizedBox(width: 12),
              SortControl(
                options: _sortOptions,
                value: _sort,
                onChanged: (s) => setState(() => _sort = s),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: AsyncView<List<VersionInfo>>(
            value: activity,
            onRetry: () => ref.invalidate(activityProvider(_limit)),
            isEmpty: (l) => l.isEmpty,
            empty: const EmptyState(
              icon: Icons.history,
              title: 'No history yet',
              message: 'Changes appear here as soon as a tracked file is created, modified, renamed or deleted.',
            ),
            builder: (items) {
              final rows =
                  items
                      .where(
                        (v) => _operation == null || v.operation == _operation,
                      )
                      .where(
                        (v) =>
                            _filter.isEmpty ||
                            v.absolutePath.toLowerCase().contains(_filter),
                      )
                      .toList()
                    ..sort((a, b) {
                      final c = _compare(a, b, _sort.key);
                      final tie = c != 0 ? c : a.id.compareTo(b.id);
                      return _sort.descending ? -tie : tie;
                    });
              if (rows.isEmpty)
                return const EmptyState(
                  icon: Icons.search_off,
                  title: 'No matching events',
                );
              return ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: rows.length,
                separatorBuilder: (_, _) => const Divider(),
                itemBuilder: (_, i) {
                  final v = rows[i];
                  return ListTile(
                    leading: SizedBox(
                      width: 72,
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: OperationChip(v.operation),
                      ),
                    ),
                    title: Text(v.name),
                    subtitle: Text(
                      v.absolutePath,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(formatDateTime(v.timestamp)),
                        Text(
                          'v${v.parentVersionId ?? '—'} → v${v.id}${v.hasContent ? ' · ${formatBytes(v.fileSize)}' : ''}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                    onTap: () => showVersionDetails(context, v.id),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}
