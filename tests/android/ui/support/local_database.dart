import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';

/// Exercise production Dart SQL against real SQLite, without an Android emulator.
Future<Future<void> Function()> startLocalDatabase() async {
  databaseFactory = databaseFactorySqflitePlugin;
  final process = await Process.start(
    Platform.environment['JARVIS_TEST_PYTHON'] ?? 'python',
    ['-u', '../tests/android/ui/support/sqlite_bridge.py'],
  );
  final replies = StreamIterator(
    process.stdout.transform(utf8.decoder).transform(const LineSplitter()),
  );
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  messenger.setMockMethodCallHandler(
    const MethodChannel('com.tekartik.sqflite'),
    (call) async {
      if (call.method == 'getDatabasesPath') return Directory.systemTemp.path;
      if (call.method == 'openDatabase') return {'id': 1};
      if (call.method == 'closeDatabase') return null;
      final args = Map<String, dynamic>.from(call.arguments as Map);
      // Android rejects execute() for PRAGMAs that return rows. Python SQLite
      // accepts them, so enforce the Android contract in this bridge as well.
      if (call.method == 'execute' &&
          RegExp(r'^PRAGMA\s+(busy_timeout|journal_mode)', caseSensitive: false)
              .hasMatch(args['sql']?.toString() ?? '')) {
        throw PlatformException(
          code: 'sqlite_error',
          message: 'Row-returning PRAGMA requires rawQuery on Android',
        );
      }
      if (args['sql'] == null && call.method != 'batch') return null;
      process.stdin.writeln(jsonEncode({...args, 'method': call.method}));
      await process.stdin.flush();
      if (!await replies.moveNext()) throw StateError('SQLite bridge stopped');
      final response = jsonDecode(replies.current) as Map;
      if (response['error'] != null)
        throw PlatformException(
          code: 'sqlite_error',
          message: response['error'],
        );
      if (call.method == 'execute')
        return args['inTransaction'] == true ? {'transactionId': 1} : null;
      return call.method == 'batch' && args['noResult'] == true
          ? null
          : response['result'];
    },
  );
  return () async {
    messenger.setMockMethodCallHandler(
      const MethodChannel('com.tekartik.sqflite'),
      null,
    );
    await process.stdin.close();
    await replies.cancel();
    await process.exitCode;
  };
}
