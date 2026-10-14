import 'reminder_alert_service.dart';
import 'mobile_sql_storage.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import '../models/chat_session.dart';
import 'api_service.dart';
import 'sync_service.dart';
import 'conversation_memory.dart';

/// Offline-first Local SQLite Database Service for Jarvis Mobile.
///
/// Stores reminders, notes, saved places, and chat sessions directly on device,
/// enabling instant zero-latency UI access and offline geofence/sensor evaluation.
class LocalDbService extends ChangeNotifier {
  void notifyLocalChanges() => notifyListeners();
  static final LocalDbService _instance = LocalDbService._internal();
  factory LocalDbService() => _instance;
  LocalDbService._internal();

  Database? _db;
  Future<Database>? _opening;

  Future<Database> get database async {
    if (_db != null) return _db!;
    final opening = _opening ??= _initDatabase();
    try {
      return _db = await opening;
    } finally {
      if (identical(_opening, opening)) _opening = null;
    }
  }

  Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'jarvis_mobile.db');

    return await openDatabase(
      path,
      version: 10,
      onConfigure: (db) async {
        await db.rawQuery('PRAGMA journal_mode=WAL');
        await db.execute('PRAGMA synchronous=NORMAL');
        // Android treats this PRAGMA as a row-returning query, even on assignment.
        await db.rawQuery('PRAGMA busy_timeout=5000');
      },
      onOpen: (db) async {
        await MobileSqlStorage.prepare(db);
        await db.execute(
          'CREATE TABLE IF NOT EXISTS chat_archive_refs '
          '(thread_id TEXT PRIMARY KEY, file_id TEXT, digest TEXT, cached_digest TEXT, message_count INTEGER, '
          'archived INTEGER NOT NULL DEFAULT 1, archived_at TEXT)',
        );
        final archiveColumns = (await db.rawQuery(
          'PRAGMA table_info(chat_archive_refs)',
        )).map((row) => row['name']).toSet();
        if (!archiveColumns.contains('archived')) {
          await db.execute(
            'ALTER TABLE chat_archive_refs ADD COLUMN archived INTEGER NOT NULL DEFAULT 1',
          );
        }
        if (!archiveColumns.contains('archived_at')) {
          await db.execute(
            'ALTER TABLE chat_archive_refs ADD COLUMN archived_at TEXT',
          );
        }
        await db.execute(
          'CREATE INDEX IF NOT EXISTS idx_messages_thread_julian ON chat_messages(thread_id, julianday(timestamp))',
        );
        await db.execute(
          'CREATE TABLE IF NOT EXISTS context_outbox '
          '(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, occurred_at TEXT NOT NULL)',
        );
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 10) {
          await db.execute('ALTER TABLE places ADD COLUMN boundary_json TEXT');
        }
        if (oldVersion < 8) {
          await db.execute(
            "ALTER TABLE reminders ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'notification'",
          );
          await db.execute(
            'ALTER TABLE reminders ADD COLUMN activity_delay_seconds INTEGER NOT NULL DEFAULT 0',
          );
        }
        if (oldVersion < 7) {
          await db.execute(
            'ALTER TABLE reminders ADD COLUMN dynamic_policy TEXT',
          );
        }
        if (oldVersion < 2) {
          try {
            await db.execute(
              "ALTER TABLE chat_sessions ADD COLUMN sync_status TEXT DEFAULT 'pending'",
            );
          } catch (_) {}
        }
        if (oldVersion < 4) {
          await db.execute(
            'ALTER TABLE reminders ADD COLUMN previous_status TEXT',
          );
          await db.execute('ALTER TABLE reminders ADD COLUMN deleted_at TEXT');
          await db.execute('ALTER TABLE notes ADD COLUMN deleted_at TEXT');
        }
        if (oldVersion < 5) {
          await db.execute(
            'ALTER TABLE chat_messages ADD COLUMN duration_ms INTEGER',
          );
        }
        if (oldVersion < 6) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS activity_days (
              day_key TEXT PRIMARY KEY,
              payload TEXT NOT NULL,
              fetched_at TEXT NOT NULL
            )
          ''');
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
            dynamic_policy TEXT,
            delivery_mode TEXT NOT NULL DEFAULT 'notification',
            activity_delay_seconds INTEGER NOT NULL DEFAULT 0,
            activity TEXT,
            status TEXT DEFAULT 'ACTIVE',
            previous_status TEXT,
            deleted_at TEXT,
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
            deleted_at TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
          )
        ''');

        // Saved Places table
        await db.execute('''
          CREATE TABLE places (
            id TEXT PRIMARY KEY,
            boundary_json TEXT,
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
            duration_ms INTEGER,
            sync_status TEXT DEFAULT 'pending'
          )
        ''');

        await db.execute('''
          CREATE TABLE activity_days (
            day_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            fetched_at TEXT NOT NULL
          )
        ''');

        // Create indexes for fast querying
        await db.execute(
          'CREATE INDEX idx_reminders_status ON reminders(status)',
        );
        await db.execute(
          'CREATE INDEX idx_messages_thread ON chat_messages(thread_id)',
        );
      },
    );
  }

  Future<Map<String, dynamic>?> loadActivityDay(String dayKey) async {
    final db = await database;
    final rows = await db.query(
      'activity_days',
      columns: ['payload'],
      where: 'day_key = ?',
      whereArgs: [dayKey],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return Map<String, dynamic>.from(
      jsonDecode(rows.first['payload'] as String),
    );
  }

  Future<void> saveActivityDay(
    String dayKey,
    Map<String, dynamic> payload,
  ) async {
    final db = await database;
    await db.insert('activity_days', {
      'day_key': dayKey,
      'payload': jsonEncode(payload),
      'fetched_at': DateTime.now().toUtc().toIso8601String(),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<int> activityCacheDayCount() async {
    final db = await database;
    final rows = await db.rawQuery(
      'SELECT COUNT(*) AS count FROM activity_days',
    );
    return (rows.first['count'] as num?)?.toInt() ?? 0;
  }

  Future<void> clearActivityCache() async {
    final db = await database;
    await db.delete('activity_days');
  }

  Future<void> queueContextEvent(Map<String, dynamic> event) async {
    final db = await database;
    await db.insert('context_outbox', {
      'event_id': event['event_id'],
      'payload': jsonEncode(event),
      'occurred_at': event['occurred_at'],
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
  }

  Future<List<Map<String, dynamic>>> pendingContextEvents() async {
    final db = await database;
    final rows = await db.query(
      'context_outbox',
      orderBy: 'occurred_at ASC',
      limit: 10,
    );
    return rows
        .map(
          (row) =>
              Map<String, dynamic>.from(jsonDecode(row['payload'] as String)),
        )
        .toList();
  }

  Future<void> acknowledgeContextEvent(String id) async {
    final db = await database;
    await db.delete('context_outbox', where: 'event_id = ?', whereArgs: [id]);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // REMINDERS CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getReminders({
    String? status,
    bool includeDeleted = false,
  }) async {
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
      raw = await db.query(
        'reminders',
        where: includeDeleted ? null : "status != 'DELETED'",
        orderBy: 'updated_at DESC',
      );
    }
    if (status == 'DELETED') return raw;

    // Deduplicate by title + due_at + location_name so user never sees duplicate rows
    final seen = <String>{};
    final List<Map<String, dynamic>> deduped = [];
    for (final item in raw) {
      final key =
          '${(item['title'] ?? '').toString().trim().toLowerCase()}|${(item['due_at'] ?? '').toString().trim()}|${(item['location_name'] ?? '').toString().trim().toLowerCase()}|${(item['status'] ?? '').toString().toUpperCase()}|${item['delivery_mode'] ?? 'notification'}';
      if (seen.add(key)) {
        deduped.add(item);
      }
    }
    return deduped;
  }

  Future<void> saveReminder(
    Map<String, dynamic> reminder, {
    bool markPending = true,
  }) async {
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
    await ReminderAlertService.sync(await getReminders());
    notifyListeners();
  }

  Future<void> updateReminderStatus(
    String id,
    String newStatus, {
    bool markPending = true,
  }) async {
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
    await ReminderAlertService.sync(await getReminders());
    notifyListeners();
  }

  Future<void> deleteReminder(String id) async {
    final db = await database;
    final rows = await db.query(
      'reminders',
      where: 'id = ?',
      whereArgs: [id],
      limit: 1,
    );
    if (rows.isEmpty || rows.first['status'] == 'DELETED') return;
    final now = DateTime.now().toUtc().toIso8601String();
    await db.update(
      'reminders',
      {
        'previous_status': rows.first['status'] ?? 'ACTIVE',
        'status': 'DELETED',
        'deleted_at': now,
        'updated_at': now,
        'sync_status': 'pending',
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    await ReminderAlertService.sync(await getReminders());
    notifyListeners();
  }

  Future<void> restoreReminder(String id) async {
    final db = await database;
    final rows = await db.query(
      'reminders',
      where: 'id = ? AND status = ?',
      whereArgs: [id, 'DELETED'],
      limit: 1,
    );
    if (rows.isEmpty) return;
    await db.update(
      'reminders',
      {
        'status': rows.first['previous_status'] ?? 'ACTIVE',
        'previous_status': null,
        'deleted_at': null,
        'updated_at': DateTime.now().toUtc().toIso8601String(),
        'sync_status': 'pending',
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    await ReminderAlertService.sync(await getReminders());
    notifyListeners();
  }

  /// Evaluate active reminders that match an activity (e.g. WALKING) and location.
  /// Fires system notification immediately and marks reminder as COMPLETED.
  Future<List<String>> evaluateActivityReminders({
    required String activity,
    double? latitude,
    double? longitude,
  }) async {
    final triggeredIds = <String>[];
    try {
      final reminders = await getReminders(status: 'ACTIVE');
      final normAct = activity.toUpperCase().trim();

      for (final r in reminders) {
        if (ReminderAlertService.isRinging(r) ||
            (r['activity_delay_seconds'] as num? ?? 0) > 0) {
          continue;
        }
        final rAct = (r['activity'] ?? '').toString().toUpperCase();
        if (rAct.isEmpty) continue;

        // Check if reminder activity matches (e.g. "WALKING" or "WALKING, IN_VEHICLE")
        final acts = rAct.split(RegExp(r'[,/|]|(\bOR\b)'));
        final matchesAct = acts.any(
          (a) => a.trim().isNotEmpty && a.trim() == normAct,
        );
        if (!matchesAct) continue;
        final dueRaw = (r['due_at'] ?? '').toString().trim();
        if (dueRaw.isNotEmpty) {
          final due = DateTime.tryParse(dueRaw);
          if (due == null || DateTime.now().toUtc().isBefore(due.toUtc())) {
            continue;
          }
        }

        final rLat = (r['latitude'] is num)
            ? (r['latitude'] as num).toDouble()
            : null;
        final rLon = (r['longitude'] is num)
            ? (r['longitude'] as num).toDouble()
            : null;
        if ((r['location_name'] ?? '').toString().trim().isNotEmpty &&
            (rLat == null || rLon == null)) {
          continue;
        }
        final radius = (r['radius_m'] is num)
            ? (r['radius_m'] as num).toDouble()
            : 150.0;

        bool shouldTrigger = false;
        if (rLat != null && rLon != null) {
          if (latitude != null && longitude != null) {
            final dist = _haversineMeters(latitude, longitude, rLat, rLon);
            if (dist <= radius) {
              shouldTrigger = true;
            }
          }
        } else {
          // Activity-only reminder (no location constraint)
          shouldTrigger = true;
        }

        if (shouldTrigger) {
          final id = r['id']?.toString() ?? '';
          final title = r['title'] ?? r['body'] ?? 'Reminder Alert';
          final body = r['body'] ?? title;

          ApiService().showSystemNotification(
            id: id.hashCode,
            title: 'Jarvis Reminder: $title',
            content: body,
          );

          await updateReminderStatus(id, 'COMPLETED', markPending: true);
          triggeredIds.add(id);
          debugPrint(
            '[LocalDbService] Triggered activity reminder: "$title" ($id)',
          );
        }
      }

      if (triggeredIds.isNotEmpty) {
        notifyListeners();
        SyncService().syncNow();
      }
    } catch (e) {
      debugPrint('[LocalDbService] evaluateActivityReminders error: $e');
    }
    return triggeredIds;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // NOTES CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getNotes({bool deleted = false}) async {
    final db = await database;
    final raw = await db.query(
      'notes',
      where: deleted ? 'deleted_at IS NOT NULL' : 'deleted_at IS NULL',
      orderBy: 'updated_at DESC',
    );
    // Distinct IDs are distinct notes, including title-only notes and merge
    // sources. Never hide originals just because their text is identical.
    return raw;
  }

  Future<void> saveNote(
    Map<String, dynamic> note, {
    bool markPending = true,
  }) async {
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
    final now = DateTime.now().toUtc().toIso8601String();
    await db.update(
      'notes',
      {'deleted_at': now, 'updated_at': now, 'sync_status': 'pending'},
      where: 'id = ?',
      whereArgs: [id],
    );
    notifyListeners();
  }

  Future<void> restoreNote(String id) async {
    final db = await database;
    await db.update(
      'notes',
      {
        'deleted_at': null,
        'updated_at': DateTime.now().toUtc().toIso8601String(),
        'sync_status': 'pending',
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    notifyListeners();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PLACES CRUD
  // ═══════════════════════════════════════════════════════════════════════════

  Future<List<Map<String, dynamic>>> getPlaces() async {
    final db = await database;
    return await db.query('places', orderBy: 'updated_at DESC');
  }

  Future<void> savePlace(
    Map<String, dynamic> place, {
    bool markPending = true,
  }) async {
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

  Future<List<Map<String, dynamic>>> recallAnswers(
    String question, {
    List<Map<String, dynamic>> recentHistory = const [],
  }) async {
    final terms = ConversationMemory.searchTerms(question);
    if (terms.isEmpty) return [];
    final db = await database;
    final matches = terms.map((_) => 'lower(q.content) LIKE ?').join(' OR ');
    // Match questions first; then pair each with its immediate next message.
    // This cannot attach an answer from a different chat or skip over a correction.
    final rows = await db.rawQuery('''
      SELECT q.id AS question_id, q.content AS question, q.thread_id,
             a.id AS answer_id, a.content AS answer, a.timestamp AS answered_at,
             a.executed_records,
             (SELECT n.content FROM chat_messages n WHERE n.thread_id = a.thread_id
              AND n.role = 'user' AND (julianday(n.timestamp) > julianday(a.timestamp)
                   OR (julianday(n.timestamp) = julianday(a.timestamp) AND n.rowid > a.rowid))
              ORDER BY julianday(n.timestamp), n.rowid LIMIT 1) AS next_user_text
      FROM (SELECT q.rowid AS question_rowid, q.* FROM chat_messages q WHERE q.role = 'user'
            AND ($matches) AND EXISTS (SELECT 1 FROM chat_sessions s WHERE s.id = q.thread_id)
            ORDER BY julianday(q.timestamp) DESC LIMIT 80) q
      JOIN chat_messages a ON a.id = (
        SELECT n.id FROM chat_messages n WHERE n.thread_id = q.thread_id
        AND (julianday(n.timestamp) > julianday(q.timestamp)
             OR (julianday(n.timestamp) = julianday(q.timestamp) AND n.rowid > q.question_rowid))
        ORDER BY julianday(n.timestamp), n.rowid LIMIT 1)
      WHERE a.role = 'assistant' AND substr(a.id, 1, 4) != 'err_'
    ''', terms.map((term) => '%$term%').toList());
    return ConversationMemory.select(
      question,
      rows,
      recentHistory: recentHistory,
    );
  }

  Future<List<ChatSession>> loadChatSessions({
    bool summariesOnly = false,
    String? loadThreadId,
    String? onlyThreadId,
    int? messageLimit,
  }) async {
    final db = await database;
    final sessionRows = await db.rawQuery(
      'SELECT s.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id=s.id) AS message_count, '
      '(SELECT timestamp FROM chat_messages m WHERE m.thread_id=s.id '
      'ORDER BY julianday(timestamp) DESC LIMIT 1) AS last_message_at '
      ',(SELECT message_count FROM chat_archive_refs a WHERE a.thread_id=s.id) AS archived_count '
      ',(SELECT digest FROM chat_archive_refs a WHERE a.thread_id=s.id) AS archive_digest '
      ',(SELECT archived FROM chat_archive_refs a WHERE a.thread_id=s.id) AS is_archived '
      ',(SELECT archived_at FROM chat_archive_refs a WHERE a.thread_id=s.id) AS archived_at '
      ",(SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id=s.id AND m.sync_status='pending') AS pending_count "
      'FROM chat_sessions s ${onlyThreadId == null ? '' : 'WHERE s.id=?'} '
      'ORDER BY julianday(s.updated_at) DESC',
      onlyThreadId == null ? [] : [onlyThreadId],
    );
    final List<ChatSession> sessions = [];

    for (final sRow in sessionRows) {
      final threadId = sRow['id'] as String;
      final messages = !summariesOnly || threadId == loadThreadId
          ? await loadChatMessages(threadId, limit: messageLimit)
          : <ChatMessage>[];
      sessions.add(
        ChatSession(
          id: threadId,
          title: sRow['title'] as String? ?? 'New Chat',
          createdAt:
              DateTime.tryParse(sRow['created_at'] as String? ?? '') ??
              DateTime.now(),
          updatedAt:
              DateTime.tryParse(sRow['updated_at'] as String? ?? '') ??
              DateTime.now(),
          messages: messages,
          storedMessageCount: max(
            (sRow['message_count'] as num?)?.toInt() ?? 0,
            (sRow['archived_count'] as num?)?.toInt() ?? 0,
          ),
          summaryLastActivityAt: DateTime.tryParse(
            sRow['last_message_at'] as String? ?? '',
          ),
          hasArchive: sRow['archive_digest'] != null,
          isArchived:
              sRow['archive_digest'] != null &&
              sRow['is_archived'] == 1 &&
              (sRow['pending_count'] as num? ?? 0) == 0 &&
              ((sRow['archived_count'] as num?) == null ||
                  (sRow['message_count'] as num? ?? 0) <=
                      (sRow['archived_count'] as num)),
          archivedAt: DateTime.tryParse(sRow['archived_at'] as String? ?? ''),
        ),
      );
    }
    sessions.sort((a, b) => b.lastActivityAt.compareTo(a.lastActivityAt));
    return sessions;
  }

  Future<List<ChatMessage>> loadChatMessages(
    String threadId, {
    int? limit,
    ChatMessage? before,
  }) async {
    final db = await database;
    final args = <Object?>[threadId];
    var boundary = '';
    if (before != null) {
      const rank = "CASE WHEN role='user' THEN 0 ELSE 1 END";
      boundary =
          ' AND (julianday(timestamp) < julianday(?) OR '
          '(julianday(timestamp) = julianday(?) AND '
          '($rank < ? OR ($rank = ? AND id < ?))))';
      args.addAll([
        before.timestamp.toUtc().toIso8601String(),
        before.timestamp.toUtc().toIso8601String(),
        before.isUser ? 0 : 1,
        before.isUser ? 0 : 1,
        before.id,
      ]);
    }
    if (limit != null) args.add(limit);
    final msgRows = await db.rawQuery(
      'SELECT * FROM chat_messages WHERE thread_id=?$boundary '
      "ORDER BY julianday(timestamp) DESC, CASE WHEN role='user' THEN 0 ELSE 1 END DESC, id DESC "
      '${limit == null ? '' : 'LIMIT ?'}',
      args,
    );
    final messages = msgRows.map((m) {
      List<String> executed = [];
      if (m['executed_records'] != null) {
        try {
          executed = List<String>.from(
            jsonDecode(m['executed_records'] as String),
          );
        } catch (_) {}
      }

      return ChatMessage(
        id: m['id'] as String?,
        text: m['content'] as String? ?? '',
        isUser: (m['role'] as String?) == 'user',
        timestamp:
            DateTime.tryParse(m['timestamp'] as String? ?? '') ??
            DateTime.now(),
        runId: m['run_id'] as String?,
        executedRecords: executed,
        durationMs: (m['duration_ms'] as num?)?.toInt(),
      );
    }).toList();
    return ChatSession(
      title: '',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: messages,
    ).messages;
  }

  Future<Set<String>> searchChatIds(String query) async {
    final db = await database;
    final pattern = '%${query.toLowerCase()}%';
    final rows = await db.rawQuery(
      'SELECT s.id FROM chat_sessions s WHERE lower(s.title) LIKE ? OR '
      'EXISTS (SELECT 1 FROM chat_messages m WHERE m.thread_id=s.id AND lower(m.content) LIKE ?)',
      [pattern, pattern],
    );
    return rows.map((r) => r['id'] as String).toSet();
  }

  Future<void> saveChatSession(
    ChatSession session, {
    bool markPending = true,
  }) async {
    final db = await database;
    final existingMessages = markPending
        ? {
            for (final row in await db.query(
              'chat_messages',
              where: 'thread_id = ?',
              whereArgs: [session.id],
            ))
              row['id']: row,
          }
        : <Object?, Map<String, Object?>>{};
    final batch = db.batch();

    batch.insert('chat_sessions', {
      'id': session.id,
      'title': session.title,
      'created_at': session.createdAt.toUtc().toIso8601String(),
      'updated_at': session.updatedAt.toUtc().toIso8601String(),
      if (markPending) 'sync_status': 'pending',
    }, conflictAlgorithm: ConflictAlgorithm.replace);

    for (final m in session.messages) {
      final data = <String, Object?>{
        'id': m.id,
        'thread_id': session.id,
        'role': m.isUser ? 'user' : 'assistant',
        'content': m.text,
        'timestamp': m.timestamp.toUtc().toIso8601String(),
        'run_id': m.runId,
        'executed_records': jsonEncode(m.executedRecords),
        'duration_ms': m.durationMs,
      };
      final existing = existingMessages[m.id];
      if (markPending &&
          existing != null &&
          data.entries.every((entry) => existing[entry.key] == entry.value)) {
        // Preserve both synced and still-pending rows. Saving a new message
        // must not queue every unchanged historical message for another write.
        continue;
      }
      if (markPending) data['sync_status'] = 'pending';
      if (markPending) {
        batch.update(
          'chat_archive_refs',
          {'archived': 0},
          where: 'thread_id = ?',
          whereArgs: [session.id],
        );
      }
      batch.insert(
        'chat_messages',
        data,
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }

    await batch.commit(noResult: true);
    notifyListeners();
  }

  Future<void> deleteChatSession(String sessionId) async {
    final db = await database;
    await db.delete(
      'chat_messages',
      where: 'thread_id = ?',
      whereArgs: [sessionId],
    );
    await db.delete('chat_sessions', where: 'id = ?', whereArgs: [sessionId]);
    notifyListeners();
  }

  Future<void> deleteAllChatSessionsLocal() async {
    final db = await database;
    await db.delete('chat_messages');
    await db.delete('chat_sessions');
    notifyListeners();
  }

  // Local chat archive metadata and cached messages.
  Future<Map<String, Object?>?> chatArchiveReference(String threadId) async {
    final rows = await (await database).query(
      'chat_archive_refs',
      where: 'thread_id = ?',
      whereArgs: [threadId],
    );
    return rows.isEmpty ? null : rows.single;
  }

  Future<void> cacheArchivedChat(
    Map<String, dynamic> archive,
    String digest, {
    bool retirePending = false,
  }) async {
    final db = await database;
    final threadId = archive['id'] as String;
    final existing = {
      for (final row in await db.query(
        'chat_messages',
        where: 'thread_id = ?',
        whereArgs: [threadId],
      ))
        row['id']: row,
    };
    final batch = db.batch();
    for (final item in archive['messages'] as List) {
      final m = Map<String, dynamic>.from(item);
      final previous = existing[m['id']];
      if (previous != null) {
        // A newer local edit wins over an older archived answer.
        if (previous['content'] == m['text'] &&
            (previous['sync_status'] != 'pending' || retirePending)) {
          batch.update(
            'chat_messages',
            {'sync_status': 'archived'},
            where: 'id = ? AND thread_id = ?',
            whereArgs: [m['id'], threadId],
          );
        }
        continue;
      }
      batch.insert('chat_messages', {
        'id': m['id'],
        'thread_id': threadId,
        'content': m['text'],
        'role': m['is_user'] == true ? 'user' : 'assistant',
        'timestamp': m['timestamp'],
        'run_id': m['run_id'],
        'executed_records': jsonEncode(m['executed_records'] ?? []),
        'duration_ms': m['duration_ms'],
        'sync_status': 'archived',
      }, conflictAlgorithm: ConflictAlgorithm.ignore);
    }
    batch.rawInsert(
      'INSERT INTO chat_archive_refs(thread_id,digest,cached_digest,message_count,archived,archived_at) VALUES(?,?,?,?,1,?) '
      'ON CONFLICT(thread_id) DO UPDATE SET digest=excluded.digest,cached_digest=excluded.cached_digest,'
      'message_count=excluded.message_count,archived=CASE WHEN ? THEN 1 ELSE chat_archive_refs.archived END,'
      'archived_at=CASE WHEN ? THEN excluded.archived_at ELSE COALESCE(chat_archive_refs.archived_at,excluded.archived_at) END',
      [
        threadId,
        digest,
        digest,
        (archive['messages'] as List).length,
        DateTime.now().toUtc().toIso8601String(),
        retirePending ? 1 : 0,
        retirePending ? 1 : 0,
      ],
    );
    await batch.commit(noResult: true);
    notifyListeners();
  }
}

double _haversineMeters(double lat1, double lon1, double lat2, double lon2) {
  const r = 6371000.0;
  final dLat = (lat2 - lat1) * (pi / 180.0);
  final dLon = (lon2 - lon1) * (pi / 180.0);
  final a =
      sin(dLat / 2) * sin(dLat / 2) +
      cos(lat1 * (pi / 180.0)) *
          cos(lat2 * (pi / 180.0)) *
          sin(dLon / 2) *
          sin(dLon / 2);
  final c = 2 * atan2(sqrt(a), sqrt(1 - a));
  return r * c;
}
