import 'package:flutter_test/flutter_test.dart';
import 'package:undo_desktop/core/util/format.dart';

void main() {
  test('formatBytes uses binary units', () {
    expect(formatBytes(null), '—');
    expect(formatBytes(512), '512 B');
    expect(formatBytes(1536), '1.5 KiB');
    expect(formatBytes(5 * 1024 * 1024), '5.0 MiB');
  });

  test('percent handles zero totals', () {
    expect(percent(1, 0), '0%');
    expect(percent(1, 4), '25.0%');
  });

  test('formatRelative', () {
    final now = DateTime(2024, 1, 1, 12);
    expect(formatRelative(null), 'never');
    expect(formatRelative(now.subtract(const Duration(minutes: 5)), now: now), '5 min ago');
    expect(formatRelative(now.subtract(const Duration(hours: 3)), now: now), '3 h ago');
  });

  test('shortHash', () {
    expect(shortHash('0123456789abcdef'), '0123456789ab');
    expect(shortHash(null), '—');
  });
}
