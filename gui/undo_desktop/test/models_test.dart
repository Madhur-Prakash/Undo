import 'package:flutter_test/flutter_test.dart';
import 'package:undo_desktop/core/models/models.dart';

void main() {
  test('VersionInfo parses backend JSON', () {
    final v = VersionInfo.fromJson({
      'id': 7,
      'file_id': 1,
      'root_id': 1,
      'relative_path': 'docs/a.txt',
      'absolute_path': '/home/u/docs/a.txt',
      'operation': 'RENAME',
      'timestamp': '2024-05-01T10:00:00Z',
      'file_size': 12,
      'blob_hash': 'ab' * 32,
      'parent_version_id': 3,
      'snapshot_id': null,
      'metadata': {'from_path': 'docs/old.txt'},
    });
    expect(v.name, 'a.txt');
    expect(v.hasContent, isTrue);
    expect(v.metadata['from_path'], 'docs/old.txt');
    expect(v.timestamp.toUtc(), DateTime.utc(2024, 5, 1, 10));
  });

  test('RestoreResult counts writes', () {
    final r = RestoreResult.fromJson({
      'dry_run': true,
      'items': [
        {'relative_path': 'a', 'destination': '/x/a', 'action': 'create', 'version_id': 1, 'size': 3, 'detail': null},
        {'relative_path': 'b', 'destination': '/x/b', 'action': 'conflict', 'version_id': 2, 'size': 4, 'detail': 'exists'},
      ],
      'created': 1,
      'overwritten': 0,
      'identical': 0,
      'conflicts': 1,
      'errors': 0,
    });
    expect(r.writes, 1);
    expect(r.items.last.action, 'conflict');
  });

  test('DELETE version has no content', () {
    final v = VersionInfo.fromJson({
      'id': 9, 'file_id': 1, 'root_id': 1, 'relative_path': 'a', 'absolute_path': '/a',
      'operation': 'DELETE', 'timestamp': '2024-05-01T10:00:00Z', 'file_size': 0, 'blob_hash': null,
    });
    expect(v.hasContent, isFalse);
  });
}
