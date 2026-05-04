import 'package:cloud_firestore/cloud_firestore.dart';

enum LocationTrigger { onExit, onEnter }

class Task {
  final String id;
  final String title;
  final String notes;
  final DateTime? dueDate;
  final DateTime? reminderTime;
  final bool isCompleted;
  // Location-based reminder fields
  final String? locationName;
  final double? latitude;
  final double? longitude;
  final LocationTrigger? locationTrigger;

  Task({
    required this.id,
    required this.title,
    this.notes = '',
    this.dueDate,
    this.reminderTime,
    this.isCompleted = false,
    this.locationName,
    this.latitude,
    this.longitude,
    this.locationTrigger,
  });

  /// Whether this task has a geofence-based reminder attached.
  bool get hasLocationReminder =>
      locationName != null && latitude != null && longitude != null;

  Task copyWith({
    String? id,
    String? title,
    String? notes,
    DateTime? dueDate,
    DateTime? reminderTime,
    bool? isCompleted,
    String? locationName,
    double? latitude,
    double? longitude,
    LocationTrigger? locationTrigger,
  }) {
    return Task(
      id: id ?? this.id,
      title: title ?? this.title,
      notes: notes ?? this.notes,
      dueDate: dueDate ?? this.dueDate,
      reminderTime: reminderTime ?? this.reminderTime,
      isCompleted: isCompleted ?? this.isCompleted,
      locationName: locationName ?? this.locationName,
      latitude: latitude ?? this.latitude,
      longitude: longitude ?? this.longitude,
      locationTrigger: locationTrigger ?? this.locationTrigger,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'title': title,
      'notes': notes,
      'dueDate': dueDate?.toIso8601String(),
      'reminderTime': reminderTime?.toIso8601String(),
      'isCompleted': isCompleted,
      if (locationName != null) 'locationName': locationName,
      if (latitude != null) 'latitude': latitude,
      if (longitude != null) 'longitude': longitude,
      if (locationTrigger != null)
        'locationTrigger':
            locationTrigger == LocationTrigger.onExit ? 'ON_EXIT' : 'ON_ENTER',
    };
  }

  factory Task.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(dynamic value) {
      if (value == null) return null;
      if (value is Timestamp) return value.toDate();
      if (value is String) return DateTime.tryParse(value);
      return null;
    }

    LocationTrigger? parseTrigger(dynamic value) {
      if (value == null) return null;
      if (value is String) {
        if (value == 'ON_EXIT') return LocationTrigger.onExit;
        if (value == 'ON_ENTER') return LocationTrigger.onEnter;
      }
      return null;
    }

    return Task(
      id: json['id'],
      title: json['title'],
      notes: json['notes'] ?? '',
      dueDate: parseDate(json['dueDate']),
      reminderTime: parseDate(json['reminderTime']),
      isCompleted: json['isCompleted'] ?? false,
      locationName: json['locationName'],
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      locationTrigger: parseTrigger(json['locationTrigger']),
    );
  }
}
