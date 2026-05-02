import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:cloud_firestore/cloud_firestore.dart';
import '../models/task.dart';
import '../models/note.dart';

class ApiService {
  final CollectionReference _tasksCollection = FirebaseFirestore.instance.collection('tasks');
  final CollectionReference _notesCollection = FirebaseFirestore.instance.collection('notes');

  // Tasks
  Future<List<Task>> fetchTasks() async {
    try {
      final snapshot = await _tasksCollection.get();
      return snapshot.docs.map((doc) {
        final data = doc.data() as Map<String, dynamic>;
        if (!data.containsKey('id')) {
          data['id'] = doc.id;
        }
        return Task.fromJson(data);
      }).toList();
    } catch (e) {
      throw Exception('Failed to load tasks from Firebase: $e');
    }
  }

  Future<Task> createTask(Task task) async {
    try {
      await _tasksCollection.doc(task.id).set(task.toJson());
      return task;
    } catch (e) {
      throw Exception('Failed to create task in Firebase: $e');
    }
  }

  Future<Task> updateTask(Task task) async {
    try {
      await _tasksCollection.doc(task.id).update(task.toJson());
      return task;
    } catch (e) {
      throw Exception('Failed to update task in Firebase: $e');
    }
  }

  Future<void> deleteTask(String id) async {
    try {
      await _tasksCollection.doc(id).delete();
    } catch (e) {
      throw Exception('Failed to delete task in Firebase: $e');
    }
  }

  // Notes
  Future<List<Note>> fetchNotes() async {
    try {
      final snapshot = await _notesCollection.orderBy('createdAt', descending: true).get();
      return snapshot.docs.map((doc) {
        final data = doc.data() as Map<String, dynamic>;
        if (!data.containsKey('id')) {
          data['id'] = doc.id;
        }
        return Note.fromJson(data);
      }).toList();
    } catch (e) {
      throw Exception('Failed to load notes from Firebase: $e');
    }
  }

  Future<Note> createNote(Note note) async {
    try {
      await _notesCollection.doc(note.id).set(note.toJson());
      return note;
    } catch (e) {
      throw Exception('Failed to create note in Firebase: $e');
    }
  }

  Future<void> deleteNote(String id) async {
    try {
      await _notesCollection.doc(id).delete();
    } catch (e) {
      throw Exception('Failed to delete note from Firebase: $e');
    }
  }

  // AI Assistant
  Future<String> askAI(String message) async {
    try {
      final response = await http.post(
        Uri.parse('http://localhost:8000/ask'), // Change to your backend URL
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'message': message}),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['response'];
      } else {
        throw Exception('AI Backend Error: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to connect to AI assistant: $e');
    }
  }
}
