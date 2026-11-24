// Data classes mirroring the backend's pydantic models (undo_core/domain.py).

DateTime? _dt(Object? v) =>
    v == null ? null : DateTime.parse(v as String).toLocal();
int _i(Object? v) => v == null ? 0 : (v as num).toInt();
int? _in(Object? v) => v == null ? null : (v as num).toInt();
List<T> _list<T>(Object? v, T Function(Map<String, dynamic>) f) =>
    (v as List? ?? const []).map((e) => f(e as Map<String, dynamic>)).toList();

class WatcherInfo {
  WatcherInfo.fromJson(Map<String, dynamic> j)
    : rootId = _i(j['root_id']),
      path = j['path'] as String,
      mode = j['mode'] as String,
      healthy = j['healthy'] as bool,
      error = j['error'] as String?;
  final int rootId;
  final String path;
  final String mode;
  final bool healthy;
  final String? error;
}

class HealthInfo {
  HealthInfo.fromJson(Map<String, dynamic> j)
    : pid = _i(j['pid']),
      version = j['version'] as String,
      uptimeSeconds = (j['uptime_seconds'] as num).toDouble(),
      apiUrl = j['api_url'] as String?,
      watchers = _list(j['watchers'], WatcherInfo.fromJson),
      queueDepth = _i(j['queue_depth']),
      queueCapacity = _i(j['queue_capacity']),
      pendingCaptures = _i(j['pending_captures']),
      eventsReceived = _i(j['events_received']),
      eventsDropped = _i(j['events_dropped']),
      captures = (j['captures'] as Map? ?? {}).map(
        (k, v) => MapEntry(k as String, _i(v)),
      ),
      lastReconcileAt = _dt(j['last_reconcile_at']),
      reconciling = j['reconciling'] as bool? ?? false,
      recentErrors = (j['recent_errors'] as List? ?? const []).cast<String>();
  final int pid;
  final String version;
  final double uptimeSeconds;
  final String? apiUrl;
  final List<WatcherInfo> watchers;
  final int queueDepth;
  final int queueCapacity;
  final int pendingCaptures;
  final int eventsReceived;
  final int eventsDropped;
  final Map<String, int> captures;
  final DateTime? lastReconcileAt;
  final bool reconciling;
  final List<String> recentErrors;
}

class StatusInfo {
  StatusInfo.fromJson(Map<String, dynamic> j)
    : dataDir = j['data_dir'] as String,
      daemonRunning = j['daemon_running'] as bool,
      daemon = j['daemon'] == null
          ? null
          : HealthInfo.fromJson(j['daemon'] as Map<String, dynamic>),
      rootCount = _i(j['root_count']),
      fileCount = _i(j['file_count']),
      deletedFileCount = _i(j['deleted_file_count']),
      versionCount = _i(j['version_count']),
      snapshotCount = _i(j['snapshot_count']),
      skippedCount = _i(j['skipped_count']),
      storedBytes = _i(j['stored_bytes']),
      logicalBytes = _i(j['logical_bytes']);
  final String dataDir;
  final bool daemonRunning;
  final HealthInfo? daemon;
  final int rootCount;
  final int fileCount;
  final int deletedFileCount;
  final int versionCount;
  final int snapshotCount;
  final int skippedCount;
  final int storedBytes;
  final int logicalBytes;
}

class RootInfo {
  RootInfo.fromJson(Map<String, dynamic> j)
    : id = _i(j['id']),
      path = j['path'] as String,
      enabled = j['enabled'] as bool,
      createdAt = _dt(j['created_at'])!,
      lastScanAt = _dt(j['last_scan_at']),
      fileCount = _i(j['file_count']),
      deletedFileCount = _i(j['deleted_file_count']),
      versionCount = _i(j['version_count']),
      watchMode = j['watch_mode'] as String?;
  final int id;
  final String path;
  final bool enabled;
  final DateTime createdAt;
  final DateTime? lastScanAt;
  final int fileCount;
  final int deletedFileCount;
  final int versionCount;
  final String? watchMode;
}

