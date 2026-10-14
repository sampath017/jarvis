import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/mobile_store.dart';
import 'package:jarvis_collector/services/mobile_index_catalog.dart';
import 'package:jarvis_collector/services/power_http.dart'
    show MobileSaveException;
import 'support/local_database.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'scoped reads, change commits, concurrent edits, budget dedupe and Chroma progress receipts',
    () async {
      final close = await startLocalDatabase();
      addTearDown(close);
      final store = MobileStore.instance;
      final opened = await Future.wait(
        List.generate(8, (_) => store.database()),
      );
      final db = opened.first;
      expect(opened.every((connection) => identical(connection, db)), true);
      await db.insert('notes', {
        'id': 'requested',
        'title': 'invoice',
        'content': 'invoice A',
        'updated_at': 'v1',
        'created_at': 'v1',
      });
      await db.insert('notes', {
        'id': 'private',
        'title': 'diary',
        'content': 'unrelated private data',
        'updated_at': 'v1',
        'created_at': 'v1',
      });
      expect((await store.commandContext()).keys, ['budget']);
      final state = await store.readForTool('update_note', {
        'note_id': 'requested',
      });
      expect((state['records']['notes'] as List).single['id'], 'requested');
      expect(jsonEncode(state), isNot(contains('private data')));
      final changes = <String, dynamic>{
        'operation_id': 'one',
        'base_versions': {
          'notes': {'requested': 'v1'},
        },
        'records': {
          'notes': [
            {'id': 'requested', 'content': 'updated', 'updated_at': 'v2'},
          ],
        },
        'budget': {
          'day': '2026-10-24',
          'cost_nanos': 50,
          'call_count': 1,
          'estimated_tokens': 10,
        },
      };
      await store.apply(changes);
      await store.apply(changes);
      expect((await db.query('mobile_usage')).single['cost_nanos'], 50);
      expect(
        (await db.query(
          'notes',
          where: 'id=?',
          whereArgs: ['requested'],
        )).single['content'],
        'updated',
      );
      await db.update(
        'notes',
        {'content': 'new phone edit', 'updated_at': 'v3'},
        where: 'id=?',
        whereArgs: ['requested'],
      );
      await store.apply(changes);
      expect(
        (await db.query(
          'notes',
          where: 'id=?',
          whereArgs: ['requested'],
        )).single['content'],
        'new phone edit',
      );
      final conflict = {...changes, 'operation_id': 'conflict'};
      await expectLater(
        store.apply(conflict),
        throwsA(isA<MobileSaveException>()),
      );
      await expectLater(
        store.apply(conflict),
        throwsA(isA<MobileSaveException>()),
      );
      await MobileIndexCatalog.instance.save(
        {'id': 'f', 'account': 'a'},
        {'chunks': 200, 'coverage': 'content'},
      );
      final result = await MobileIndexCatalog.instance.request(
        '/results?account=a',
      );
      expect((result['items'] as List).single['chunks'], 200);
      expect(
        await db.rawQuery(
          "SELECT name FROM sqlite_master WHERE name IN ('local_file_text','local_file_vectors')",
        ),
        isEmpty,
      );
    },
  );
}
