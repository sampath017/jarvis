import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/mobile_store.dart';
import 'package:jarvis_collector/services/mobile_sql_storage.dart';
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
      final appendState = await store.readForTool('append_note', {
        'note_id': 'requested',
      });
      expect(
        (appendState['records']['notes'] as List).single['id'],
        'requested',
      );
      final subjectState = await store.readForTool('create_note', {
        'title': ' INVOICE ',
      });
      expect(
        (subjectState['records']['notes'] as List).single['id'],
        'requested',
      );
      expect(jsonEncode(subjectState), isNot(contains('private data')));
      await db.insert('notes', {
        'id': 'duplicate',
        'title': 'Invoice',
        'content': 'A second subject match',
        'updated_at': 'v1',
        'created_at': 'v1',
      });
      final ambiguousState = await store.readForTool('create_note', {
        'title': 'invoice',
      });
      expect((ambiguousState['records']['notes'] as List).length, 2);
      Future<void> domain(String table, String id, Map value, int at) =>
          MobileSqlStorage.put(
            db,
            table,
            id,
            Map<String, dynamic>.from(value),
            domain: true,
            storedAt: at,
          );
      await domain('context_events', 'latest', {
        'id': 'latest',
        'activity': 'WALKING',
        'timestamp': '2026-10-28T08:30:00+00:00',
      }, 1);
      await domain('context_events', 'replayed', {
        'id': 'replayed',
        'activity': 'STILL',
        'timestamp': '2026-10-28T07:30:00+00:00',
      }, 2);
      await db.insert('reminders', {
        'id': 'helmet',
        'title': 'Helmet',
        'activity': 'IN_VEHICLE',
        'created_at': 'v1',
        'updated_at': 'v1',
      });
      await db.insert('reminders', {
        'id': 'private-reminder',
        'title': 'Private reminder',
        'created_at': 'v1',
        'updated_at': 'v1',
      });
      await domain('context_trigger_state', 'helmet', {
        'source_type': 'REMINDER',
        'source_id': 'helmet',
        'is_inside': 0,
      }, 2);
      await domain('context_trigger_state', 'private-reminder', {
        'source_type': 'REMINDER',
        'source_id': 'private-reminder',
        'is_inside': 0,
      }, 2);
      for (final tool in [
        'get_current_context',
        'get_motion_evidence',
        'get_monitoring_status',
      ]) {
        final context = await store.readForTool(tool, {});
        expect(
          context['agent']['domain']['context_events'].single['id'],
          'latest',
        );
        expect(jsonEncode(context), isNot(contains('private')));
        expect(context.containsKey('records'), false);
      }
      final preview = await store.readForTool('preview_reminder_match', {
        'reminder_id': 'helmet',
      });
      expect(preview['records']['reminders'].single['id'], 'helmet');
      expect(
        preview['agent']['domain']['context_trigger_state'].single['source_id'],
        'helmet',
      );
      expect(jsonEncode(preview), isNot(contains('private')));
      await db.insert('places', {
        'id': 'home',
        'name': 'Home',
        'latitude': 12.5,
        'longitude': 77.5,
        'created_at': 'v1',
        'updated_at': 'v1',
      });
      final geofences = await store.readForTool('check_saved_geofences', {});
      expect(geofences['records']['places'].single['id'], 'home');
      expect(jsonEncode(geofences), isNot(contains('private')));
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
      final usageBeforeRejected = await db.query('mobile_usage');
      await expectLater(
        store.apply({
          'operation_id': 'unsupported-state',
          'agent': {'unsupported_state': <String, dynamic>{}},
          'budget': {'day': '2026-10-24', 'cost_nanos': 999},
        }),
        throwsA(isA<MobileSaveException>()),
      );
      await expectLater(
        store.apply({'agent': <dynamic>[]}),
        throwsA(isA<MobileSaveException>()),
      );
      expect(await db.query('mobile_usage'), usageBeforeRejected);
      expect(
        await db.query(
          'mobile_commits',
          where: 'operation_id=?',
          whereArgs: ['unsupported-state'],
        ),
        isEmpty,
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