class FileInfo {
  FileInfo.fromJson(Map<String, dynamic> j)
    : id = _i(j['id']),
      rootId = _i(j['root_id']),
      relativePath = j['relative_path'] as String,
      absolutePath = j['absolute_path'] as String,
      name = j['name'] as String,
      size = _in(j['size']),
      createdAt = _dt(j['created_at'])!,
      deletedAt = _dt(j['deleted_at']),
      isDeleted = j['is_deleted'] as bool,
      latestVersionId = _in(j['latest_version_id']),
      versionCount = _i(j['version_count']),
      lastModified = _dt(j['last_modified']),
      latestOperation = j['latest_operation'] as String?,
      latestTimestamp = _dt(j['latest_timestamp']);
  final int id;
  final int rootId;
  final String relativePath;
  final String absolutePath;
  final String name;
  final int? size;
  final DateTime createdAt;
  final DateTime? deletedAt;
  final bool isDeleted;
  final int? latestVersionId;
  final int versionCount;
  final DateTime? lastModified;
  final String? latestOperation;
  final DateTime? latestTimestamp;
}

class FilePage {
  FilePage.fromJson(Map<String, dynamic> j)
    : items = _list(j['items'], FileInfo.fromJson),
      total = _i(j['total']);
  final List<FileInfo> items;
  final int total;
}

class VersionInfo {
  VersionInfo.fromJson(Map<String, dynamic> j)
    : id = _i(j['id']),
      fileId = _i(j['file_id']),
      rootId = _i(j['root_id']),
      relativePath = j['relative_path'] as String,
      absolutePath = j['absolute_path'] as String,
      operation = j['operation'] as String,
      timestamp = _dt(j['timestamp'])!,
      fileSize = _i(j['file_size']),
      blobHash = j['blob_hash'] as String?,
      parentVersionId = _in(j['parent_version_id']),
      metadata = (j['metadata'] as Map?)?.cast<String, dynamic>() ?? const {};
  final int id;
  final int fileId;
  final int rootId;
  final String relativePath;
  final String absolutePath;
  final String operation;
  final DateTime timestamp;
  final int fileSize;
  final String? blobHash;
  final int? parentVersionId;
  final Map<String, dynamic> metadata;

  bool get hasContent => blobHash != null;
  String get name => relativePath.split('/').last;
}

class PathHistoryInfo {
  PathHistoryInfo.fromJson(Map<String, dynamic> j)
    : relativePath = j['relative_path'] as String,
      validFrom = _dt(j['valid_from'])!,
      validTo = _dt(j['valid_to']);
  final String relativePath;
  final DateTime validFrom;
  final DateTime? validTo;
}

class FileHistory {
  FileHistory.fromJson(Map<String, dynamic> j)
    : file = FileInfo.fromJson(j['file'] as Map<String, dynamic>),
      versions = _list(j['versions'], VersionInfo.fromJson),
      paths = _list(j['paths'], PathHistoryInfo.fromJson);
  final FileInfo file;
  final List<VersionInfo> versions;
  final List<PathHistoryInfo> paths;
}

class BlobInfo {
  BlobInfo.fromJson(Map<String, dynamic> j)
    : hash = j['hash'] as String,
      originalSize = _i(j['original_size']),
      compressedSize = _i(j['compressed_size']),
      compressionAlgorithm = j['compression_algorithm'] as String,
      compressionLevel = _in(j['compression_level']),
      storageKind = j['storage_kind'] as String,
      status = j['status'] as String,
      verifiedAt = _dt(j['verified_at']),
      chunkCount = _i(j['chunk_count']),
      referenceCount = _i(j['reference_count']);
  final String hash;
  final int originalSize;
  final int compressedSize;
  final String compressionAlgorithm;
  final int? compressionLevel;
  final String storageKind;
  final String status;
  final DateTime? verifiedAt;
  final int chunkCount;
  final int referenceCount;
}

