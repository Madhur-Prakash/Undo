// File explorer: search tracked files (live and deleted) and open their history.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

/// Sorted by the daemon, before paging (GET /files?sort=...).
const fileSortOptions = [
  SortOption('path', 'Path', ascendingHint: 'A to Z', descendingHint: 'Z to A'),
  SortOption('modified', 'Last modified',
      descendingFirst: true, ascendingHint: 'oldest first', descendingHint: 'newest first'),
  SortOption('size', 'Size', descendingFirst: true, ascendingHint: 'smallest first', descendingHint: 'largest first'),
  SortOption('version', 'Latest change',
      descendingFirst: true, ascendingHint: 'oldest first', descendingHint: 'newest first'),
  SortOption('versions', 'Number of versions',
      descendingFirst: true, ascendingHint: 'fewest first', descendingHint: 'most first'),
];

class FilesPage extends ConsumerStatefulWidget {
  const FilesPage({super.key});

  @override
  ConsumerState<FilesPage> createState() => _FilesPageState();
}

class _FilesPageState extends ConsumerState<FilesPage> {
  Timer? _debounce;
  late final TextEditingController _search;

  @override
  void initState() {
    super.initState();
    _search = TextEditingController(text: ref.read(fileQueryProvider).text);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _setQuery(FileQuery q) => ref.read(fileQueryProvider.notifier).update(q);

  @override
  Widget build(BuildContext context) {
    final query = ref.watch(fileQueryProvider);
    final files = ref.watch(filesProvider);
    final roots = ref.watch(rootsProvider);
    final theme = Theme.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: 'Files',
        subtitle: 'Tracked files and their available history',
        actions: [IconButton(tooltip: 'Refresh', onPressed: () => ref.invalidate(filesProvider), icon: const Icon(Icons.refresh))],
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _search,
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search by path'),
              onChanged: (v) {
                _debounce?.cancel();
                _debounce = Timer(const Duration(milliseconds: 300), () => _setQuery(query.copyWith(text: v.trim())));
              },
            ),
          ),
          const SizedBox(width: 12),
          roots.maybeWhen(
            data: (list) => AppDropdown<int?>(
              value: query.rootId,
              hint: const Text('All roots'),
              items: [
                const DropdownMenuItem(value: null, child: Text('All roots')),
                for (final r in list) DropdownMenuItem(value: r.id, child: Text(r.path, overflow: TextOverflow.ellipsis)),
              ],
              onChanged: (v) => _setQuery(v == null ? query.copyWith(clearRoot: true) : query.copyWith(rootId: v)),
            ),
            orElse: () => const SizedBox.shrink(),
          ),
          const SizedBox(width: 12),
          FilterChip(
            label: const Text('Include deleted'),
            selected: query.includeDeleted,
            onSelected: (v) => _setQuery(query.copyWith(includeDeleted: v)),
          ),
          const SizedBox(width: 12),
          SortControl(
            options: fileSortOptions,
            value: (key: query.sort, descending: query.descending),
            onChanged: (s) => _setQuery(query.copyWith(sort: s.key, descending: s.descending)),
          ),
        ]),
      ),
      const SizedBox(height: 16),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 6),
        child: DefaultTextStyle(
          style: theme.textTheme.labelMedium!.copyWith(color: theme.colorScheme.onSurfaceVariant),
          child: const Row(children: [
            Expanded(flex: 5, child: Text('Name / path')),
            Expanded(flex: 1, child: Text('Size', textAlign: TextAlign.right)),
            Expanded(flex: 2, child: Text('Last modified', textAlign: TextAlign.right)),
            Expanded(flex: 2, child: Text('Latest version', textAlign: TextAlign.right)),
            Expanded(flex: 1, child: Text('History', textAlign: TextAlign.right)),
          ]),
        ),
      ),
      const Divider(),
      Expanded(
        child: AsyncView<FilePage>(
          value: files,
          onRetry: () => ref.invalidate(filesProvider),
          isEmpty: (p) => p.items.isEmpty,
          empty: EmptyState(
            icon: Icons.folder_off_outlined,
            title: query.text.isEmpty ? 'No tracked files yet' : 'No files match "${query.text}"',
            message: query.text.isEmpty ? 'Add a folder to track on the Overview page.' : null,
          ),
          builder: (page) => Column(children: [
            Expanded(
              child: ListView.builder(
                itemCount: page.items.length,
                itemBuilder: (_, i) => _FileRow(file: page.items[i]),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text('${page.items.length} of ${page.total} files', style: theme.textTheme.bodySmall),
            ),
          ]),
        ),
      ),
    ]);
  }
}

class _FileRow extends StatelessWidget {
  const _FileRow({required this.file});
  final FileInfo file;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    return InkWell(
      onTap: () => context.go('/files/${file.id}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
        child: Row(children: [
          Icon(file.isDeleted ? Icons.delete_outline : Icons.insert_drive_file_outlined,
              size: 20, color: file.isDeleted ? theme.colorScheme.error : muted),
          const SizedBox(width: 12),
          Expanded(
            flex: 5,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(file.name, overflow: TextOverflow.ellipsis,
                  style: file.isDeleted ? TextStyle(decoration: TextDecoration.lineThrough, color: muted) : null),
              Text(file.absolutePath, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodySmall),
            ]),
          ),
          Expanded(flex: 1, child: Text(formatBytes(file.size), textAlign: TextAlign.right)),
          Expanded(flex: 2, child: Text(formatDateTime(file.lastModified), textAlign: TextAlign.right)),
          Expanded(
            flex: 2,
            child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              if (file.latestOperation != null) OperationChip(file.latestOperation!),
              const SizedBox(width: 6),
              Text(file.latestVersionId != null ? 'v${file.latestVersionId}' : '—'),
            ]),
          ),
          Expanded(flex: 1, child: Text('${file.versionCount} versions', textAlign: TextAlign.right)),
        ]),
      ),
    );
  }
}
