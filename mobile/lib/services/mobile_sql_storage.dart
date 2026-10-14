import 'dart:convert';
import 'package:sqflite/sqflite.dart';

/// Fixed SQL entities shared by the UI and native worker. No path-based storage API.
class MobileSqlStorage {
  static const localUid = 'jarvis_local_user';
  static const domainColumns = <String, String>{
    'tasks':
        'id TEXT,title TEXT,description TEXT,due_date TEXT,priority TEXT,status TEXT,created_at TEXT,updated_at TEXT',
    'preferences':
        'id TEXT,key TEXT,value TEXT,source TEXT,created_at TEXT,updated_at TEXT',
    'automations':
        'id TEXT,name TEXT,trigger_type TEXT,action_type TEXT,enabled INTEGER,created_at TEXT,updated_at TEXT',
    'context_rules':
        'id TEXT,name TEXT,trigger_type TEXT,action_type TEXT,enabled INTEGER,one_shot INTEGER,last_fired_at TEXT,created_at TEXT,updated_at TEXT',
    'context_events':
        'id TEXT,activity TEXT,transition TEXT,gps_lat REAL,gps_lon REAL,gps_accuracy_m REAL,timestamp TEXT,session_id TEXT,created_at TEXT',
    'mobility_sessions':
        'id TEXT,status TEXT,vehicle_class TEXT,confidence REAL,started_at TEXT,last_updated TEXT,paused_at TEXT,completed_at TEXT,created_at TEXT,updated_at TEXT',
    'dynamic_reminder_state': 'reminder_id TEXT',
    'context_trigger_state':
        'source_type TEXT,source_id TEXT,is_inside INTEGER,last_event_id TEXT,last_seen_at TEXT',
  };
  static const recordColumns = <String, String>{
    'mobility_sessions':
        'session_id TEXT,status TEXT,vehicle_class TEXT,last_updated TEXT,started_at TEXT,paused_at TEXT,completed_at TEXT,classification_confidence REAL',
    'dynamic_reminder_state': 'payload TEXT',
    'semantic_contexts':
        'state TEXT,active INTEGER,confidence REAL,last_observed_at TEXT,updated_at TEXT,context_id TEXT,mobility_session_id TEXT',
    'context_memory':
        'timestamp TEXT,activity TEXT,transition TEXT,event_id TEXT,event_type TEXT,source TEXT,mobility_session_id TEXT',
    'activity_routines': 'through TEXT,computed_at TEXT',
    'activity_sessions':
        'session_id TEXT,status TEXT,activity TEXT,started_at TEXT,last_updated TEXT,through TEXT,computed_at TEXT',
    'activity_cache_state': 'mobility INTEGER',
    'context_processing_errors':
        'event_id TEXT,status TEXT,timestamp TEXT,created_at TEXT,updated_at TEXT',
    'context_requests':
        'request_id TEXT,status TEXT,created_at TEXT,expires_at TEXT,received_at TEXT,location_status TEXT,event_id TEXT',
    'context_identity': 'fingerprint_salt TEXT,created_at TEXT',
    'motion_diagnostics':
        'timestamp TEXT,source TEXT,candidate TEXT,provisional INTEGER,model_version TEXT,event_id TEXT',
    'ai_usage':
        'day TEXT,call_count INTEGER,estimated_tokens INTEGER,cost_nanos INTEGER,updated_at TEXT',
  };

  static String physical(String table, {bool domain = false}) {
    if (!(domain ? domainColumns : recordColumns).containsKey(table)) {
      throw StateError('Unsupported SQLite entity: $table');
    }
    return '${domain ? 'domain' : 'record'}_$table';
  }

  static List<String> fields(String table, {bool domain = false}) =>
      (domain ? domainColumns : recordColumns)[table]!
          .split(',')
          .map((part) => part.trim().split(' ').first)
          .toList();

  static Future<void> prepare(Database db) =>
      db.transaction(prepareInTransaction);

