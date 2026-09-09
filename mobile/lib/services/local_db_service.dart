import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import '../models/chat_session.dart';

/// Offline-first Local SQLite Database Service for Jarvis Mobile.
///
/// Stores reminders, notes, saved places, and chat sessions directly on device,
/// enabling instant zero-latency UI access and offline geofence/sensor evaluation.
class LocalDbService extends ChangeNotifier {
  static final LocalDbService _instance = LocalDbService._internal();
  factory LocalDbService() => _instance;
  LocalDbService._internal();

  Database? _db;

  Future<Database> get database async {
    if (_db != null) return _db!;
    _db = await _initDatabase();
    return _db!;
  }

  Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'jarvis_mobile.db');

    return await openDatabase(
      path,
      version: 2,
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          try {
            await db.execute("ALTER TABLE chat_sessions ADD COLUMN sync_status TEXT DEFAULT 'pending'");
          } catch (_) {}
        }
      },
      onCreate: (db, version) async {
        // Reminders table
        await db.execute('''
          CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            due_at TEXT,
            location_name TEXT,
            latitude REAL,
            longitude REAL,
            radius_m REAL DEFAULT 150.0,
            activity TEXT,
            status TEXT DEFAULT 'ACTIVE',
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
          )
        ''');

        // Notes table
        await db.execute('''
          CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            title TEXT,
            content TEXT NOT NULL,
            place TEXT,
            category TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
          )
        ''');

        // Saved Places table
        await db.execute('''
          CREATE TABLE places (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT,
            latitude REAL,
            longitude REAL,
            radius_m REAL DEFAULT 150.0,
            category TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
          )
        ''');

        // Chat Sessions table
        await db.execute('''
          CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            sync_status TEXT DEFAULT 'pending'
          )
        ''');

        // Chat Messages table
        await db.execute('''
          CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            run_id TEXT,
            executed_records TEXT,
            sync_status TEXT DEFAULT 'pending'
          )
        ''');

        // Create indexes for fast querying
        await db.execute('CREATE INDEX idx_reminders_status ON reminders(status)');
        await db.execute('CREATE INDEX idx_messages_thread ON chat_messages(thread_id)');
      },
    );
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // REMINDERS CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getReminders({String? status}) async {
    final db = await database;
    List<Map<String, dynamic>> raw;
    if (status != null) {
      raw = await db.query(
        'reminders',
        where: 'status = ?',
        whereArgs: [status],
        orderBy: 'updated_at DESC',
      );
    } else {
      raw = await db.query('reminders', orderBy: 'updated_at DESC');
    }

    // Deduplicate by title + due_at + location_name so user never sees duplicate rows
    final seen = <String>{};
    final List<Map<String, dynamic>> deduped = [];
    for (final item in raw) {
      final key = '${(item['title'] ?? '').toString().trim().toLowerCase()}|${(item['due_at'] ?? '').toString().trim()}|${(item['location_name'] ?? '').toString().trim().toLowerCase()}';
      if (seen.add(key)) {
        deduped.add(item);
      }
    }
    return deduped;
  }

  Future<void> saveReminder(Map<String, dynamic> reminder, {bool markPending = true}) async {
    final db = await database;
    final now = DateTime.now().toUtc().toIso8601String();
    final data = Map<String, dynamic>.from(reminder);

    data['updated_at'] = data['updated_at'] ?? now;
    data['created_at'] = data['created_at'] ?? now;
    if (markPending) {
      data['sync_status'] = 'pending';
    }

    await db.insert(
      'reminders',
      data,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    notifyListeners();
  }

  Future<void> updateReminderStatus(String id, String newStatus, {bool markPending = true}) async {
    final db = await database;
    final now = DateTime.now().toUtc().toIso8601String();
    await db.update(
      'reminders',
      {
        'status': newStatus,
        'updated_at': now,
        if (markPending) 'sync_status': 'pending',
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    notifyListeners();
  }

  Future<void> deleteReminder(String id) async {
    final db = await database;
    await db.delete('reminders', where: 'id = ?', whereArgs: [id]);
    notifyListeners();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // NOTES CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getNotes() async {
    final db = await database;
    final raw = await db.query('notes', orderBy: 'updated_at DESC');
    final seen = <String>{};
    final List<Map<String, dynamic>> deduped = [];
    for (final item in raw) {
      final key = (item['content'] ?? item['text'] ?? '').toString().trim().toLowerCase();
      if (seen.add(key)) {
        deduped.add(item);
      }
    }
    return deduped;
  }


  Future<void> saveNote(Map<String, dynamic> note, {bool markPending = true}) async {
    final db = await database;
    final now = DateTime.now().toUtc().toIso8601String();
    final data = Map<String, dynamic>.from(note);

    data['updated_at'] = data['updated_at'] ?? now;
    data['created_at'] = data['created_at'] ?? now;
    if (markPending) {
      data['sync_status'] = 'pending';
    }

    await db.insert(
      'notes',
      data,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    notifyListeners();
  }

  Future<void> deleteNote(String id) async {
    final db = await database;
    await db.delete('notes', where: 'id = ?', whereArgs: [id]);
    notifyListeners();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PLACES CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getPlaces() async {
    final db = await database;
    return await db.query('places', orderBy: 'updated_at DESC');
  }

  Future<void> savePlace(Map<String, dynamic> place, {bool markPending = true}) async {
    final db = await database;
    final now = DateTime.now().toUtc().toIso8601String();
    final data = Map<String, dynamic>.from(place);

    data['updated_at'] = data['updated_at'] ?? now;
    data['created_at'] = data['created_at'] ?? now;
    if (markPending) {
      data['sync_status'] = 'pending';
    }

    await db.insert(
      'places',
      data,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    notifyListeners();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // CHAT SESSIONS & MESSAGES
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<ChatSession>> loadChatSessions() async {
    final db = await database;
    final sessionRows = await db.query('chat_sessions', orderBy: 'updated_at DESC');
    final List<ChatSession> sessions = [];

    for (final sRow in sessionRows) {
      final threadId = sRow['id'] as String;
      final msgRows = await db.query(
        'chat_messages',
        where: 'thread_id = ?',
        whereArgs: [threadId],
        orderBy: 'timestamp ASC',
      );

      final messages = msgRows.map((m) {
        List<String> executed = [];
        if (m['executed_records'] != null) {
          try {
            executed = List<String>.from(jsonDecode(m['executed_records'] as String));
          } catch (_) {}
        }

        return ChatMessage(
          id: m['id'] as String?,
          text: m['content'] as String? ?? '',
          isUser: (m['role'] as String?) == 'user',
          timestamp: DateTime.tryParse(m['timestamp'] as String? ?? '') ?? DateTime.now(),
          runId: m['run_id'] as String?,
          executedRecords: executed,
        );
      }).toList();

      sessions.add(ChatSession(
        id: threadId,
        title: sRow['title'] as String? ?? 'New Chat',
        createdAt: DateTime.tryParse(sRow['created_at'] as String? ?? '') ?? DateTime.now(),
        updatedAt: DateTime.tryParse(sRow['updated_at'] as String? ?? '') ?? DateTime.now(),
        messages: messages,
      ));
    }

    return sessions;
  }

  Future<void> saveChatSession(ChatSession session, {bool markPending = true}) async {
    final db = await database;
    final batch = db.batch();

    batch.insert(
      'chat_sessions',
      {
        'id': session.id,
        'title': session.title,
        'created_at': session.createdAt.toIso8601String(),
        'updated_at': session.updatedAt.toIso8601String(),
        if (markPending) 'sync_status': 'pending',
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );

    for (final m in session.messages) {
      batch.insert(
        'chat_messages',
        {
          'id': m.id,
          'thread_id': session.id,
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
          'timestamp': m.timestamp.toIso8601String(),
          'run_id': m.runId,
          'executed_records': jsonEncode(m.executedRecords),
          if (markPending) 'sync_status': 'pending',
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }

    await batch.commit(noResult: true);
    notifyListeners();
  }

  Future<void> deleteChatSession(String sessionId) async {
    final db = await database;
    await db.delete('chat_messages', where: 'thread_id = ?', whereArgs: [sessionId]);
    await db.delete('chat_sessions', where: 'id = ?', whereArgs: [sessionId]);
    notifyListeners();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SYNC RECONCILIATION HELPERS
  // ═══════════════════════════════════════════════════════════════════════════

  /// Retrieve all locally modified records waiting to be pushed to Firestore
  Future<Map<String, List<Map<String, dynamic>>>> getPendingSyncRecords() async {
    final db = await database;
    final reminders = await db.query('reminders', where: "sync_status = 'pending'");
    final notes = await db.query('notes', where: "sync_status = 'pending'");
    final places = await db.query('places', where: "sync_status = 'pending'");
    final sessions = await db.query('chat_sessions', where: "sync_status = 'pending'");
    final messages = await db.query('chat_messages', where: "sync_status = 'pending'");

    return {
      'reminders': reminders,
      'notes': notes,
      'places': places,
      'chat_sessions': sessions,
      'chat_messages': messages,
    };
  }

  /// Mark records as synced after successful upload to cloud
  Future<void> markRecordsSynced({
    List<String>? reminderIds,
    List<String>? noteIds,
    List<String>? placeIds,
    List<String>? sessionIds,
    List<String>? messageIds,
  }) async {
    final db = await database;
    final batch = db.batch();

    if (reminderIds != null && reminderIds.isNotEmpty) {
      final placeholders = List.filled(reminderIds.length, '?').join(',');
      batch.rawUpdate(
        'UPDATE reminders SET sync_status = ? WHERE id IN ($placeholders)',
        ['synced', ...reminderIds],
      );
    }

    if (noteIds != null && noteIds.isNotEmpty) {
      final placeholders = List.filled(noteIds.length, '?').join(',');
      batch.rawUpdate(
        'UPDATE notes SET sync_status = ? WHERE id IN ($placeholders)',
        ['synced', ...noteIds],
      );
    }

    if (placeIds != null && placeIds.isNotEmpty) {
      final placeholders = List.filled(placeIds.length, '?').join(',');
      batch.rawUpdate(
        'UPDATE places SET sync_status = ? WHERE id IN ($placeholders)',
        ['synced', ...placeIds],
      );
    }

    if (sessionIds != null && sessionIds.isNotEmpty) {
      final placeholders = List.filled(sessionIds.length, '?').join(',');
      batch.rawUpdate(
        'UPDATE chat_sessions SET sync_status = ? WHERE id IN ($placeholders)',
        ['synced', ...sessionIds],
      );
    }

    if (messageIds != null && messageIds.isNotEmpty) {
      final placeholders = List.filled(messageIds.length, '?').join(',');
      batch.rawUpdate(
        'UPDATE chat_messages SET sync_status = ? WHERE id IN ($placeholders)',
        ['synced', ...messageIds],
      );
    }

    await batch.commit(noResult: true);
  }

  /// Reconcile remote records pulled down from Firestore into local SQLite
  Future<void> reconcileRemoteRecords({
    List<Map<String, dynamic>>? remoteReminders,
    List<Map<String, dynamic>>? remoteNotes,
    List<Map<String, dynamic>>? remotePlaces,
    List<Map<String, dynamic>>? remoteChatSessions,
    List<Map<String, dynamic>>? remoteChatMessages,
  }) async {
    final db = await database;
    final batch = db.batch();

    if (remoteReminders != null) {
      final remoteIds = remoteReminders
          .map((r) => r['id']?.toString() ?? '')
          .where((id) => id.isNotEmpty)
          .toSet();

      // Delete any local items that were deleted from Firestore in the cloud
      final localSynced = await db.query('reminders', columns: ['id'], where: "sync_status = 'synced'");
      for (final row in localSynced) {
        final localId = row['id'] as String;
        if (!remoteIds.contains(localId)) {
          batch.delete('reminders', where: 'id = ?', whereArgs: [localId]);
        }
      }

      for (final r in remoteReminders) {
        final id = r['id']?.toString() ?? '';
        if (id.isEmpty) continue;
        final isActive = r['active'] == null
            ? (r['status'] == 'ACTIVE' || r['status'] == null)
            : (r['active'] == true);
        final sanitized = {
          'id': id,
          'title': r['title']?.toString() ?? 'Reminder',
          'body': r['body']?.toString() ?? r['title']?.toString() ?? '',
          'due_at': r['due_at']?.toString(),
          'location_name': r['location_name']?.toString(),
          'latitude': (r['latitude'] is num) ? (r['latitude'] as num).toDouble() : null,
          'longitude': (r['longitude'] is num) ? (r['longitude'] as num).toDouble() : null,
          'radius_m': (r['radius_m'] is num) ? (r['radius_m'] as num).toDouble() : 150.0,
          'activity': r['activity']?.toString(),
          'status': isActive ? 'ACTIVE' : 'INACTIVE',
          'sync_status': 'synced',
          'created_at': r['created_at']?.toString() ?? DateTime.now().toIso8601String(),
          'updated_at': r['updated_at']?.toString() ?? DateTime.now().toIso8601String(),
        };
        batch.insert(
          'reminders',
          sanitized,
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }

    if (remoteNotes != null) {
      final remoteIds = remoteNotes
          .map((n) => n['id']?.toString() ?? '')
          .where((id) => id.isNotEmpty)
          .toSet();

      // Delete any local notes that were deleted from Firestore in the cloud
      final localSynced = await db.query('notes', columns: ['id'], where: "sync_status = 'synced'");
      for (final row in localSynced) {
        final localId = row['id'] as String;
        if (!remoteIds.contains(localId)) {
          batch.delete('notes', where: 'id = ?', whereArgs: [localId]);
        }
      }

      for (final n in remoteNotes) {
        final id = n['id']?.toString() ?? '';
        if (id.isEmpty) continue;
        final sanitized = {
          'id': id,
          'title': n['title']?.toString() ?? 'Note',
          'content': n['content']?.toString() ?? n['text']?.toString() ?? '',
          'place': n['place']?.toString(),
          'category': n['category']?.toString(),
          'sync_status': 'synced',
          'created_at': n['created_at']?.toString() ?? DateTime.now().toIso8601String(),
          'updated_at': n['updated_at']?.toString() ?? DateTime.now().toIso8601String(),
        };
        batch.insert(
          'notes',
          sanitized,
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }

    if (remotePlaces != null) {
      final remoteIds = remotePlaces
          .map((p) => p['id']?.toString() ?? '')
          .where((id) => id.isNotEmpty)
          .toSet();

      final localSynced = await db.query('places', columns: ['id'], where: "sync_status = 'synced'");
      for (final row in localSynced) {
        final localId = row['id'] as String;
        if (!remoteIds.contains(localId)) {
          batch.delete('places', where: 'id = ?', whereArgs: [localId]);
        }
      }

      for (final p in remotePlaces) {
        final id = p['id']?.toString() ?? '';
        if (id.isEmpty) continue;
        final sanitized = {
          'id': id,
          'name': p['name']?.toString() ?? '',
          'address': p['address']?.toString(),
          'latitude': (p['latitude'] is num) ? (p['latitude'] as num).toDouble() : null,
          'longitude': (p['longitude'] is num) ? (p['longitude'] as num).toDouble() : null,
          'radius_m': (p['radius_m'] is num) ? (p['radius_m'] as num).toDouble() : 150.0,
          'category': p['category']?.toString(),
          'sync_status': 'synced',
          'created_at': p['created_at']?.toString() ?? DateTime.now().toIso8601String(),
          'updated_at': p['updated_at']?.toString() ?? DateTime.now().toIso8601String(),
        };
        batch.insert(
          'places',
          sanitized,
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }


    if (remoteChatSessions != null) {
      final remoteIds = remoteChatSessions
          .map((s) => s['id']?.toString() ?? '')
          .where((id) => id.isNotEmpty)
          .toSet();

      final localSynced = await db.query('chat_sessions', columns: ['id'], where: "sync_status = 'synced'");
      for (final row in localSynced) {
        final localId = row['id'] as String;
        if (!remoteIds.contains(localId)) {
          batch.delete('chat_sessions', where: 'id = ?', whereArgs: [localId]);
          batch.delete('chat_messages', where: 'thread_id = ?', whereArgs: [localId]);
        }
      }

      for (final s in remoteChatSessions) {
        final data = Map<String, dynamic>.from(s);
        batch.insert(
          'chat_sessions',
          {
            'id': data['id'],
            'title': data['title'] ?? 'New Chat',
            'created_at': data['created_at'] ?? DateTime.now().toIso8601String(),
            'updated_at': data['updated_at'] ?? DateTime.now().toIso8601String(),
            'sync_status': 'synced',
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }

    if (remoteChatMessages != null) {
      final remoteMsgIds = remoteChatMessages
          .map((m) => m['id']?.toString() ?? '')
          .where((id) => id.isNotEmpty)
          .toSet();

      final localSyncedMsgs = await db.query('chat_messages', columns: ['id'], where: "sync_status = 'synced'");
      for (final row in localSyncedMsgs) {
        final localId = row['id'] as String;
        if (!remoteMsgIds.contains(localId)) {
          batch.delete('chat_messages', where: 'id = ?', whereArgs: [localId]);
        }
      }

      for (final m in remoteChatMessages) {
        final data = Map<String, dynamic>.from(m);
        batch.insert(
          'chat_messages',
          {
            'id': data['id'],
            'thread_id': data['thread_id'] ?? 'default',
            'role': data['role'] ?? 'user',
            'content': data['content'] ?? '',
            'timestamp': data['timestamp'] ?? DateTime.now().toIso8601String(),
            'run_id': data['run_id'],
            'executed_records': data['executed_records'] is String
                ? data['executed_records']
                : jsonEncode(data['executed_records'] ?? []),
            'sync_status': 'synced',
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }

    await batch.commit(noResult: true);
    notifyListeners();
  }

}
