import 'dart:convert';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../models/feature_vector.dart';
import '../models/recording_session.dart';
import '../models/sensor_sample.dart';

/// Handles saving, streaming, listing, and exporting real sensor telemetry data.
class SessionStorageService {
  static const String folderName = 'JarvisTelemetry';
  static Directory? _cachedDir;

  /// Resolves the primary directory accessible by phone file managers.
  static Future<Directory> getStorageDir() async {
    if (_cachedDir != null && await _cachedDir!.exists()) {
      return _cachedDir!;
    }

    Directory? dir;

    // 1. Try public Download folder on Android (directly visible in phone File Manager)
    try {
      final publicDownload = Directory('/storage/emulated/0/Download/$folderName');
      if (await publicDownload.exists()) {
        _cachedDir = publicDownload;
        return publicDownload;
      } else {
        await publicDownload.create(recursive: true);
        _cachedDir = publicDownload;
        return publicDownload;
      }
    } catch (_) {
      // Fall through if scoped storage blocks direct path
    }

    // 2. Try getExternalStorageDirectory (visible over USB and in file manager Android/data/...)
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null) {
        dir = Directory('${ext.path}/$folderName');
        if (!await dir.exists()) await dir.create(recursive: true);
        _cachedDir = dir;
        return dir;
      }
    } catch (_) {}

    // 3. Fallback to app documents
    final appDocs = await getApplicationDocumentsDirectory();
    dir = Directory('${appDocs.path}/$folderName');
    if (!await dir.exists()) await dir.create(recursive: true);
    _cachedDir = dir;
    return dir;
  }

  /// Create and prepare files for a new recording session.
  static Future<({File csvFile, File jsonFile, IOSink csvSink})>
      createSessionFiles(String sessionId) async {
    final dir = await getStorageDir();
    final csvPath = '${dir.path}/$sessionId.csv';
    final jsonPath = '${dir.path}/${sessionId}_summary.json';

    final csvFile = File(csvPath);
    final jsonFile = File(jsonPath);

    // Initialize CSV with column headers
    final sink = csvFile.openWrite(mode: FileMode.writeOnly);
    sink.writeln(SensorSample.csvHeader);

    return (csvFile: csvFile, jsonFile: jsonFile, csvSink: sink);
  }

  /// Finalize and save the session summary JSON file with High & Low telemetry metadata.
  static Future<RecordingSession> finalizeSession({
    required String sessionId,
    required DateTime startTime,
    required DateTime endTime,
    required String label,
    required String mountPosition,
    required String roadCondition,
    required int sampleCount,
    required File csvFile,
    required File jsonFile,
    required IOSink csvSink,
    FeatureVector? summaryFeatures,
    Map<String, dynamic>? journeyGps,
  }) async {
    await csvSink.flush();
    await csvSink.close();

    final durationSeconds =
        endTime.difference(startTime).inMilliseconds / 1000.0;
    final csvSizeBytes = await csvFile.length();

    final session = RecordingSession(
      id: sessionId,
      startTime: startTime,
      endTime: endTime,
      label: label,
      mountPosition: mountPosition,
      roadCondition: roadCondition,
      sampleCount: sampleCount,
      durationSeconds: durationSeconds,
      csvFilePath: csvFile.path,
      jsonFilePath: jsonFile.path,
      csvSizeBytes: csvSizeBytes,
    );

    final summaryPayload = {
      ...session.toJson(),
      'telemetry_modes': {
        'high_telemetry': {
          'status': 'RECORDED',
          'imu_sampling_rate_hz': 50,
          'gps_accuracy_mode': 'HIGH_PRECISION_1M',
          'total_samples': sampleCount,
          'csv_file_path': csvFile.path,
          'csv_size_bytes': csvSizeBytes,
        },
        'low_telemetry': {
          'status': 'EDGE_EXTRACTED',
          'vibration_features':
              summaryFeatures?.toBackendFeatureSummary() ?? {},
          'journey_gps': journeyGps ?? {},
        },
      },
      'feature_summary': summaryFeatures?.toBackendFeatureSummary() ?? {},
      'journey_gps': journeyGps ?? {},
    };

    await jsonFile.writeAsString(
      const JsonEncoder.withIndent('  ').convert(summaryPayload),
    );

    return session;
  }

  /// Lists all recorded sessions discovered in storage.
  static Future<List<RecordingSession>> listSessions() async {
    try {
      final dir = await getStorageDir();
      final entities = dir.listSync();
      final sessions = <RecordingSession>[];

      for (final entity in entities) {
        if (entity is File && entity.path.endsWith('_summary.json')) {
          try {
            final content = await entity.readAsString();
            final data = jsonDecode(content) as Map<String, dynamic>;
            sessions.add(RecordingSession.fromJson(data));
          } catch (_) {}
        }
      }

      // Sort newest first
      sessions.sort((a, b) => b.startTime.compareTo(a.startTime));
      return sessions;
    } catch (_) {
      return [];
    }
  }

  /// Delete a recorded session and all associated files.
  static Future<void> deleteSession(RecordingSession session) async {
    try {
      final csv = File(session.csvFilePath);
      if (await csv.exists()) await csv.delete();
      final json = File(session.jsonFilePath);
      if (await json.exists()) await json.delete();
    } catch (_) {}
  }

  /// Share CSV or JSON using Android's system share sheet.
  static Future<void> shareSession(RecordingSession session) async {
    final filesToShare = <XFile>[];
    if (await File(session.csvFilePath).exists()) {
      filesToShare.add(XFile(session.csvFilePath, name: '${session.id}.csv'));
    }
    if (await File(session.jsonFilePath).exists()) {
      filesToShare
          .add(XFile(session.jsonFilePath, name: '${session.id}_summary.json'));
    }

    if (filesToShare.isNotEmpty) {
      await SharePlus.instance.share(
        ShareParams(
          files: filesToShare,
          subject: 'Jarvis Telemetry: ${session.label} (${session.id})',
          text:
              'Recorded ${session.sampleCount} samples of ${session.label} on ${session.roadCondition}.',
        ),
      );
    }
  }
}
