// Typed client for the Undo local API (/api/v1). All business logic lives in the backend.
import 'package:dio/dio.dart';

import '../models/models.dart';
import 'discovery.dart';

class ApiException implements Exception {
  ApiException(this.code, this.message, {this.status});
  final String code;
  final String message;
  final int? status;

  bool get isConnection => code == 'connection';

  @override
  String toString() => message;
}

class UndoApi {
  UndoApi(this.endpoint)
      : _dio = Dio(BaseOptions(
          baseUrl: endpoint.baseUrl,
          headers: {'Authorization': 'Bearer ${endpoint.token}'},
          connectTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(minutes: 30),
        ));

  final DaemonEndpoint endpoint;
  final Dio _dio;

  Future<T> _req<T>(String method, String path, {Map<String, dynamic>? query, Object? body}) async {
    try {
      final resp = await _dio.request<T>(
        path,
        data: body,
        queryParameters: query?..removeWhere((_, v) => v == null),
        options: Options(method: method),
      );
      return resp.data as T;
    } on DioException catch (e) {
      final data = e.response?.data;
      if (data is Map && data['error'] is Map) {
        final err = data['error'] as Map;
        throw ApiException(err['code'] as String? ?? 'error', err['message'] as String? ?? 'Request failed',
            status: e.response?.statusCode);
      }
      if (e.response == null) {
        throw ApiException('connection', 'Cannot reach the Undo daemon (${e.message ?? e.type.name})');
      }
      throw ApiException('http_${e.response?.statusCode}', 'Request failed: ${e.response?.statusCode}',
          status: e.response?.statusCode);
    }
  }

  Map<String, dynamic> _m(Object? v) => v as Map<String, dynamic>;
  List<Map<String, dynamic>> _l(Object? v) => (v as List).cast<Map<String, dynamic>>();

  // ----------------------------------------------------------------- status
  Future<StatusInfo> status() async => StatusInfo.fromJson(_m(await _req<Object>('GET', '/status')));
  Future<void> shutdown() => _req<Object>('POST', '/daemon/shutdown');

  // ----------------------------------------------------------------- roots
  Future<List<RootInfo>> roots() async => _l(await _req<Object>('GET', '/roots')).map(RootInfo.fromJson).toList();
  Future<RootInfo> addRoot(String path, {bool scan = true}) async =>
      RootInfo.fromJson(_m(_m(await _req<Object>('POST', '/roots', body: {'path': path, 'scan': scan}))['root']));
  Future<RootInfo> setRootEnabled(int id, bool enabled) async =>
      RootInfo.fromJson(_m(await _req<Object>('PATCH', '/roots/$id', body: {'enabled': enabled})));
  Future<void> removeRoot(int id, {bool purge = false}) =>
      _req<Object>('DELETE', '/roots/$id', query: {'purge': purge});
  Future<List<ReconcileReport>> scan({Object? target, bool deep = false}) async =>
      _l(await _req<Object>('POST', '/scan', body: {'target': target, 'deep': deep}))
          .map(ReconcileReport.fromJson)
          .toList();

  // ----------------------------------------------------------------- files & history
  Future<FilePage> files({String? query, bool includeDeleted = false, int? rootId, int limit = 500, int offset = 0}) async =>
      FilePage.fromJson(_m(await _req<Object>('GET', '/files', query: {
        'query': (query == null || query.isEmpty) ? null : query,
        'include_deleted': includeDeleted,
        'root_id': rootId,
        'limit': limit,
        'offset': offset,
      })));
  Future<FileHistory> fileHistory(int fileId) async =>
      FileHistory.fromJson(_m(await _req<Object>('GET', '/history/files/$fileId')));
  Future<List<VersionInfo>> activity({int limit = 200}) async =>
      _l(await _req<Object>('GET', '/history/log', query: {'limit': limit})).map(VersionInfo.fromJson).toList();
  Future<VersionDetail> version(int id) async => VersionDetail.fromJson(_m(await _req<Object>('GET', '/versions/$id')));
  Future<VersionContent> preview(int id) async =>
      VersionContent.fromJson(_m(await _req<Object>('GET', '/versions/$id/preview')));
  Future<VersionDiff> diff(int a, int b) async =>
      VersionDiff.fromJson(_m(await _req<Object>('GET', '/versions/diff', query: {'a': a, 'b': b})));

  // ----------------------------------------------------------------- restore
  Future<RestoreResult> restoreVersion(int versionId, {String? destination, bool overwrite = false, bool dryRun = true}) async =>
      RestoreResult.fromJson(_m(await _req<Object>('POST', '/restore/version', body: {
        'version_id': versionId,
        'destination': destination,
        'overwrite': overwrite,
        'dry_run': dryRun,
      })));
  Future<RestoreResult> recover(String path, {String? destination, bool overwrite = false, bool dryRun = true}) async =>
      RestoreResult.fromJson(_m(await _req<Object>('POST', '/restore/recover', body: {
        'path': path,
        'destination': destination,
        'overwrite': overwrite,
        'dry_run': dryRun,
      })));

  // ----------------------------------------------------------------- snapshots
  Future<List<SnapshotInfo>> snapshots() async =>
      _l(await _req<Object>('GET', '/snapshots')).map(SnapshotInfo.fromJson).toList();
  Future<SnapshotInfo> createSnapshot(String name, {String? description, int? rootId}) async =>
      SnapshotInfo.fromJson(_m(await _req<Object>('POST', '/snapshots',
          body: {'name': name, 'description': description, 'root': rootId, 'scan': true})));
  Future<SnapshotDiff> diffSnapshots(int a, int b) async =>
      SnapshotDiff.fromJson(_m(await _req<Object>('GET', '/snapshots/$a/diff/$b')));
  Future<RestoreResult> restoreSnapshot(int id, {String? destination, bool overwrite = false, bool dryRun = true}) async =>
      RestoreResult.fromJson(_m(await _req<Object>('POST', '/snapshots/$id/restore',
          body: {'destination': destination, 'overwrite': overwrite, 'dry_run': dryRun})));
  Future<void> deleteSnapshot(int id) => _req<Object>('DELETE', '/snapshots/$id');

  // ----------------------------------------------------------------- storage
  Future<StorageStats> storageStats() async => StorageStats.fromJson(_m(await _req<Object>('GET', '/storage/stats')));
  Future<VerifyReport> verify({bool full = true}) async =>
      VerifyReport.fromJson(_m(await _req<Object>('POST', '/storage/verify', body: {'full': full, 'repair': true})));
  Future<GcReport> gc({required bool dryRun}) async =>
      GcReport.fromJson(_m(await _req<Object>('POST', '/storage/gc', body: {'dry_run': dryRun})));
  Future<RetentionReport> retention({required bool dryRun}) async =>
      RetentionReport.fromJson(_m(await _req<Object>('POST', '/storage/retention', body: {'dry_run': dryRun})));

  // ----------------------------------------------------------------- settings
  Future<Map<String, dynamic>> settings() async => _m(await _req<Object>('GET', '/settings'));
  Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> values) async =>
      _m(await _req<Object>('PATCH', '/settings', body: values));
  Future<List<ExclusionInfo>> exclusions() async =>
      _l(await _req<Object>('GET', '/exclusions')).map(ExclusionInfo.fromJson).toList();
  Future<void> addExclusion(String pattern) => _req<Object>('POST', '/exclusions', body: {'pattern': pattern});
  Future<void> removeExclusion(String pattern, {int? rootId}) =>
      _req<Object>('POST', '/exclusions/remove', body: {'pattern': pattern, 'root': rootId});
}