class VersionDetail {
  VersionDetail.fromJson(Map<String, dynamic> j)
    : version = VersionInfo.fromJson(j['version'] as Map<String, dynamic>),
      file = FileInfo.fromJson(j['file'] as Map<String, dynamic>),
      blob = j['blob'] == null
          ? null
          : BlobInfo.fromJson(j['blob'] as Map<String, dynamic>),
      previousVersionId = _in(j['previous_version_id']),
      nextVersionId = _in(j['next_version_id']),
      isText = j['is_text'] as bool? ?? false;
  final VersionInfo version;
  final FileInfo file;
  final BlobInfo? blob;
  final int? previousVersionId;
  final int? nextVersionId;
  final bool isText;
}

/// Character range [start, end) that differs inside a changed line.
typedef DiffSpan = (int, int);

List<DiffSpan> _spans(Object? v) => [
  for (final s in (v as List?) ?? const [])
    (((s as List)[0] as num).toInt(), (s[1] as num).toInt()),
];

/// One row of a side-by-side diff: the old line (a) next to the new line (b).
class DiffRow {
  DiffRow.fromJson(Map<String, dynamic> j)
    : kind = j['kind'] as String,
      aNo = _in(j['a_no']),
      aText = j['a_text'] as String?,
      bNo = _in(j['b_no']),
      bText = j['b_text'] as String?,
      aSpans = _spans(j['a_spans']),
      bSpans = _spans(j['b_spans']);
  final String kind; // equal | delete | insert | change
  final int? aNo;
  final String? aText;
  final int? bNo;
  final String? bText;
  final List<DiffSpan> aSpans;
  final List<DiffSpan> bSpans;
}

class DiffHunk {
  DiffHunk.fromJson(Map<String, dynamic> j)
    : aStart = _i(j['a_start']),
      aCount = _i(j['a_count']),
      bStart = _i(j['b_start']),
      bCount = _i(j['b_count']),
      rows = [
        for (final r in (j['rows'] as List))
          DiffRow.fromJson((r as Map).cast<String, dynamic>()),
      ];
  final int aStart;
  final int aCount;
  final int bStart;
  final int bCount;
  final List<DiffRow> rows;

  String get header => '@@ -$aStart,$aCount +$bStart,$bCount @@';
}

class VersionDiff {
  VersionDiff.fromJson(Map<String, dynamic> j)
    : a = VersionInfo.fromJson((j['a'] as Map).cast<String, dynamic>()),
      b = VersionInfo.fromJson((j['b'] as Map).cast<String, dynamic>()),
      identical = j['identical'] as bool,
      isText = j['is_text'] as bool,
      diff = j['diff'] as String?,
      hunks = [
        for (final h in (j['hunks'] as List?) ?? const [])
          DiffHunk.fromJson((h as Map).cast<String, dynamic>()),
      ],
      added = _i(j['added']),
      removed = _i(j['removed']),
      truncated = j['truncated'] as bool? ?? false,
      sizeDelta = _i(j['size_delta']),
      note = j['note'] as String?;
  final VersionInfo a;
  final VersionInfo b;
  final bool identical;
  final bool isText;
  final String? diff;
  final List<DiffHunk> hunks;
  final int added;
  final int removed;
  final bool truncated;
  final int sizeDelta;
  final String? note;
}

class VersionContent {
  VersionContent.fromJson(Map<String, dynamic> j)
    : isText = j['is_text'] as bool,
      size = _i(j['size']),
      truncated = j['truncated'] as bool,
      text = j['text'] as String?;
  final bool isText;
  final int size;
  final bool truncated;
  final String? text;
}

class RestoreItem {
  RestoreItem.fromJson(Map<String, dynamic> j)
    : relativePath = j['relative_path'] as String,
      destination = j['destination'] as String,
      action = j['action'] as String,
      versionId = _in(j['version_id']),
      size = _i(j['size']),
      detail = j['detail'] as String?;
  final String relativePath;
  final String destination;
  final String action;
  final int? versionId;
  final int size;
  final String? detail;
}

