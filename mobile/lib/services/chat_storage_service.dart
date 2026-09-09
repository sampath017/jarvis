import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../models/chat_session.dart';
import 'api_service.dart';
import 'local_db_service.dart';
import 'sync_service.dart';

/// Offline-first persistence for chat sessions using LocalDbService (SQLite).
/// Includes one-time migration from legacy chat_sessions.json.
class ChatStorageService {
  static const String _fileName = 'chat_sessions.json';
  static bool _migrated = false;

  static Future<void> _checkMigration() async {
    if (_migrated) return;
    _migrated = true;
    try {
      final dir = await getApplicationDocumentsDirectory();
      final file = File('${dir.path}/$_fileName');
      if (await file.exists()) {
        final raw = await file.readAsString();
        if (raw.trim().isNotEmpty) {
          final decoded = jsonDecode(raw);
          if (decoded is List) {
            final db = LocalDbService();
            for (final item in decoded) {
              final session = ChatSession.fromJson(item as Map<String, dynamic>);
              await db.saveChatSession(session, markPending: false);
            }
          }
        }
      }
    } catch (e) {
      debugPrint('[ChatStorageService] Migration note: $e');
    }
  }

  /// Load all stored chat sessions from local SQLite, sorted most recent first.
  static Future<List<ChatSession>> loadSessions() async {
    await _checkMigration();
    return await LocalDbService().loadChatSessions();
  }

  /// Save or update an individual chat session into local SQLite.
  static Future<void> saveSession(ChatSession session) async {
    await LocalDbService().saveChatSession(session);
    SyncService().syncNow();
  }


  /// Delete a chat session by ID from local SQLite and Cloud Firestore.
  static Future<void> deleteSession(String sessionId) async {
    await LocalDbService().deleteChatSession(sessionId);
    if (ApiService().isOnline) {
      await ApiService().deleteChatSession(sessionId);
    }
  }

  /// Rename a chat session.
  static Future<void> renameSession(String sessionId, String newTitle) async {
    final list = await loadSessions();
    final index = list.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final session = list[index];
      session.title = newTitle;
      session.updatedAt = DateTime.now();
      await LocalDbService().saveChatSession(session);
    }
  }
}
