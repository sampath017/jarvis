import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/mobile_store.dart';
import 'package:jarvis_collector/services/mobile_sql_storage.dart';
import 'support/local_database.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'entity SQL preserves owners, types, transactions and unrelated records',
    () async {
      final close = await startLocalDatabase();
      addTearDown(close);
      final db = await MobileStore.instance.database();
      await db.insert('notes', {
        'id': 'note',
        'title': 'Keep',
        'content': 'User note',
      });
      await db.insert('reminders', {
        'id': 'reminder',
        'title': 'Keep',
        'status': 'ACTIVE',
      });
      await db.insert('chat_sessions', {'id': 'thread', 'title': 'Keep'});
      await db.insert('chat_messages', {
        'id': 'message',
        'thread_id': 'thread',
        'role': 'user',
        'content': 'Keep chat',
        'timestamp': '2026-10-28T08:00:00Z',
      });
      await db.insert('mobile_usage', {
        'day': '2026-10-28',
        'cost_nanos': 42,
        'call_count': 3,
        'estimated_tokens': 100,
      });
      await db.insert('mobile_receipts', {
        'operation_id': 'paid',
        'cost_nanos': 42,
        'call_count': 3,
        'estimated_tokens': 100,
      });
      final untouched = <String, List<Map<String, Object?>>>{};
      for (final table in [
        'notes',
        'reminders',
        'chat_sessions',
        'chat_messages',
        'mobile_usage',
        'mobile_receipts',
      ]) {
        untouched[table] = await db.query(table);
      }
      await MobileSqlStorage.put(
        db,
        'mobility_sessions',
        'same',
        {'id': 'same', 'status': 'ACTIVE', 'events_json': '["original"]'},
        domain: true,
        storedAt: 100,
      );
      await MobileSqlStorage.put(db, 'mobility_sessions', 'same', {
        'session_id': 'same',
        'status': 'PAUSED',
        'parking_gps': {'latitude': 12.0},
      }, storedAt: 200);
      await MobileSqlStorage.put(
        db,
        'mobility_sessions',
        'same',
        {'session_id': 'same', 'status': 'COMPLETED'},
        uid: 'second-owner',
        storedAt: 300,
      );
      final typed = <String, dynamic>{
        'state': 'PARKED',
        'active': true,
        'confidence': 0.85,
        'context_id': null,
        'last_observed_at': {
          '__jarvis_datetime__': '2026-10-20T08:00:00+00:00',
        },
        'nested': {
          'allowed': false,
          'empty': null,
          'values': [1, 2.5, 'text', null],
        },
      };
      await MobileSqlStorage.put(
        db,
        'semantic_contexts',
        'typed',
        typed,
        storedAt: 350,
      );
      await MobileSqlStorage.put(db, 'context_memory', 'observation', {
        'timestamp': '2026-10-20T08:00:00Z',
        'activity': 'WALKING',
        'activity_evidence': 'android_transition',
        'gps': {'latitude': 12.0, 'longitude': 77.0},
      }, storedAt: 1792483200000);
      final domain = (await MobileSqlStorage.domainRows(
        db,
        'mobility_sessions',
      )).single;
      expect(domain['status'], 'ACTIVE');
      expect(domain['events_json'], '["original"]');
      expect(domain['__key'], 'same');
      final records = (await MobileSqlStorage.records(
        db,
        'mobility_sessions',
      )).single;
      expect(records['data']['status'], 'PAUSED');
      expect(records['data']['parking_gps']['latitude'], 12.0);
      expect(
        (await MobileSqlStorage.records(
          db,
          'mobility_sessions',
          uid: 'second-owner',
        )).single['data']['status'],
        'COMPLETED',
      );
      expect(
        (await MobileSqlStorage.records(
          db,
          'semantic_contexts',
        )).single['data'],
        typed,
      );
      final indexed = (await db.query('record_semantic_contexts')).single;
      expect(indexed['active'], 1);
      expect(indexed['last_observed_at'], '2026-10-20T08:00:00+00:00');
      expect(indexed['stored_at'], 350);
      expect(
        (await db.query('record_context_memory')).single['stored_at'],
        1792483200000,
      );
      await expectLater(
        db.transaction((transaction) async {
          await MobileSqlStorage.put(
            transaction,
            'context_requests',
            'rollback',
            {'status': 'received'},
          );
          await MobileSqlStorage.put(transaction, 'mobility_sessions', 'same', {
            'status': 'WRONG',
          });
          throw StateError('synthetic transaction failure');
        }),
        throwsStateError,
      );
      expect(await MobileSqlStorage.records(db, 'context_requests'), isEmpty);
      expect(
        (await MobileSqlStorage.records(
          db,
          'mobility_sessions',
        )).single['data']['status'],
        'PAUSED',
      );
      await MobileSqlStorage.prepare(db);
      expect(
        (await MobileSqlStorage.records(
          db,
          'semantic_contexts',
        )).single['data'],
        typed,
      );
      for (final entry in untouched.entries) {
        expect(await db.query(entry.key), entry.value);
      }
      await MobileStore.instance.apply({
        'operation_id': 'typed-state',
        'agent': {
          'records': [
            {
              'table': 'semantic_contexts',
              'id': 'typed',
              'uid': MobileSqlStorage.localUid,
              'data': {
                'state': 'MOVING',
                'active': false,
                'details': {'source': 'verified'},
              },
            },
          ],
        },
      });
      final updated = (await MobileSqlStorage.records(
        db,
        'semantic_contexts',
      )).single['data'];
      expect(updated, {
        'state': 'MOVING',
        'active': false,
        'details': {'source': 'verified'},
      });
      await MobileStore.instance.apply({
        'operation_id': 'typed-remove',
        'agent': {
          'removed': [
            {
              'table': 'semantic_contexts',
              'id': 'typed',
              'uid': MobileSqlStorage.localUid,
            },
          ],
        },
      });
      expect(await MobileSqlStorage.records(db, 'semantic_contexts'), isEmpty);
      await MobileSqlStorage.remove(db, 'mobility_sessions', 'same');
      expect(await MobileSqlStorage.records(db, 'mobility_sessions'), isEmpty);
      expect(
        await MobileSqlStorage.records(
          db,
          'mobility_sessions',
          uid: 'second-owner',
        ),
        hasLength(1),
      );
      expect(
        await MobileSqlStorage.domainRows(db, 'mobility_sessions'),
        hasLength(1),
      );
      expect(() => MobileSqlStorage.physical('unsupported'), throwsStateError);
      await expectLater(
        MobileSqlStorage.put(db, 'semantic_contexts', '', {}),
        throwsStateError,
      );
    },
  );
}
