import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../models/chat_session.dart';
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
              final session = ChatSession.fromJson(
                item as Map<String, dynamic>,
              );
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
  static Future<List<ChatSession>> loadSessions({
    bool summariesOnly = false,
    String? loadThreadId,
    int? messageLimit,
  }) async {
    await _checkMigration();
    return await LocalDbService().loadChatSessions(
      summariesOnly: summariesOnly,
      loadThreadId: loadThreadId,
      messageLimit: messageLimit,
    );
  }

  static Future<ChatSession?> loadSession(
    String id, {
    int? messageLimit,
  }) async {
    await _checkMigration();
    final rows = await LocalDbService().loadChatSessions(
      onlyThreadId: id,
      messageLimit: messageLimit,
    );
    return rows.firstOrNull;
  }

  /// Save or update an individual chat session into local SQLite.
  static Future<void> saveSession(ChatSession session) async {
    await LocalDbService().saveChatSession(session);
    // The saved data is already local. Downloading every remote message here
    // makes each new message's read cost grow with the entire chat archive.
    SyncService().syncNow(pullRemote: false);
  }

  /// Delete a chat session by ID from local SQLite and the API working cache.
  static Future<void> deleteSession(String sessionId) async {
    await LocalDbService().deleteChatSession(sessionId);
  }

  /// Rename a chat session.
  static Future<void> renameSession(String sessionId, String newTitle) async {
    final session = await loadSession(sessionId);
    if (session != null) {
      session.title = newTitle;
      session.updatedAt = DateTime.now();
      await LocalDbService().saveChatSession(session);
    }
  }
}
