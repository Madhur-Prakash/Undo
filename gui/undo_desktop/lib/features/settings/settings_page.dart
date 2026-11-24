// Settings editor. Every value is validated and persisted by the backend.
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

  TextEditingController _controller(String section, String key) =>
      _text.putIfAbsent('$section.$key', () {
        final v = _get(section, key);
        return TextEditingController(text: v == null ? '' : v.toString());
      });

  Map<String, dynamic> _changes() {
    final out = <String, dynamic>{};
    for (final entry in _text.entries) {
      final parts = entry.key.split('.');
      final text = entry.value.text.trim();
      final original = (widget.initial[parts[0]] as Map)[parts[1]];
      if (text != (original?.toString() ?? '')) {
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

  Widget _number(String section, String key, String label, {String? help}) =>
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: TextField(
          controller: _controller(section, key),
          decoration: InputDecoration(labelText: label, helperText: help),
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
          title: 'Retention policy',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _switch(
                'retention',
                'keep_all',
                'Keep all versions',
                help:
                    'When off, a version is kept if any rule below keeps it. The latest version of every file, '
                    'the last content of deleted files and snapshot versions are always kept.',
              ),
              Wrap(
                spacing: 16,
                children: [
                  SizedBox(
                    width: 220,
                    child: _number(
                      'retention',
                      'keep_last',
                      'Keep last N versions per file',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'retention',
                      'keep_days',
                      'Keep everything for N days',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'retention',
                      'daily_days',
                      'Keep daily versions for N days',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'retention',
                      'weekly_weeks',
                      'Keep weekly versions for N weeks',
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _number(
                      'retention',
                      'max_storage_bytes',
                      'Storage quota',
                      help: 'e.g. 50GB; empty = none',
                    ),
                  ),
                ],
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
                      'Reconciliation interval (seconds)',
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
        builder: (list) => Column(
          children: [
            for (final e in list)
              ListTile(
                title: Text(
                  e.pattern,
                  style: const TextStyle(fontFamily: 'monospace'),
                ),
                subtitle: Text(
                  '${e.source}${e.rootId != null ? ' · root ${e.rootId}' : ' · all roots'}',
                ),
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
                            () => api.removeExclusion(
                              e.pattern,
                              rootId: e.rootId,
                            ),
                            success:
                                'Removed ${e.pattern}. Run a scan to capture newly included files.',
                          );
                          ref.invalidate(exclusionsProvider);
                          ref.invalidate(settingsProvider);
                        },
                      ),
              ),
          ],
        ),
      ),
    );
  }
}