class RestoreResult {
  RestoreResult.fromJson(Map<String, dynamic> j)
    : dryRun = j['dry_run'] as bool,
      items = _list(j['items'], RestoreItem.fromJson),
      created = _i(j['created']),
      overwritten = _i(j['overwritten']),
      identical = _i(j['identical']),
      conflicts = _i(j['conflicts']),
      errors = _i(j['errors']),
      metadataRestored = (j['metadata_restored'] as List? ?? const [])
          .cast<String>(),
      metadataNotRestored = (j['metadata_not_restored'] as List? ?? const [])
          .cast<String>(),
      preRestoreVersions = (j['pre_restore_versions'] as List? ?? const [])
          .map(_i)
          .toList();
  final bool dryRun;
  final List<RestoreItem> items;
  final int created;
  final int overwritten;
  final int identical;
  final int conflicts;
  final int errors;
  final List<String> metadataRestored;
  final List<String> metadataNotRestored;
  final List<int> preRestoreVersions;

  int get writes => created + overwritten;
}

class SnapshotInfo {
  SnapshotInfo.fromJson(Map<String, dynamic> j)
    : id = _i(j['id']),
      name = j['name'] as String,
      description = j['description'] as String?,
      createdAt = _dt(j['created_at'])!,
      rootId = _i(j['root_id']),
      rootPath = j['root_path'] as String,
      fileCount = _i(j['file_count']),
      totalSize = _i(j['total_size']);
  final int id;
  final String name;
  final String? description;
  final DateTime createdAt;
  final int rootId;
  final String rootPath;
  final int fileCount;
  final int totalSize;
}

class SnapshotChange {
  SnapshotChange.fromJson(Map<String, dynamic> j)
    : relativePath = j['relative_path'] as String,
      aSize = _in(j['a_size']),
      bSize = _in(j['b_size']);
  final String relativePath;
  final int? aSize;
  final int? bSize;
}

class SnapshotDiff {
  SnapshotDiff.fromJson(Map<String, dynamic> j)
    : a = SnapshotInfo.fromJson(j['a'] as Map<String, dynamic>),
      b = SnapshotInfo.fromJson(j['b'] as Map<String, dynamic>),
      added = _list(j['added'], SnapshotChange.fromJson),
      removed = _list(j['removed'], SnapshotChange.fromJson),
      modified = _list(j['modified'], SnapshotChange.fromJson),
      unchanged = _i(j['unchanged']);
  final SnapshotInfo a;
  final SnapshotInfo b;
  final List<SnapshotChange> added;
  final List<SnapshotChange> removed;
  final List<SnapshotChange> modified;
  final int unchanged;
}

class StorageStats {
  StorageStats.fromJson(Map<String, dynamic> j)
    : dataDir = j['data_dir'] as String,
      blobCount = _i(j['blob_count']),
      chunkCount = _i(j['chunk_count']),
      versionCount = _i(j['version_count']),
      logicalBytes = _i(j['logical_bytes']),
      uniqueBytes = _i(j['unique_bytes']),
      storedBytes = _i(j['stored_bytes']),
      blobDiskBytes = _i(j['blob_disk_bytes']),
      databaseBytes = _i(j['database_bytes']),
      dedupSavingsBytes = _i(j['dedup_savings_bytes']),
      compressionSavingsBytes = _i(j['compression_savings_bytes']),
      totalSavingsBytes = _i(j['total_savings_bytes']),
      compressionAlgorithms = (j['compression_algorithms'] as Map? ?? {}).map(
        (k, v) => MapEntry(k as String, _i(v)),
      ),
      unhealthyBlobs = _i(j['unhealthy_blobs']),
      skippedFiles = _i(j['skipped_files']),
      lastVerifyAt = j['last_verify_at'] == null
          ? null
          : DateTime.parse('${j['last_verify_at']}Z').toLocal(),
      lastVerifyOk = j['last_verify_ok'] as bool?,
      lastGcAt = j['last_gc_at'] == null
          ? null
          : DateTime.parse('${j['last_gc_at']}Z').toLocal();
  final String dataDir;
  final int blobCount;
  final int chunkCount;
  final int versionCount;
  final int logicalBytes;
  final int uniqueBytes;
  final int storedBytes;
  final int blobDiskBytes;
  final int databaseBytes;
  final int dedupSavingsBytes;
  final int compressionSavingsBytes;
  final int totalSavingsBytes;
  final Map<String, int> compressionAlgorithms;
  final int unhealthyBlobs;
  final int skippedFiles;
  final DateTime? lastVerifyAt;
  final bool? lastVerifyOk;
  final DateTime? lastGcAt;
}