  static Future<void> prepareInTransaction(DatabaseExecutor db) async {
    final meta = await db.rawQuery(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='mobile_schema_meta'",
    );
    if (meta.isNotEmpty &&
        (await db.query(
          'mobile_schema_meta',
          where: 'key=? AND value=?',
          whereArgs: ['entity_schema', '1'],
        )).isNotEmpty) {
      return;
    }
    for (final domain in [false, true]) {
      for (final entry in (domain ? domainColumns : recordColumns).entries) {
        final table = physical(entry.key, domain: domain);
        await db.execute(
          'CREATE TABLE IF NOT EXISTS $table '
          '(row_key TEXT NOT NULL,uid TEXT NOT NULL,${entry.value},'
          "extra_json TEXT NOT NULL DEFAULT '{}',stored_at INTEGER NOT NULL,PRIMARY KEY(uid,row_key))",
        );
        await db.execute(
          'CREATE INDEX IF NOT EXISTS idx_${table}_recent ON $table(uid,stored_at)',
        );
        for (final field in fields(entry.key, domain: domain)) {
          if ({
            'timestamp',
            'status',
            'last_observed_at',
            'started_at',
          }.contains(field)) {
            await db.execute(
              'CREATE INDEX IF NOT EXISTS idx_${table}_$field ON $table(uid,$field)',
            );
          }
        }
      }
    }
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_schema_meta '
      '(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
    );
    await db.insert('mobile_schema_meta', {
      'key': 'entity_schema',
      'value': '1',
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  static Future<void> put(
    DatabaseExecutor db,
    String table,
    String id,
    Map<String, dynamic> data, {
    String uid = localUid,
    bool domain = false,
    int? storedAt,
  }) async {
    if (id.isEmpty || uid.isEmpty) {
      throw StateError('SQLite entity requires an ID and owner');
    }
    final target = physical(table, domain: domain);
    final extra = Map<String, dynamic>.from(data);
    final row = <String, Object?>{
      'row_key': id,
      'uid': uid,
      'stored_at': storedAt ?? DateTime.now().millisecondsSinceEpoch,
    };
    for (final field in fields(table, domain: domain)) {
      final value = data[field];
      if (value is String || value is num) {
        row[field] = value;
        final definition = (domain ? domainColumns : recordColumns)[table]!
            .split(',')
            .firstWhere((part) => part.trim().startsWith('$field '))
            .trim();
        if ((value is String && definition.endsWith(' TEXT')) ||
            (value is int && definition.endsWith(' INTEGER'))) {
          extra.remove(field);
        }
      } else if (value is bool) {
        row[field] = value ? 1 : 0;
      } else if (value is Map &&
          value.length == 1 &&
          value['__jarvis_datetime__'] is String) {
        row[field] = value['__jarvis_datetime__'] as String;
      }
    }
    row['extra_json'] = jsonEncode(extra);
    await db.insert(target, row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  static Map<String, dynamic> data(
    String table,
    Map<String, Object?> row, {
    bool domain = false,
  }) => {
    for (final field in fields(table, domain: domain))
      if (row[field] != null) field: row[field],
    ...Map<String, dynamic>.from(
      jsonDecode(row['extra_json'] as String) as Map,
    ),
  };

  static Future<List<Map<String, dynamic>>> domainRows(
    DatabaseExecutor db,
    String table, {
    int limit = 100,
    String uid = localUid,
  }) async => [
    for (final row in await db.query(
      physical(table, domain: true),
      where: 'uid=?',
      whereArgs: [uid],
      orderBy: 'stored_at DESC',
      limit: limit,
    ))
      {...data(table, row, domain: true), '__key': row['row_key']},
  ];

  static Future<List<Map<String, dynamic>>> records(
    DatabaseExecutor db,
    String table, {
    int? limit,
    String uid = localUid,
  }) async => [
    for (final row in await db.query(
      physical(table),
      where: 'uid=?',
      whereArgs: [uid],
      orderBy: 'stored_at DESC',
      limit: limit,
    ))
      {
        'table': table,
        'id': row['row_key'],
        'uid': row['uid'],
        'data': data(table, row),
      },
  ];

  static Future<int> remove(
    DatabaseExecutor db,
    String table,
    String id, {
    String uid = localUid,
    bool domain = false,
  }) => db.delete(
    physical(table, domain: domain),
    where: 'uid=? AND row_key=?',
    whereArgs: [uid, id],
  );
}
