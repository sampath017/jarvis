import 'local_db_service.dart';

/// Recording names and archive choices live only in the phone database.
class SessionPreferences {
  Future<Map<String, Map<String, Object?>>> load() async {
    final db = await LocalDbService().database;
    await db.execute(
      'CREATE TABLE IF NOT EXISTS session_preferences '
      '(id TEXT PRIMARY KEY, name TEXT, archived INTEGER NOT NULL DEFAULT 0)',
    );
    return {
      for (final row in await db.query('session_preferences'))
        row['id'] as String: row,
    };
  }

  Future<void> save(String id, String? name, bool archived) async {
    await load();
    final db = await LocalDbService().database;
    await db.rawInsert(
      'INSERT OR REPLACE INTO session_preferences (id,name,archived) VALUES (?,?,?)',
      [id, name, archived ? 1 : 0],
    );
  }
}
