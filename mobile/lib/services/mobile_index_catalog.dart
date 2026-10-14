import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'mobile_store.dart';

/// Phone-only progress receipts. Chunks and embeddings remain in existing Chroma.
class MobileIndexCatalog {
  static final instance = MobileIndexCatalog();
  Future<Database> database() async {
    final db = await MobileStore.instance.database();
    await db.execute(
      'CREATE TABLE IF NOT EXISTS mobile_index_catalog(account TEXT,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(account,id))',
    );
    return db;
  }

  Future<void> save(Map memory, Map result, {String? reason}) async {
    final db = await database();
    final metadata = Map<String, dynamic>.from(memory)..remove('path');
    await db.insert('mobile_index_catalog', {
      'account': memory['account'],
      'id': memory['id'],
      'payload': jsonEncode({
        ...metadata,
        ...result,
        'file_id': memory['id'],
        'status': reason == null ? 'complete' : 'attention',
        'reason': reason ?? '',
      }),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<Map<String, dynamic>> request(String path, {Object? body}) async {
    final db = await database();
    final uri = Uri.parse(path);
    final data = Map<String, dynamic>.from(body as Map? ?? {});
    if (uri.path == '/catalog') {
      await save(data['memory'], {
        'coverage': 'metadata',
        'chunks': 0,
      }, reason: data['reason']);
      return {'status': 'ok'};
    }
    final account = uri.queryParameters['account'] ?? '';
    final after = uri.queryParameters['after'] ?? '';
    final rows = await db.query(
      'mobile_index_catalog',
      where: 'account=? AND id>?',
      whereArgs: [account, after],
      orderBy: 'id',
      limit: 101,
    );
    final items = rows
        .take(100)
        .map(
          (r) => Map<String, dynamic>.from(jsonDecode(r['payload'] as String)),
        )
        .toList();
    final counts = await db.rawQuery(
      'SELECT payload FROM mobile_index_catalog WHERE account=?',
      [account],
    );
    var complete = 0, attention = 0;
    for (final row in counts) {
      if (jsonDecode(row['payload'] as String)['status'] == 'complete') {
        complete++;
      } else {
        attention++;
      }
    }
    return {
      'items': items,
      'next_cursor': rows.length > 100 ? items.last['id'] : null,
      'counts': {'complete': complete, 'attention': attention},
    };
  }
}
