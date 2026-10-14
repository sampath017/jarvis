import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/local_db_service.dart';
import 'package:jarvis_collector/services/sync_page.dart';
import 'package:jarvis_collector/services/session_preferences.dart';
import 'package:jarvis_collector/models/chat_session.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  databaseFactory = databaseFactorySqflitePlugin;

  test(
    'summary list skips bodies; real SQLite pagination and cursor commits preserve history',
    () async {
      final python = Platform.environment['JARVIS_TEST_PYTHON'] ?? 'python';
      final process = await Process.start(python, [
        '-u',
        '../tests/android/ui/support/sqlite_bridge.py',
      ]);
      final replies = StreamIterator(
        process.stdout.transform(utf8.decoder).transform(const LineSplitter()),
      );
      final queries = <Map>[];
      var failBatch = false;
      Future<dynamic> sql(Map value) async {
        process.stdin.writeln(jsonEncode(value));
        await process.stdin.flush();
        if (!await replies.moveNext()) {
          throw StateError('SQLite test process stopped');
        }
        final response = jsonDecode(replies.current) as Map;
        if (response['error'] != null) {
          throw PlatformException(
            code: 'sqlite_error',
            message: '${response['error']}',
          );
        }
        return response['result'];
      }

      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(
        const MethodChannel('com.tekartik.sqflite'),
        (call) async {
          if (call.method == 'getDatabasesPath') {
            return Directory.systemTemp.path;
          }
          if (call.method == 'openDatabase') return {'id': 1};
          if (call.method == 'closeDatabase') return null;
          final args = Map<String, dynamic>.from(call.arguments as Map);
          if (call.method == 'batch') {
            if (failBatch) {
              failBatch = false;
              throw PlatformException(
                code: 'sqlite_error',
                message: 'Simulated storage failure',
              );
            }
            final result = await sql({
              'method': 'batch',
              'operations': args['operations'],
            });
            return args['noResult'] == true ? null : result;
          }
          if (args['sql'] != null) {
            queries.add({...args, 'method': call.method});
            final result = await sql({...args, 'method': call.method});
            if (call.method == 'execute') {
              return args['inTransaction'] == true
                  ? {'transactionId': 1}
                  : null;
            }
            return result;
          }
          return null;
        },
      );
      addTearDown(() async {
        messenger.setMockMethodCallHandler(
          const MethodChannel('com.tekartik.sqflite'),
          null,
        );
        await process.stdin.close();
        await replies.cancel();
        await process.exitCode;
      });
      final local = LocalDbService();
      final db = await local.database;
      final at = DateTime.utc(2026, 10, 14, 8);
      for (final id in ['a', 'b']) {
        await db.insert('chat_sessions', {
          'id': id,
          'title': id,
          'created_at': at.toIso8601String(),
          'updated_at': at.toIso8601String(),
        });
      }
      for (var i = 0; i < 151; i++) {
        await db.insert('chat_messages', {
          'id': 'm${i.toString().padLeft(3, '0')}',
          'thread_id': 'a',
          'role': i.isEven ? 'user' : 'assistant',
          'content': 'message $i',
          'timestamp': at.add(Duration(seconds: i ~/ 2)).toIso8601String(),
          'sync_status': 'synced',
        });
      }
      await db.insert('chat_messages', {
        'id': 'other',
        'thread_id': 'b',
        'role': 'user',
        'content': 'other',
        'timestamp': at.toIso8601String(),
        'sync_status': 'synced',
      });
      queries.clear();
      final summaries = await local.loadChatSessions(summariesOnly: true);
      expect(summaries.every((s) => s.messages.isEmpty), isTrue);
      expect(summaries.firstWhere((s) => s.id == 'a').messageCount, 151);
      expect(
        queries.where(
          (q) => '${q['sql']}'.startsWith('SELECT * FROM chat_messages'),
        ),
        isEmpty,
      );
      final opened = await local.loadChatSessions(
        summariesOnly: true,
        loadThreadId: 'a',
        messageLimit: 60,
      );
      final chat = opened.firstWhere((s) => s.id == 'a');
      expect(chat.messages, hasLength(60));
      expect(opened.firstWhere((s) => s.id == 'b').messages, isEmpty);
      final older = await local.loadChatMessages(
        'a',
        before: chat.messages.first,
        limit: 60,
      );
      final oldest = await local.loadChatMessages(
        'a',
        before: older.first,
        limit: 60,
      );
      final ids = [
        ...oldest,
        ...older,
        ...chat.messages,
      ].map((m) => m.id).toList();
      expect(ids, hasLength(151));
      expect(ids.toSet(), hasLength(151));
      expect(ids.first, 'm000');
      expect(ids.last, 'm150');
      expect(await local.searchChatIds('message 10'), contains('a'));

      SyncPage page(String id, String cursor) => SyncPage.fromJson({
        'cursor': cursor,
        'has_more': false,
        'bootstrap': false,
        'events': [
          {
            'collection': 'notes',
            'id': id,
            'deleted': false,
            'data': {
              'id': id,
              'content': 'note',
              'created_at': at.toIso8601String(),
              'updated_at': at.toIso8601String(),
            },
          },
        ],
      });
      await local.applySyncPage(
        'test',
        page('n1', 'first'),
        startingBootstrap: false,
      );
      failBatch = true;
      await expectLater(
        local.applySyncPage(
          'test',
          page('n2', 'second'),
          startingBootstrap: false,
        ),
        throwsA(isA<DatabaseException>()),
      );
      expect(await local.syncCursor('test'), 'first');
      expect(
        await db.query('notes', where: 'id=?', whereArgs: ['n2']),
        isEmpty,
      );
      await local.applySyncPage(
        'test',
        page('n2', 'second'),
        startingBootstrap: false,
      );
      expect(await local.syncCursor('test'), 'second');

      final completeChat = (await local.loadChatSessions(
        onlyThreadId: 'a',
      )).single;
      await local.cacheArchivedChat(
        completeChat.toJson(),
        'verified-digest',
        retirePending: true,
      );
      final archived = (await local.loadChatSessions(
        summariesOnly: true,
        onlyThreadId: 'a',
      )).single;
      expect(archived.isArchived, isTrue);
      expect(archived.hasArchive, isTrue);
      expect(archived.archivedAt, isNotNull);
      completeChat.messages.add(
        ChatMessage(
          id: 'continued',
          text: 'new message',
          isUser: true,
          timestamp: at.add(const Duration(days: 1)),
        ),
      );
      await local.saveChatSession(completeChat);
      final continued = (await local.loadChatSessions(
        summariesOnly: true,
        onlyThreadId: 'a',
      )).single;
      expect(continued.isArchived, isFalse);
      expect(continued.hasArchive, isTrue);
      expect(continued.messageCount, 152);

      await db.update(
        'notes',
        {'content': 'uploaded version', 'sync_status': 'pending'},
        where: 'id=?',
        whereArgs: ['n1'],
      );
      final uploaded = await local.getPendingSyncRecords();
      await db.update(
        'notes',
        {'content': 'edited while uploading'},
        where: 'id=?',
        whereArgs: ['n1'],
      );
      await local.markRecordsSynced(noteIds: ['n1'], pushedRecords: uploaded);
      expect(
        (await db.query(
          'notes',
          where: 'id=?',
          whereArgs: ['n1'],
        )).single['sync_status'],
        'pending',
      );
      await local.markRecordsSynced(
        noteIds: ['n1'],
        pushedRecords: await local.getPendingSyncRecords(),
      );
      expect(
        (await db.query(
          'notes',
          where: 'id=?',
          whereArgs: ['n1'],
        )).single['sync_status'],
        'synced',
      );

      // A fresh/empty API instance cannot prune the durable phone history.
      await local.applySyncPage(
        'test',
        SyncPage.fromJson({
          'cursor': 'fresh-cache',
          'events': <Map<String, dynamic>>[],
          'has_more': false,
          'bootstrap': true,
          'bootstrap_complete': true,
        }),
        startingBootstrap: true,
      );
      expect(
        await db.query('notes', where: 'id=?', whereArgs: ['n1']),
        isNotEmpty,
      );
      expect(
        await db.query('chat_messages', where: 'thread_id=?', whereArgs: ['a']),
        isNotEmpty,
      );
      await db.update(
        'chat_messages',
        {'sync_status': 'archived'},
        where: 'id=?',
        whereArgs: ['other'],
      );
      await local.prepareBackendRebuild('test');
      expect(await local.syncCursor('test'), isNull);
      expect((await local.getPendingSyncRecords())['notes'], isNotEmpty);
      expect(
        (await db.query(
          'chat_messages',
          where: 'id=?',
          whereArgs: ['other'],
        )).single['sync_status'],
        'archived',
      );
      final preferences = SessionPreferences();
      await preferences.save('recording:local', 'Evening walk', true);
      final savedPreferences = await SessionPreferences().load();
      expect(savedPreferences['recording:local']?['name'], 'Evening walk');
      expect(savedPreferences['recording:local']?['archived'], 1);
    },
  );
}
