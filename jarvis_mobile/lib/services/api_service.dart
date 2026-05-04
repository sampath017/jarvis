import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:geolocator/geolocator.dart';
import '../models/task.dart';
import '../models/note.dart';
import '../models/chat_thread.dart';

class ApiService {
  final CollectionReference _tasksCollection = FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'jarvis').collection('tasks');
  final CollectionReference _notesCollection = FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'jarvis').collection('notes');
  final CollectionReference _chatsCollection = FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'jarvis').collection('chats');
  
  static const String baseUrl = 'http://localhost:8000'; // Change to your Cloud Run URL after deployment

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

  // Chats
  Future<List<ChatThread>> fetchChatThreads() async {
    try {
      final snapshot = await _chatsCollection.orderBy('updatedAt', descending: true).get();
      return snapshot.docs.map((doc) {
        final data = doc.data() as Map<String, dynamic>;
        if (!data.containsKey('id')) {
          data['id'] = doc.id;
        }
        return ChatThread.fromJson(data);
      }).toList();
    } catch (e) {
      throw Exception('Failed to load chat threads from Firebase: $e');
    }
  }

  Future<ChatThread> saveChatThread(ChatThread thread) async {
    try {
      await _chatsCollection.doc(thread.id).set(thread.toJson());
      return thread;
    } catch (e) {
      throw Exception('Failed to save chat thread in Firebase: $e');
    }
  }

  Future<void> deleteChatThread(String id) async {
    try {
      await _chatsCollection.doc(id).delete();
    } catch (e) {
      throw Exception('Failed to delete chat thread from Firebase: $e');
    }
  }

  // AI Assistant
  Future<String> askAI(String message, String threadId, {String? threadTitle}) async {
    try {
      // Try to get the user's current location to send with the message
      double? userLat;
      double? userLng;
      try {
        final position = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            timeLimit: Duration(seconds: 5),
          ),
        );
        userLat = position.latitude;
        userLng = position.longitude;
      } catch (_) {
        // Location unavailable — continue without it
      }

      final response = await http.post(
        Uri.parse('$baseUrl/ask'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'message': message, 
          'thread_id': threadId,
          if (threadTitle != null) 'thread_title': threadTitle,
          if (userLat != null) 'user_latitude': userLat,
          if (userLng != null) 'user_longitude': userLng,
        }),
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

  Future<void> submitFeedback(String threadId, int score) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/feedback'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'thread_id': threadId,
          'score': score,
        }),
      );

      if (response.statusCode != 200) {
        throw Exception('Failed to submit feedback: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to connect to backend: $e');
    }
  }
}
