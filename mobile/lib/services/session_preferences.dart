import 'dart:convert';
import 'package:http/http.dart' as http;
import 'local_db_service.dart';
import 'api_service.dart';

/// Cloud is authoritative; SQLite retains a read-only offline cache.
class SessionPreferences {
  late final _api = ApiService();
  Future<Map<String, Map<String, Object?>>> load() async {
    final db = await LocalDbService().database;
    await db.execute(
      'CREATE TABLE IF NOT EXISTS session_preferences '
      '(id TEXT PRIMARY KEY, name TEXT, archived INTEGER NOT NULL DEFAULT 0)',
    );
    try {
      final response = await http
          .get(
            Uri.parse('${_api.baseUrl}/session-library/preferences'),
            headers: {'X-User-ID': _api.userId},
          )
          .timeout(const Duration(seconds: 20));
      if (response.statusCode != 200) throw Exception('Cloud unavailable');
      final items = (jsonDecode(response.body)['items'] as List)
          .cast<Map<String, dynamic>>();
      await db.transaction((txn) async {
        await txn.delete('session_preferences');
        for (final item in items) {
          await txn.rawInsert(
            'INSERT INTO session_preferences (id, name, archived) VALUES (?, ?, ?)',
            [item['id'], item['name'], item['archived'] == true ? 1 : 0],
          );
        }
      });
    } catch (_) {
      /* Offline display uses the last confirmed cloud copy. */
    }
    return {
      for (final row in await db.query('session_preferences'))
        row['id'] as String: row,
    };
  }

  Future<void> save(String id, String? name, bool archived) async {
    final response = await http
        .put(
          Uri.parse('${_api.baseUrl}/session-library/preferences'),
          headers: {
            'X-User-ID': _api.userId,
            'Content-Type': 'application/json',
          },
          body: jsonEncode({'id': id, 'name': name, 'archived': archived}),
        )
        .timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception('Could not save to Firebase');
    }
    final db = await LocalDbService().database;
    await db.rawInsert(
      'INSERT OR REPLACE INTO session_preferences (id, name, archived) VALUES (?, ?, ?)',
      [id, name, archived ? 1 : 0],
    );
  }
}
