// Settings editor. Every value is validated and persisted by the backend.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/models.dart';
import '../../core/providers/providers.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PageHeader(
          title: 'Settings',
          subtitle:
              'Changes are validated by the daemon and applied immediately',
          actions: [
            IconButton(
              tooltip: 'Reload',
              onPressed: () => ref.invalidate(settingsProvider),
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        Expanded(
          child: AsyncView<Map<String, dynamic>>(
            value: settings,
            onRetry: () => ref.invalidate(settingsProvider),
            builder: (s) =>
                _SettingsForm(key: ValueKey(s.hashCode), initial: s),
          ),
        ),
      ],
    );
  }
}

class _SettingsForm extends ConsumerStatefulWidget {
  const _SettingsForm({super.key, required this.initial});
  final Map<String, dynamic> initial;

  @override
  ConsumerState<_SettingsForm> createState() => _SettingsFormState();
}

class _SettingsFormState extends ConsumerState<_SettingsForm> {
  late Map<String, Map<String, dynamic>> _values;
  final Map<String, TextEditingController> _text = {};
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _values = {
      for (final e in widget.initial.entries)
        if (e.value is Map && !e.key.startsWith('_'))
          e.key: Map<String, dynamic>.from(e.value as Map),
    };
  }

  @override
  void dispose() {
    for (final c in _text.values) {
      c.dispose();
    }
    super.dispose();
  }

  dynamic _get(String section, String key) => _values[section]?[key];
  void _set(String section, String key, dynamic value) =>
      setState(() => _values[section]![key] = value);

  /// Settings shown as sizes; the backend accepts "4GiB", "500MB", "64" (bytes).
  static const _sizeKeys = {
    'capture.max_file_size',
    'chunking.chunk_size',
    'chunking.min_file_size',
    'compression.min_size',
    'retention.max_storage_bytes',
  };

  /// The text a field shows for a stored value (and compares against to detect changes).
  static String _textOf(String section, String key, Object? v) {
    if (v == null) return '';
    if (v is List) return v.join(', ');
    if (v is num && _sizeKeys.contains('$section.$key')) {
      return _sizeText(v.toInt());
    }
    return v.toString();
  }

  static String _sizeText(int bytes) {
    const units = [('GiB', 1 << 30), ('MiB', 1 << 20), ('KiB', 1 << 10)];
    for (final (unit, size) in units) {
      if (bytes >= size && bytes % size == 0) return '${bytes ~/ size}$unit';
    }
    return '$bytes';
  }

  TextEditingController _controller(String section, String key) =>
      _text.putIfAbsent(
        '$section.$key',
        () => TextEditingController(
          text: _textOf(section, key, _get(section, key)),
        ),
      );

  Map<String, dynamic> _changes() {
    final out = <String, dynamic>{};
    for (final entry in _text.entries) {
      final parts = entry.key.split('.');
      final text = entry.value.text.trim();
      final original = (widget.initial[parts[0]] as Map)[parts[1]];
      if (text != _textOf(parts[0], parts[1], original)) {
        (out[parts[0]] ??= <String, dynamic>{})[parts[1]] = text.isEmpty
            ? null
            : text;
      }
    }
    for (final section in _values.entries) {
      for (final kv in section.value.entries) {
        if (_text.containsKey('${section.key}.${kv.key}')) continue;
        final original = (widget.initial[section.key] as Map)[kv.key];
        if (kv.value != original && kv.value is! List) {
          (out[section.key] ??= <String, dynamic>{})[kv.key] = kv.value;
        }
      }
    }
    return out;
  }

  Future<void> _save() async {
    final changes = _changes();
    if (changes.isEmpty) {
      showMessage(context, 'Nothing changed');
      return;
    }
    setState(() => _saving = true);
    final result = await runAction(
      context,
      () => ref.read(apiProvider).updateSettings(changes),
      success: 'Settings saved',
    );
    if (mounted) setState(() => _saving = false);
    if (result != null) ref.invalidate(settingsProvider);
  }

  /// A labelled text field. The full label sits above the box and wraps when long (never cut
  /// off); [help] (an example or the meaning of "empty") goes below it, also in full.
  Widget _number(
    String section,
    String key,
    String label, {
    String? help,
    bool enabled = true,
  }) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
            color: enabled ? null : Theme.of(context).disabledColor,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _controller(section, key),
          enabled: enabled,
          decoration: InputDecoration(helperText: help, helperMaxLines: 6),
        ),
      ],
    ),
  );

  Widget _switch(String section, String key, String label, {String? help}) =>
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(label),
        subtitle: help == null ? null : Text(help),
        value: (_get(section, key) as bool?) ?? false,
        onChanged: (v) => _set(section, key, v),
      );

  @override
  Widget build(BuildContext context) {
    final info = (widget.initial['_info'] as Map?) ?? const {};
    final level = ((_get('compression', 'level') as num?) ?? 3).toInt();
    final maxFile = (widget.initial['capture'] as Map)['max_file_size'] as int?;
    final theme = (_get('ui', 'theme') as String?) ?? 'system';
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 96),
      children: [
        SectionCard(
          title: 'Storage location',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SelectableText('${info['data_dir'] ?? ''}'),
              const SizedBox(height: 4),
              SelectableText(
                'Settings file: ${info['config_path'] ?? '${info['data_dir'] ?? ''}${Platform.pathSeparator}config.json'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 4),
              Text(
                'To use another location, stop the daemon, move the folder and set the UNDO_HOME environment variable.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Compression',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _switch(
                'compression',
                'enabled',
                'Compress stored data (Zstandard)',
                help: 'Already-compressed formats and data that does not shrink are stored raw automatically.',
              ),
              Wrap(
                spacing: 16,
                runSpacing: 4,
                children: [
                  SizedBox(
                    width: 240,
                    child: _number(
                      'compression',
                      'min_size',
                      'Store smaller files uncompressed',
                      help: 'e.g. 64 (bytes) or 1KiB',
                    ),
                  ),
                  SizedBox(
                    width: 520,
                    child: _number(
                      'compression',
                      'skip_extensions',
                      'Never compress these file types',
                      help: 'Comma-separated, e.g. .zip, .jpg, .mp4 (already compressed)',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                'Compression level: $level  (1 = fastest, 3 = default, 19 = archival)',
              ),
              Slider(
                value: level.toDouble().clamp(1, 19),
                min: 1,
                max: 19,
                divisions: 18,
                label: '$level',
                onChanged: (v) => _set('compression', 'level', v.round()),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Chunk deduplication',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _switch(
                'chunking',
                'enabled',
                'Split large files into chunks and store each chunk once',
                help:
                    'Saves space when big files change only in places (VM disks, databases, large binaries). '
                    'Whole-file deduplication is always on.',
              ),
              Wrap(
                spacing: 16,
                runSpacing: 4,
                children: [
                  SizedBox(
                    width: 240,
                    child: _number(
                      'chunking',
                      'chunk_size',
                      'Chunk size',
                      help: 'e.g. 4MiB',
                    ),
                  ),
                  SizedBox(
                    width: 240,
                    child: _number(
                      'chunking',
                      'min_file_size',
                      'Only for files at least this big',
                      help: 'e.g. 16MiB',
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Retention policy',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _switch(
                'retention',
                'keep_all',
                'Keep all versions',
                help:
                    'On: nothing is ever removed (except to stay under the storage quota). '
                    'Off: an older version is kept only if at least one rule below keeps it. '
                    'Always kept either way: the latest version of every file, the last content of deleted files, '
                    'and versions in snapshots.',
              ),
              Builder(
                builder: (context) {
                  final rulesOn =
                      !((_get('retention', 'keep_all') as bool?) ?? true);
                  return Wrap(
                    spacing: 16,
                    runSpacing: 4,
                    children: [
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'keep_last',
                          'Last N versions of each file',
                          help: 'e.g. 20 · empty = no rule',
                          enabled: rulesOn,
                        ),
                      ),
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'keep_days',
                          'Every version from the last N days',
                          help: 'e.g. 30 · empty = no rule',
                          enabled: rulesOn,
                        ),
                      ),
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'daily_days',
                          'One version per day, for N days',
                          help: 'e.g. 90 · empty = no rule',
                          enabled: rulesOn,
                        ),
                      ),
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'weekly_weeks',
                          'One version per week, for N weeks',
                          help: 'e.g. 52 · empty = no rule',
                          enabled: rulesOn,
                        ),
                      ),
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'max_storage_bytes',
                          'Storage quota (total size)',
                          help: 'e.g. 50GB · oldest unprotected versions go first · empty = no limit',
                        ),
                      ),
                      SizedBox(
                        width: 240,
                        child: _number(
                          'retention',
                          'interval_seconds',
                          'Retention interval (seconds)',
                          help: '86400 = daily (default)\n43200 = every 12 h · 604800 = weekly\nFirst run: 10 min after the daemon starts',
                        ),
                      ),
                    ],
                  );
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Monitoring',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 16,
                children: [
                  SizedBox(
                    width: 260,
                    child: _number(
                      'monitor',
                      'reconcile_interval_seconds',
                      'Full safety scan interval (seconds)',
                      help: '3600 = hourly (default)',
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: _number(
                      'monitor',
                      'polling_interval_seconds',
                      'Polling interval (seconds)',
                      help: 'Only used in polling mode · default 10',
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: _number(
                      'capture',
                      'max_file_size',
                      'Maximum file size',
                      help: 'current ${formatBytes(maxFile)}; e.g. 2GB',
                    ),
                  ),
                ],
              ),
              _switch(
                'monitor',
                'initial_scan',
                'Scan all folders when the daemon starts',
                help: 'Catches changes made while Undo was not running. Recommended.',
              ),
              _switch(
                'monitor',
                'force_polling',
                'Use polling instead of native notifications',
                help: 'Slower; for network shares or filesystems without change notifications.',
              ),
              _switch(
                'monitor',
                'exclude_hidden',
                'Exclude hidden files and folders',
              ),
              _switch(
                'monitor',
                'follow_symlinks',
                'Follow symbolic links that stay inside the tracked folder',
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const _ExclusionsCard(),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Daemon & performance',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _switch(
                'daemon',
                'autostart',
                'Start the daemon automatically when Undo Desktop opens',
                help: 'For starting at login use `undo service install`.',
              ),
              Wrap(
                spacing: 16,
                children: [
                  SizedBox(
                    width: 220,
                    child: _number(
                      'capture',
                      'max_concurrent',
                      'Concurrent captures',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'capture',
                      'debounce_seconds',
                      'Event debounce (s)',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'capture',
                      'stable_seconds',
                      'Stability wait (s)',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'capture',
                      'retry_seconds',
                      'Retry interval (s)',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number('capture', 'max_retries', 'Max retries'),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'monitor',
                      'event_queue_size',
                      'Event queue size',
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Maintenance schedule and logging',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 16,
                runSpacing: 4,
                children: [
                  SizedBox(
                    width: 260,
                    child: _number(
                      'daemon',
                      'gc_interval_seconds',
                      'Garbage collection interval (seconds)',
                      help: '86400 = daily (default)',
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: _number(
                      'daemon',
                      'gc_grace_seconds',
                      'Grace period before deleting unused data (seconds)',
                      help: 'Grace period before unused data is deleted · default 3600',
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: _number(
                      'daemon',
                      'verify_interval_seconds',
                      'Integrity check interval (seconds)',
                      help: '0 = off (default) · e.g. 604800 = weekly',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Text(
                    'Log level',
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                  const SizedBox(width: 16),
                  AppDropdown<String>(
                    value: (_get('daemon', 'log_level') as String?) ?? 'INFO',
                    items: const [
                      DropdownMenuItem(
                        value: 'DEBUG',
                        child: Text('DEBUG (most detail)'),
                      ),
                      DropdownMenuItem(
                        value: 'INFO',
                        child: Text('INFO (default)'),
                      ),
                      DropdownMenuItem(
                        value: 'WARNING',
                        child: Text('WARNING'),
                      ),
                      DropdownMenuItem(
                        value: 'ERROR',
                        child: Text('ERROR (least)'),
                      ),
                    ],
                    onChanged: (v) {
                      if (v != null) _set('daemon', 'log_level', v);
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Local API',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'The app, the undo command and undo tui talk to the daemon through this API. '
                'Changes apply after the daemon restarts.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Wrap(
                spacing: 16,
                runSpacing: 4,
                children: [
                  SizedBox(
                    width: 200,
                    child: _number(
                      'api',
                      'port',
                      'Port',
                      help: '47821 (default) · 0 = any free port',
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: _number(
                      'api',
                      'host',
                      'Listen address',
                      help: '127.0.0.1 = this computer only',
                    ),
                  ),
                ],
              ),
              _switch(
                'api',
                'allow_remote',
                'Allow a non-loopback listen address',
                help: 'Not recommended: anyone who can reach the port and has the token could read and restore your files.',
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Appearance',
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'system',
                label: Text('System'),
                icon: Icon(Icons.brightness_auto),
              ),
              ButtonSegment(
                value: 'light',
                label: Text('Light'),
                icon: Icon(Icons.light_mode),
              ),
              ButtonSegment(
                value: 'dark',
                label: Text('Dark'),
                icon: Icon(Icons.dark_mode),
              ),
            ],
            selected: {theme},
            onSelectionChanged: (s) => _set('ui', 'theme', s.first),
          ),
        ),
        const SizedBox(height: 16),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.save),
            label: const Text('Save settings'),
          ),
        ),
      ],
    );
  }
}

class _ExclusionsCard extends ConsumerWidget {
  const _ExclusionsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exclusions = ref.watch(exclusionsProvider);
    final api = ref.read(apiProvider);
    return SectionCard(
      title: 'Exclusions',
      trailing: TextButton.icon(
        icon: const Icon(Icons.add),
        label: const Text('Add pattern'),
        onPressed: () async {
          final c = TextEditingController();
          final ok = await showDialog<bool>(
            context: context,
            builder: (ctx) => AlertDialog(
              title: const Text('Add exclusion'),
              content: SizedBox(
                width: 480,
                child: TextField(
                  controller: c,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'Pattern',
                    helperText: 'dir/ = folder name · *.log = file glob · docs/drafts = path · /abs/path',
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Add'),
                ),
              ],
            ),
          );
          if (ok == true && c.text.trim().isNotEmpty && context.mounted) {
            await runAction(
              context,
              () => api.addExclusion(c.text.trim()),
              success: 'Exclusion added',
            );
            ref.invalidate(exclusionsProvider);
          }
        },
      ),
      padding: EdgeInsets.zero,
      child: AsyncView<List<ExclusionInfo>>(
        value: exclusions,
        onRetry: () => ref.invalidate(exclusionsProvider),
        builder: (list) {
          Widget tile(ExclusionInfo e) => ListTile(
            title: Text(
              e.pattern,
              style: const TextStyle(fontFamily: 'monospace'),
            ),
            subtitle: Text(e.rootId != null ? 'root ${e.rootId}' : 'all roots'),
            trailing: e.source == 'builtin'
                ? const Tooltip(
                    message: 'Built-in, cannot be removed',
                    child: Icon(Icons.lock_outline, size: 18),
                  )
                : IconButton(
                    tooltip: 'Remove',
                    icon: const Icon(Icons.close),
                    onPressed: () async {
                      await runAction(
                        context,
                        () => api.removeExclusion(e.pattern, rootId: e.rootId),
                        success:
                            'Removed ${e.pattern}. Run a scan to capture newly included files.',
                      );
                      ref.invalidate(exclusionsProvider);
                      ref.invalidate(settingsProvider);
                    },
                  ),
          );
          // Collapsible groups, so the ~40 default patterns do not fill the page.
          final groups = <(String, String, bool, List<ExclusionInfo>)>[
            (
              'Your patterns',
              'Added by you',
              true,
              [
                for (final e in list)
                  if (e.source == 'user') e,
              ],
            ),
            (
              'Default patterns',
              'Version control, caches, temp files, package folders such as node_modules, venv and target',
              false,
              [
                for (final e in list)
                  if (e.source == 'default') e,
              ],
            ),
            (
              'Built-in',
              "Undo's own temporary files; cannot be removed",
              false,
              [
                for (final e in list)
                  if (e.source == 'builtin') e,
              ],
            ),
          ];
          return Column(
            children: [
              for (final (title, help, open, items) in groups)
                ExpansionTile(
                  initiallyExpanded: open && items.isNotEmpty,
                  shape: const Border(),
                  collapsedShape: const Border(),
                  title: Text('$title (${items.length})'),
                  subtitle: Text(
                    help,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  children: items.isEmpty
                      ? [
                          const ListTile(
                            dense: true,
                            title: Text('None yet. Use "Add pattern".'),
                          ),
                        ]
                      : [for (final e in items) tile(e)],
                ),
            ],
          );
        },
      ),
    );
  }
}
