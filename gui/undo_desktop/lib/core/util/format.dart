import 'package:intl/intl.dart';

String formatBytes(int? bytes) {
  if (bytes == null) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  var value = bytes.toDouble();
  var unit = 0;
  while (value.abs() >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return unit == 0 ? '$bytes B' : '${value.toStringAsFixed(1)} ${units[unit]}';
}

final _dateTime = DateFormat('yyyy-MM-dd HH:mm:ss');

String formatDateTime(DateTime? dt) =>
    dt == null ? '—' : _dateTime.format(dt.toLocal());

String formatRelative(DateTime? dt, {DateTime? now}) {
  if (dt == null) return 'never';
  final diff = (now ?? DateTime.now()).difference(dt);
  if (diff.inSeconds < 0) return 'just now';
  if (diff.inSeconds < 60) return '${diff.inSeconds}s ago';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) return '${diff.inHours} h ago';
  if (diff.inDays < 30) return '${diff.inDays} d ago';
  return formatDateTime(dt);
}

String formatDuration(double seconds) {
  final d = Duration(seconds: seconds.round());
  if (d.inDays > 0) return '${d.inDays}d ${d.inHours % 24}h';
  if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes % 60}m';
  if (d.inMinutes > 0) return '${d.inMinutes}m ${d.inSeconds % 60}s';
  return '${d.inSeconds}s';
}

String percent(int part, int whole) =>
    whole <= 0 ? '0%' : '${(part / whole * 100).toStringAsFixed(1)}%';

String shortHash(String? h) =>
    h == null ? '—' : (h.length > 12 ? h.substring(0, 12) : h);
