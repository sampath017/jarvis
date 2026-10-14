import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:sqflite/sqflite.dart';
import 'local_db_service.dart';
import 'mobile_sql_storage.dart';
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
    await MobileSqlStorage.prepare(db);
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

  /// A tool may read named SQL entities, IDs or a bounded search result only.
  Future<Map<String, dynamic>> readForTool(
    String tool,
    Map<String, dynamic> args,
  ) async {
    final db = await database();
    String? table;
    String? id;
    List<dynamic>? ids;
    if ({
      'get_current_context',
      'get_motion_evidence',
      'get_monitoring_status',
      'preview_reminder_match',
    }.contains(tool)) {
      final domain = <String, dynamic>{};
      // Replay/import time can differ from observation time. Select the latest
      // observation from a bounded recent window, preserving its timestamp.
      final observations = await _domainRows(db, 'context_events', 50);
      observations.sort(
        (a, b) => (b['timestamp'] ?? '').toString().compareTo(
          (a['timestamp'] ?? '').toString(),
        ),
      );
      domain['context_events'] = observations.take(1).toList();
      final records = <String, dynamic>{};
      if (tool == 'preview_reminder_match') {
        final reminderId = args['reminder_id']?.toString() ?? '';
        records['reminders'] = await db.query(
          'reminders',
          where: 'id=?',
          whereArgs: [reminderId],
          limit: 1,
        );
        domain['mobility_sessions'] =
            (await _domainRows(db, 'mobility_sessions', 30))
                .where(
                  (r) => {'ACTIVE', 'PAUSED', 'RESUMED'}.contains(r['status']),
                )
                .take(1)
                .toList();
        domain['context_trigger_state'] =
            (await _domainRows(db, 'context_trigger_state', 1000))
                .where(
                  (r) =>
                      r['source_type'] == 'REMINDER' &&
                      r['source_id'] == reminderId,
                )
                .toList();
      }
      return {
        if (records.isNotEmpty) 'records': records,
        'agent': {'domain': domain},
      };
    }
    if (tool == 'create_reminder') {
      final reminders = await db.query(
        'reminders',
        where: 'lower(title)=lower(?) AND status=?',
        whereArgs: [args['title'] ?? '', 'ACTIVE'],
        limit: 50,
      );
      final place =
          (args['journey_origin'] ?? args['location_name'])
              ?.toString()
              .trim() ??
          '';
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
      'create_note',
      'append_note',
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
      'check_saved_geofences',
      'check_user_geofences',
      'inspect_satellite_view',
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
      return {
        'agent': {
          'domain': {'tasks': await MobileSqlStorage.domainRows(db, 'tasks')},
        },
      };
    } else {
      throw StateError('Unsupported local read');
    }
    final clauses = <String>[];
    final values = <Object?>[];
    if (tool == 'create_note') {
      // Check the subject on the phone before creating a duplicate. Two rows
      // suffice to detect ambiguity; never choose the newest match silently.
      final title = args['title']?.toString().trim() ?? '';
      final rows = await db.query(
        'notes',
        where: 'deleted_at IS NULL AND lower(trim(title))=lower(?)',
        whereArgs: [title],
        limit: 2,
      );
      return {
        'records': {'notes': rows},
      };
    }
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
    if (tool == 'inspect_satellite_view') {
      final observations = await _domainRows(db, 'context_events', 50);
      observations.sort(
        (a, b) => (b['timestamp'] ?? '').toString().compareTo(
          (a['timestamp'] ?? '').toString(),
        ),
      );
      return {
        'records': {'places': rows},
        'agent': {
          'domain': {'context_events': observations.take(1).toList()},
        },
      };
    }
    if (tool.startsWith('delete_all_')) {
      final count =
          Sqflite.firstIntValue(
            await db.rawQuery('SELECT COUNT(*) FROM $table'),
          ) ??
          0;
      if (count > limit) {
        throw StateError(
          'Too many records for one bulk change. Select a smaller set.',
        );
      }
    }
    final extraPlaces = args['journey_origin']?.toString().trim() ?? '';
    return {
      'records': {
        table: rows,
        if (table == 'reminders' && extraPlaces.isNotEmpty)
          'places': await db.query(
            'places',
            where: 'lower(name)=lower(?)',
            whereArgs: [extraPlaces],
            limit: 10,
          ),
      },
    };
  }

  Future<List<Map<String, dynamic>>> _domainRows(
    Database db,
    String table,
    int limit,
  ) async {
    return MobileSqlStorage.domainRows(db, table, limit: limit);
  }

  Future<Map<String, dynamic>> historyContext(
    DateTime start,
    DateTime end,
  ) async {
    if (end.difference(start) > const Duration(days: 31)) {
      throw StateError('Choose at most 31 days');
    }
    final db = await database();
    final rows = <Map<String, dynamic>>[];
    for (final table in [
      'context_memory',
      'mobility_sessions',
      'semantic_contexts',
      'activity_routines',
      'activity_sessions',
    ]) {
      rows.addAll(await MobileSqlStorage.records(db, table));
    }
    final records = <Map<String, dynamic>>[];
    for (final row in rows) {
      final value = Map<String, dynamic>.from(row['data'] as Map);
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
      records.add({...row, 'data': value});
      if (records.length > 5000) {
        throw StateError('Too many observations. Select a shorter time range.');
      }
    }
    // Power history is local evidence, available even after a long offline pause.
    // Clip the query timestamp so an interval starting before the window is read.
    try {
      const power = MethodChannel('com.jarvis/power');
      final intervals = await power.invokeListMethod<dynamic>('history') ?? [];
      for (final raw in intervals) {
        final interval = Map<String, dynamic>.from(raw as Map);
        final off = DateTime.parse(interval['start_at'] as String).toUtc();
        final on = DateTime.tryParse(
          interval['end_at']?.toString() ?? '',
        )?.toUtc();
        if (off.isAfter(end) || (on != null && !on.isAfter(start))) continue;
        records.add({
          'table': 'context_memory',
          'uid': MobileSqlStorage.localUid,
          'id': 'power-off:${interval['id']}',
          'data': {
            'event_id': 'power-off:${interval['id']}',
            'event_type': 'JARVIS_OFF_INTERVAL',
            'source': 'phone_power_switch',
            'timestamp': (off.isBefore(start) ? start : off).toIso8601String(),
            'power_off_at': off.toIso8601String(),
            'power_on_at': on?.toIso8601String(),
            'activity': 'UNKNOWN',
            'activity_evidence': 'power_state',
          },
        });
      }
    } on MissingPluginException {
      // Older native builds have no historical switch evidence; do not invent it.
    }
    return {
      'agent': {'records': records},
    };
  }

  Future<void> apply(Map<String, dynamic> changes) async {
    final suppliedAgent = changes['agent'];
    if (suppliedAgent != null && suppliedAgent is! Map) {
      throw const MobileSaveException(
        'Jarvis returned an unsupported state format. Update the API before retrying.',
      );
    }
    final agent = Map<String, dynamic>.from(suppliedAgent as Map? ?? {});
    if (agent.keys.any(
      (key) =>
          !{'domain', 'domain_deleted', 'records', 'removed'}.contains(key),
    )) {
      throw const MobileSaveException(
        'Jarvis returned an unsupported state format. Update the API before retrying.',
      );
    }
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
          await MobileSqlStorage.put(
            tx,
            entry.key.toString(),
            id,
            value,
            uid: value['uid']?.toString() ?? MobileSqlStorage.localUid,
            domain: true,
          );
        }
      }
      for (final raw in agent['records'] as List? ?? []) {
        final row = Map<String, dynamic>.from(raw);
        await MobileSqlStorage.put(
          tx,
          row['table'].toString(),
          row['id'].toString(),
          Map<String, dynamic>.from(row['data'] as Map),
          uid: row['uid']?.toString() ?? MobileSqlStorage.localUid,
        );
      }
      for (final raw in agent['removed'] as List? ?? []) {
        final row = Map<String, dynamic>.from(raw);
        await MobileSqlStorage.remove(
          tx,
          row['table'].toString(),
          row['id'].toString(),
          uid: row['uid']?.toString() ?? MobileSqlStorage.localUid,
        );
      }
      for (final entry in (agent['domain_deleted'] as Map? ?? {}).entries) {
        for (final id in entry.value as List) {
          await MobileSqlStorage.remove(
            tx,
            entry.key.toString(),
            id.toString(),
            domain: true,
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
      if (operation != null && hasChanges) {
        await tx.insert('mobile_commits', {
          'operation_id': operation,
          'conflicts': conflicts,
        });
      }
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
    if (conflicts > 0) {
      throw const MobileSaveException(
        'Some records changed on your phone while Jarvis was working. Those newer edits were kept. Review the records before retrying.',
      );
    }
  }
}
