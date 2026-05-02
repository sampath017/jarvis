import 'package:cloud_firestore/cloud_firestore.dart';

enum Category { bike, work, garden, health, general }

class Task {
  final String id;
  final String title;
  final String notes;
  final DateTime? dueDate;
  final DateTime? reminderTime;
  final bool isCompleted;
  final Category category;

  Task({
    required this.id,
    required this.title,
    this.notes = '',
    this.dueDate,
    this.reminderTime,
    this.isCompleted = false,
    this.category = Category.general,
  });

  Task copyWith({
    String? id,
    String? title,
    String? notes,
    DateTime? dueDate,
    DateTime? reminderTime,
    bool? isCompleted,
    Category? category,
  }) {
    return Task(
      id: id ?? this.id,
      title: title ?? this.title,
      notes: notes ?? this.notes,
      dueDate: dueDate ?? this.dueDate,
      reminderTime: reminderTime ?? this.reminderTime,
      isCompleted: isCompleted ?? this.isCompleted,
      category: category ?? this.category,
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
      'category': category.name,
    };
  }

  factory Task.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(dynamic value) {
      if (value == null) return null;
      if (value is Timestamp) return value.toDate();
      if (value is String) return DateTime.tryParse(value);
      return null;
    }

    return Task(
      id: json['id'],
      title: json['title'],
      notes: json['notes'] ?? '',
      dueDate: parseDate(json['dueDate']),
      reminderTime: parseDate(json['reminderTime']),
      isCompleted: json['isCompleted'] ?? false,
      category: Category.values.firstWhere(
        (e) => e.name == json['category'],
        orElse: () => Category.general,
      ),
    );
  }
}
