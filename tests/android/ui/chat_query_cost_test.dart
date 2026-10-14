import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/local_db_service.dart';
import 'package:jarvis_collector/services/chat_storage_service.dart';
import 'package:jarvis_collector/services/session_preferences.dart';
import 'package:jarvis_collector/models/chat_session.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  databaseFactory = databaseFactorySqflitePlugin;

  test(
    'summary list skips bodies; real SQLite pagination and local archives preserve history',
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
      final fullHistory = await ChatStorageService.loadCommandHistory(
        chat,
        currentMessageId: 'm150',
      );
      expect(fullHistory, hasLength(150));
      expect(fullHistory.first['content'], 'message 0');
      expect(fullHistory.take(4).map((message) => message['role']), [
        'user',
        'assistant',
        'user',
        'assistant',
      ]);
      expect(fullHistory.last['content'], 'message 149');
      expect(
        fullHistory.any((message) => message['content'] == 'other'),
        isFalse,
      );
      expect(
        chat.messages,
        hasLength(60),
      ); // UI pagination does not limit model history.
      final unsaved = ChatMessage(
        id: 'unsaved-current',
        text: 'message 10',
        isUser: true,
        timestamp: at.add(const Duration(days: 1)),
      );
      final withUnsaved = chat.copyWith(messages: [...chat.messages, unsaved]);
      final merged = await ChatStorageService.loadCommandHistory(
        withUnsaved,
        currentMessageId: unsaved.id,
      );
      expect(merged, hasLength(151));
      expect(
        merged.where((message) => message['content'] == 'message 10'),
        hasLength(1),
      );
      await expectLater(
        ChatStorageService.loadCommandHistory(
          ChatSession(
            id: 'a',
            title: 'a',
            createdAt: at,
            updatedAt: at,
            messages: [],
            storedMessageCount: 999,
          ),
        ),
        throwsA(isA<ChatHistoryReadException>()),
      );
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

      final preferences = SessionPreferences();
      await preferences.save('recording:local', 'Evening walk', true);
      final savedPreferences = await SessionPreferences().load();
      expect(savedPreferences['recording:local']?['name'], 'Evening walk');
      expect(savedPreferences['recording:local']?['archived'], 1);

      await local.deleteChatSession('b');
      expect(
        await db.query('chat_sessions', where: 'id=?', whereArgs: ['b']),
        isEmpty,
      );
      expect(
        await db.query('chat_messages', where: 'thread_id=?', whereArgs: ['b']),
        isEmpty,
      );
      expect(
        await db.query('chat_messages', where: 'thread_id=?', whereArgs: ['a']),
        hasLength(152),
      );
      expect(
        (await local.chatArchiveReference('a'))?['cached_digest'],
        'verified-digest',
      );
      expect(
        (await SessionPreferences().load())['recording:local']?['name'],
        'Evening walk',
      );
    },
  );
}
