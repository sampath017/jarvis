import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/chat_session.dart';
import 'package:jarvis_collector/services/local_db_service.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  databaseFactory = databaseFactorySqflitePlugin;

  test(
    'saving a new reply does not requeue unchanged synced or pending history',
    () async {
      final at = DateTime.utc(2026, 10, 14, 8);
      final rows = <Map<String, Object?>>[
        for (final id in ['synced', 'pending'])
          {
            'id': id,
            'thread_id': 'chat',
            'role': 'user',
            'content': id,
            'timestamp': at.toIso8601String(),
            'run_id': null,
            'executed_records': '[]',
            'duration_ms': null,
            'sync_status': id,
          },
      ];
      final operations = <Map>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(
        const MethodChannel('com.tekartik.sqflite'),
        (call) async {
          if (call.method == 'getDatabasesPath') {
            return Directory.systemTemp.path;
          }
          if (call.method == 'openDatabase') return {'id': 1};
          if (call.method == 'query') {
            final sql = (call.arguments as Map)['sql'] as String;
            if (sql.contains('user_version')) {
              return [
                {'user_version': 8},
              ];
            }
            if (sql.contains('chat_messages')) return rows;
            return <Map<String, Object?>>[];
          }
          if (call.method == 'batch') {
            operations.addAll(
              List<Map>.from((call.arguments as Map)['operations']),
            );
          }
          return null;
        },
      );
      addTearDown(
        () => messenger.setMockMethodCallHandler(
          const MethodChannel('com.tekartik.sqflite'),
          null,
        ),
      );
      final db = LocalDbService();
      final session = ChatSession(
        id: 'chat',
        title: 'Chat',
        createdAt: at,
        updatedAt: at,
        messages: [
          for (final id in ['synced', 'pending'])
            ChatMessage(id: id, text: id, isUser: true, timestamp: at),
          ChatMessage(
            id: 'new',
            text: 'New reply',
            isUser: false,
            timestamp: at,
          ),
        ],
      );
      await db.saveChatSession(session);
      final messageWrites = operations
          .where(
            (op) =>
                '${op['sql']}'.contains('INSERT') &&
                '${op['sql']}'.contains('chat_messages'),
          )
          .toList();
      expect(messageWrites, hasLength(1));
      expect(messageWrites.single['arguments'], contains('new'));
      expect(messageWrites.single['arguments'], contains('pending'));

      operations.clear();
      session.messages[0] = ChatMessage(
        id: 'synced',
        text: 'Corrected',
        isUser: true,
        timestamp: at,
      );
      await db.saveChatSession(session);
      final edited = operations
          .where(
            (op) =>
                '${op['sql']}'.contains('INSERT') &&
                '${op['sql']}'.contains('chat_messages'),
          )
          .toList();
      expect(edited, hasLength(2));
      expect(
        edited.any((op) => (op['arguments'] as List).contains('Corrected')),
        isTrue,
      );
    },
  );
}
