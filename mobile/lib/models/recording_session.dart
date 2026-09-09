import 'dart:convert';

/// Represents a recorded data collection session stored on disk.
class RecordingSession {
  final String id;
  final DateTime startTime;
  final DateTime? endTime;
  final String label;
  final String mountPosition;
  final String roadCondition;
  final int sampleCount;
  final double durationSeconds;
  final String csvFilePath;
  final String jsonFilePath;
  final int csvSizeBytes;

  RecordingSession({
    required this.id,
    required this.startTime,
    this.endTime,
    required this.label,
    required this.mountPosition,
    required this.roadCondition,
    required this.sampleCount,
    required this.durationSeconds,
    required this.csvFilePath,
    required this.jsonFilePath,
    required this.csvSizeBytes,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'start_time': startTime.toIso8601String(),
        'end_time': endTime?.toIso8601String(),
        'label': label,
        'mount_position': mountPosition,
        'road_condition': roadCondition,
        'sample_count': sampleCount,
        'duration_seconds': durationSeconds,
        'csv_file_path': csvFilePath,
        'json_file_path': jsonFilePath,
        'csv_size_bytes': csvSizeBytes,
      };

  factory RecordingSession.fromJson(Map<String, dynamic> json) =>
      RecordingSession(
        id: json['id'] as String,
        startTime: DateTime.parse(json['start_time'] as String),
        endTime: json['end_time'] != null
            ? DateTime.parse(json['end_time'] as String)
            : null,
        label: json['label'] as String? ?? 'UNKNOWN',
        mountPosition: json['mount_position'] as String? ?? 'UNKNOWN',
        roadCondition: json['road_condition'] as String? ?? 'UNKNOWN',
        sampleCount: json['sample_count'] as int? ?? 0,
        durationSeconds:
            (json['duration_seconds'] as num?)?.toDouble() ?? 0.0,
        csvFilePath: json['csv_file_path'] as String? ?? '',
        jsonFilePath: json['json_file_path'] as String? ?? '',
        csvSizeBytes: json['csv_size_bytes'] as int? ?? 0,
      );

  String get formattedSize {
    if (csvSizeBytes < 1024) return '$csvSizeBytes B';
    if (csvSizeBytes < 1024 * 1024) {
      return '${(csvSizeBytes / 1024).toStringAsFixed(1)} KB';
    }
    return '${(csvSizeBytes / (1024 * 1024)).toStringAsFixed(2)} MB';
  }

  String get formattedDuration {
    final mins = (durationSeconds ~/ 60).toString().padLeft(2, '0');
    final secs = (durationSeconds.toInt() % 60).toString().padLeft(2, '0');
    return '$mins:$secs';
  }

  @override
  String toString() => jsonEncode(toJson());
}