class VerifyReport {
  VerifyReport.fromJson(Map<String, dynamic> j)
    : checkedBlobs = _i(j['checked_blobs']),
      checkedChunks = _i(j['checked_chunks']),
      ok = _i(j['ok']),
      missing = (j['missing'] as List).cast<String>(),
      corrupt = (j['corrupt'] as List).cast<String>(),
      repaired = (j['repaired'] as List).cast<String>(),
      orphanFiles = (j['orphan_files'] as List).length,
      healthy = j['healthy'] as bool,
      durationSeconds = (j['duration_seconds'] as num).toDouble();
  final int checkedBlobs;
  final int checkedChunks;
  final int ok;
  final List<String> missing;
  final List<String> corrupt;
  final List<String> repaired;
  final int orphanFiles;
  final bool healthy;
  final double durationSeconds;
}

class GcReport {
  GcReport.fromJson(Map<String, dynamic> j)
    : dryRun = j['dry_run'] as bool,
      candidateBlobs = _i(j['candidate_blobs']),
      candidateChunks = _i(j['candidate_chunks']),
      reclaimableBytes = _i(j['reclaimable_bytes']),
      reclaimedBytes = _i(j['reclaimed_bytes']),
      orphanFiles = _i(j['orphan_files']),
      orphanBytes = _i(j['orphan_bytes']),
      protectedByGrace = _i(j['protected_by_grace']);
  final bool dryRun;
  final int candidateBlobs;
  final int candidateChunks;
  final int reclaimableBytes;
  final int reclaimedBytes;
  final int orphanFiles;
  final int orphanBytes;
  final int protectedByGrace;
}

class RetentionReport {
  RetentionReport.fromJson(Map<String, dynamic> j)
    : dryRun = j['dry_run'] as bool,
      versionsExamined = _i(j['versions_examined']),
      versionsRemoved = _i(j['versions_removed']),
      filesAffected = _i(j['files_affected']),
      estimatedReclaimBytes = _i(j['estimated_reclaim_bytes']);
  final bool dryRun;
  final int versionsExamined;
  final int versionsRemoved;
  final int filesAffected;
  final int estimatedReclaimBytes;
}

class ExclusionInfo {
  ExclusionInfo.fromJson(Map<String, dynamic> j)
    : id = _in(j['id']),
      pattern = j['pattern'] as String,
      rootId = _in(j['root_id']),
      source = j['source'] as String;
  final int? id;
  final String pattern;
  final int? rootId;
  final String source;
}

class ReconcileReport {
  ReconcileReport.fromJson(Map<String, dynamic> j)
    : rootPath = j['root_path'] as String,
      scanned = _i(j['scanned']),
      newFiles = _i(j['new']),
      modified = _i(j['modified']),
      deleted = _i(j['deleted']),
      renamed = _i(j['renamed']),
      skipped = _i(j['skipped']),
      failed = _i(j['failed']);
  final String rootPath;
  final int scanned;
  final int newFiles;
  final int modified;
  final int deleted;
  final int renamed;
  final int skipped;
  final int failed;
}

/// Result of removing history on purpose (a file, a folder, older versions, single versions).
class ForgetResult {
  ForgetResult.fromJson(Map<String, dynamic> j)
    : dryRun = j['dry_run'] as bool,
      target = j['target'] as String,
      before = _dt(j['before']),
      filesExamined = _i(j['files_examined']),
      filesAffected = _i(j['files_affected']),
      filesRemoved = _i(j['files_removed']),
      versionsRemoved = _i(j['versions_removed']),
      versionsKeptInSnapshots = _i(j['versions_kept_in_snapshots']),
      note = j['note'] as String?;
  final bool dryRun;
  final String target;
  final DateTime? before;
  final int filesExamined;
  final int filesAffected;
  final int filesRemoved;
  final int versionsRemoved;
  final int versionsKeptInSnapshots;
  final String? note;
}
