import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:sqflite/sqflite.dart';
import 'local_db_service.dart';
import 'reminder_alert_service.dart';
import 'power_http.dart' show MobileSaveException;

/// Durable local records. Reads sent to the API are explicit and tool-scoped.
class MobileStore {
  static final instance = MobileStore();
  final _local = LocalDbService();
  Database? _preparedDatabase;
  Future<Database>? _preparing;
  static const _channel = MethodChannel('com.jarvis/foreground_service');
  Future<Map<String, dynamic>> eventContext(Map<String, dynamic> event) async =>
      Map<String, dynamic>.from(
        jsonDecode(
          await _channel.invokeMethod<String>(
                'mobileContext',
                jsonEncode(event),
              ) ??
              '{}',
        ),
      );
  String get day => DateTime.now()
      .toUtc()
      .add(const Duration(hours: 5, minutes: 30))
      .toIso8601String()
      .substring(0, 10);
  Future<Database> database() async {
    final db = await _local.database;
    if (identical(db, _preparedDatabase)) return db;
    final preparing = _preparing ??= _prepareDatabase(db);
    try {
      return _preparedDatabase = await preparing;
    } finally {
      if (identical(_preparing, preparing)) _preparing = null;
    }
  }

  Future<Database> _prepareDatabase(Database db) async {
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_agent_rows(collection TEXT,id TEXT,payload TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(collection,id))',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_mobile_agent_recent ON mobile_agent_rows(collection,updated_at)',
    );
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_usage(day TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)',
    );
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_receipts(operation_id TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)',
    );
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_commits(operation_id TEXT PRIMARY KEY,conflicts INTEGER NOT NULL DEFAULT 0)',
    );
    return db;
  }

  Future<Map<String, dynamic>> commandContext() async {
    final db = await database();
    final usage = await db.query(
      'mobile_usage',
      where: 'day=?',
      whereArgs: [day],
    );
    return {
      'budget': usage.isEmpty ? {'day': day} : usage.single,
    };
  }

  /// A tool may read a named collection, IDs or a bounded search result only.
  Future<Map<String, dynamic>> readForTool(
    String tool,
    Map<String, dynamic> args,
  ) async {
    final db = await database();
    String? table;
    String? id;
    List<dynamic>? ids;
    if (tool == 'create_reminder') {
      final reminders = await db.query(
        'reminders',
        where: 'lower(title)=lower(?) AND status=?',
        whereArgs: [args['title'] ?? '', 'ACTIVE'],
        limit: 50,
      );
      final place = args['location_name']?.toString().trim() ?? '';
      final places = place.isEmpty
          ? <Map<String, Object?>>[]
          : await db.query(
              'places',
              where: 'lower(name)=lower(?)',
              whereArgs: [place],
              limit: 10,
            );
      return {
        'records': {'reminders': reminders, 'places': places},
      };
    }
    if ({
      'list_notes',
      'search_notes',
      'update_note',
      'merge_notes',
      'delete_note',
      'delete_all_notes',
      'restore_note',
    }.contains(tool)) {
      table = 'notes';
      id = args['note_id']?.toString();
      ids = args['note_ids'] as List?;
    } else if ({
      'list_reminders',
      'search_reminders',
      'update_reminder',
      'consolidate_reminders',
      'delete_reminder',
      'delete_all_reminders',
      'restore_reminder',
    }.contains(tool)) {
      table = 'reminders';
      id = args['reminder_id']?.toString();
    } else if ({
      'list_saved_places',
      'save_place',
      'delete_place',
    }.contains(tool)) {
      table = 'places';
      id = args['place_id']?.toString();
    } else if (tool == 'recall_context_history') {
      final end =
          DateTime.tryParse(args['end_at']?.toString() ?? '') ??
          DateTime.now().toUtc();
      final start =
          DateTime.tryParse(args['start_at']?.toString() ?? '') ??
          end.subtract(
            Duration(
              minutes: ((args['lookback_minutes'] as num?)?.toInt() ?? 2880)
                  .clamp(1, 44640),
            ),
          );
      return historyContext(start, end);
    } else if ({
      'list_tasks',
      'update_task',
      'update_task_status',
      'delete_task',
    }.contains(tool)) {
      final rows = await db.query(
        'mobile_agent_rows',
        where: 'collection=?',
        whereArgs: ['domain:tasks'],
        limit: 100,
      );
      return {
        'agent': {
          'domain': {
            'tasks': rows
                .map((r) => jsonDecode(r['payload'] as String))
                .toList(),
          },
        },
      };
    } else {
      throw StateError('Unsupported local read');
    }
    final clauses = <String>[];
    final values = <Object?>[];
    if (id != null) {
      clauses.add('id=?');
      values.add(id);
    }
    if (ids != null) {
      if (ids.length > 50) throw StateError('Too many selected records');
      clauses.add('id IN (${List.filled(ids.length, '?').join(',')})');
      values.addAll(ids);
    }
    final query = (args['query'] ?? args['criteria'] ?? '').toString().trim();
    if (query.isNotEmpty) {
      final fields = table == 'notes'
          ? ['title', 'content']
          : table == 'reminders'
          ? ['title', 'body']
          : ['name', 'address'];
      final words = query
          .split(RegExp(r'\s+'))
          .where((w) => w.length > 1)
          .take(8);
      final matches = <String>[];
      for (final word in words) {
        for (final field in fields) {
          matches.add('lower($field) LIKE ?');
          values.add('%${word.toLowerCase()}%');
        }
      }
      if (matches.isNotEmpty) clauses.add('(${matches.join(' OR ')})');
    }
    final limit = tool.startsWith('delete_all_')
        ? 1000
        : ((args['limit'] as num?)?.toInt() ?? 100).clamp(1, 1000);
    final rows = await db.query(
      table,
      where: clauses.isEmpty ? null : clauses.join(' AND '),
      whereArgs: values,
      orderBy: 'updated_at DESC',
      limit: limit,
    );
    if (tool.startsWith('delete_all_')) {
      final count =
          Sqflite.firstIntValue(
            await db.rawQuery('SELECT COUNT(*) FROM $table'),
          ) ??
          0;
      if (count > limit)
        throw StateError(
          'Too many records for one bulk change. Select a smaller set.',
        );
    }
    return {
      'records': {table: rows},
    };
  }

  Future<Map<String, dynamic>> historyContext(
    DateTime start,
    DateTime end,
  ) async {
    if (end.difference(start) > const Duration(days: 31)) {
      throw StateError('Choose at most 31 days');
    }
    final db = await database();
    final rows = await db.query(
      'mobile_agent_rows',
      where: 'collection LIKE ?',
      whereArgs: ['users/%'],
      orderBy: 'updated_at DESC',
    );
    final docs = <Map<String, dynamic>>[];
    for (final row in rows) {
      final value = Map<String, dynamic>.from(
        jsonDecode(row['payload'] as String),
      );
      final rawStamp =
          (value['timestamp'] ??
          value['last_updated'] ??
          value['last_observed_at'] ??
          value['started_at'] ??
          value['start_at'] ??
          '');
      final stamp = DateTime.tryParse(
        (rawStamp is Map ? rawStamp['__jarvis_datetime__'] : rawStamp)
            .toString(),
      );
      if (stamp == null ||
          stamp.isBefore(start.subtract(const Duration(minutes: 5))) ||
          stamp.isAfter(end)) {
        continue;
      }
      docs.add({
        'collection': row['collection'],
        'id': row['id'],
        'data': value,
      });
      if (docs.length > 5000)
        throw StateError('Too many observations. Select a shorter time range.');
    }
    return {
      'agent': {'documents': docs},
    };
  }

  Future<void> apply(Map<String, dynamic> changes) async {
    final db = await database();
    var conflicts = 0;
    final operation = changes['operation_id']?.toString();
    final base = Map<String, dynamic>.from(
      changes['base_versions'] as Map? ?? {},
    );
    await db.transaction((tx) async {
      if (operation != null) {
        final committed = await tx.query(
          'mobile_commits',
          where: 'operation_id=?',
          whereArgs: [operation],
        );
        if (committed.isNotEmpty) {
          conflicts = (committed.single['conflicts'] as num).toInt();
          return;
        }
      }
      for (final table in ['reminders', 'notes', 'places']) {
        final columns = (await tx.rawQuery(
          'PRAGMA table_info($table)',
        )).map((r) => r['name']).toSet();
        final versions = Map<String, dynamic>.from(base[table] as Map? ?? {});
        for (final raw
            in (changes['records'] as Map? ?? {})[table] as List? ?? []) {
          final value = Map<String, dynamic>.from(raw);
          final id = value['id']?.toString();
          if (id == null) continue;
          final rows = await tx.query(table, where: 'id=?', whereArgs: [id]);
          final old = rows.isEmpty ? <String, Object?>{} : rows.single;
          if (rows.isNotEmpty && old['updated_at'] != versions[id]) {
            conflicts++;
            continue;
          }
          final data = <String, Object?>{...old};
          for (final entry in value.entries) {
            if (!columns.contains(entry.key)) continue;
            final v = entry.value;
            data[entry.key] = v is Map || v is List
                ? jsonEncode(v)
                : v is bool
                ? (v ? 1 : 0)
                : v;
          }
          data['id'] = id;
          data['sync_status'] = 'synced';
          await tx.insert(
            table,
            data,
            conflictAlgorithm: ConflictAlgorithm.replace,
          );
        }
        for (final id
            in (changes['deleted'] as Map? ?? {})[table] as List? ?? []) {
          final rows = await tx.query(table, where: 'id=?', whereArgs: [id]);
          if (rows.isNotEmpty && rows.single['updated_at'] == versions[id]) {
            await tx.delete(table, where: 'id=?', whereArgs: [id]);
          }
        }
      }
      final agent = Map<String, dynamic>.from(changes['agent'] as Map? ?? {});
      Future<void> save(String collection, String id, Map value) async =>
          tx.insert('mobile_agent_rows', {
            'collection': collection,
            'id': id,
            'payload': jsonEncode(value),
            'updated_at': DateTime.now().millisecondsSinceEpoch,
          }, conflictAlgorithm: ConflictAlgorithm.replace);
      for (final entry in (agent['domain'] as Map? ?? {}).entries) {
        for (final raw in entry.value as List) {
          final value = Map<String, dynamic>.from(raw);
          final id =
              (value.remove('__key') ??
                      value['id'] ??
                      value['session_id'] ??
                      value['event_id'] ??
                      jsonEncode(value))
                  .toString();
          await save('domain:${entry.key}', id, value);
        }
      }
      for (final row in agent['documents'] as List? ?? []) {
        await save(row['collection'], row['id'], row['data']);
      }
      for (final entry in (agent['domain_deleted'] as Map? ?? {}).entries) {
        for (final id in entry.value as List) {
          await tx.delete(
            'mobile_agent_rows',
            where: 'collection=? AND id=?',
            whereArgs: ['domain:${entry.key}', id],
          );
        }
      }
      final usage = changes['budget'] as Map? ?? {};
      final receipt = changes['operation_id']?.toString();
      if (receipt != null && usage['day'] != null) {
        final rows = await tx.query(
          'mobile_receipts',
          where: 'operation_id=?',
          whereArgs: [receipt],
        );
        final previous = rows.isEmpty ? <String, Object?>{} : rows.single;
        final delta = [
          for (final key in ['cost_nanos', 'call_count', 'estimated_tokens'])
            ((usage[key] as num?)?.toInt() ?? 0) -
                ((previous[key] as num?)?.toInt() ?? 0),
        ];
        if (delta.every((v) => v >= 0)) {
          await tx.rawInsert(
            'INSERT INTO mobile_usage(day,cost_nanos,call_count,estimated_tokens) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET cost_nanos=cost_nanos+excluded.cost_nanos,call_count=call_count+excluded.call_count,estimated_tokens=estimated_tokens+excluded.estimated_tokens',
            [usage['day'], ...delta],
          );
          await tx.insert('mobile_receipts', {
            'operation_id': receipt,
            'cost_nanos': usage['cost_nanos'] ?? 0,
            'call_count': usage['call_count'] ?? 0,
            'estimated_tokens': usage['estimated_tokens'] ?? 0,
          }, conflictAlgorithm: ConflictAlgorithm.replace);
        }
      }
      final hasChanges =
          (changes['records'] as Map? ?? {}).values.any(
            (v) => (v as List).isNotEmpty,
          ) ||
          (changes['deleted'] as Map? ?? {}).values.any(
            (v) => (v as List).isNotEmpty,
          ) ||
          usage.isNotEmpty;
      if (operation != null && hasChanges)
        await tx.insert('mobile_commits', {
          'operation_id': operation,
          'conflicts': conflicts,
        });
    });
    await ReminderAlertService.sync(await _local.getReminders());
    for (final raw in changes['notifications'] as List? ?? []) {
      final n = Map<String, dynamic>.from(raw);
      final payload = n['payload'] as Map? ?? {};
      await _channel.invokeMethod('showCloudNotification', {
        'id': n['id'],
        'title': n['title'] ?? 'Jarvis',
        'body': n['body'] ?? '',
        'thread_id': n['thread_id'] ?? '',
        'kind': n['kind'] ?? '',
        'delivery_mode': payload['delivery_mode'] ?? 'notification',
        'reminder_id': n['reminder_id'] ?? '',
        'alarm_due_at': payload['alarm_due_at'] ?? '',
        'occurred_at': payload['occurred_at'] ?? '',
      });
    }
    _local.notifyLocalChanges();
    if (conflicts > 0)
      throw const MobileSaveException(
        'Some records changed on your phone while Jarvis was working. Those newer edits were kept. Review the records before retrying.',
      );
  }
}
