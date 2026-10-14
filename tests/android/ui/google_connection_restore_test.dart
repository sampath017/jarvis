import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/google_connection_restore.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('jarvis/test_google_restore');
  late GoogleConnectionRestore restorer;
  late List<String> calls;
  late bool connected;
  late List<bool> progress;

  Future<void> restore({Future<void> Function(Map<String, dynamic>)? accept}) =>
      restorer.run(
        channel: channel,
        preferredEmail: 'owner@example.com',
        refresh: () async {},
        connected: () => connected,
        accept:
            accept ??
            (auth) async {
              expect(auth['email'], 'owner@example.com');
              calls.add('verify API access');
              connected = true;
            },
        setRestoring: progress.add,
      );

  setUp(() {
    restorer = GoogleConnectionRestore();
    calls = [];
    connected = false;
    progress = [];
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      calls.add(call.method);
      if (call.method != 'restoreConnection') {
        fail('Interactive consent is forbidden during restoration');
      }
      expect(call.arguments['preferredEmail'], 'owner@example.com');
      return {'token': 'existing-grant', 'email': 'owner@example.com'};
    });
  });

  tearDown(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null);
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      null,
    );
  });

  test(
    'a saved healthy connection needs no authorization or API calls',
    () async {
      connected = true;
      await restore();
      expect(calls, isEmpty);
      expect(progress, [true, false]);
    },
  );

  test(
    'fresh local state reuses a grant and verifies API access once',
    () async {
      await Future.wait([restore(), restore()]);
      await restore();
      expect(connected, isTrue);
      expect(calls, ['restoreConnection', 'verify API access']);
      expect(progress, [true, false]);
    },
  );

  test(
    'an explicit native disconnect prevents reconnecting or reading APIs',
    () async {
      binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        calls.add(call.method);
        return null; // Native userDisconnected preference vetoes restoration.
      });
      await restore();
      expect(connected, isFalse);
      expect(calls, ['restoreConnection']);
    },
  );

  test(
    'missing consent never falls back to opening Google authorization',
    () async {
      binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        calls.add(call.method);
        throw PlatformException(code: 'CONSENT_REQUIRED');
      });
      await restore();
      expect(connected, isFalse);
      expect(calls, ['restoreConnection']);
      expect(progress.last, isFalse);
    },
  );

  test('a failed API verification does not establish a connection', () async {
    await restore(accept: (_) async => throw StateError('API unavailable'));
    expect(connected, isFalse);
    expect(calls, ['restoreConnection']);
    expect(progress.last, isFalse);
  });

  test('concurrent launch consumers wait for the same restoration', () async {
    final verified = Completer<void>();
    final first = restore(
      accept: (_) async {
        await verified.future;
        connected = true;
      },
    );
    final second = restore();
    await Future<void>.delayed(Duration.zero);
    expect(connected, isFalse);
    verified.complete();
    await Future.wait([first, second]);
    expect(connected, isTrue);
    expect(calls, ['restoreConnection']);
  });

  for (final apiStatus in [200, 401, 503]) {
    test(
      'Drive saves restored account only after verified access ($apiStatus)',
      () async {
        final operations = <String>[];
        var saved = false;
        binding.defaultBinaryMessenger.setMockMethodCallHandler(
          GoogleDriveService.channel,
          (call) async {
            operations.add(call.method);
            switch (call.method) {
              case 'status':
                return {
                  'connected': saved,
                  'email': saved ? 'owner@example.com' : '',
                };
              case 'restoreConnection':
                return {
                  'token': 'existing-grant',
                  'email': 'owner@example.com',
                };
              case 'saveConnection':
                saved = true;
                expect(call.arguments['email'], 'owner@example.com');
                return true;
              case 'token':
                return 'existing-grant';
              case 'readRecord':
                return null;
              case 'writeRecord':
                return true;
              case 'accessRequired':
                return true;
              default:
                fail('Unexpected platform operation ${call.method}');
            }
          },
        );
        final drive = GoogleDriveService(
          clientFactory: () => MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.host, 'www.googleapis.com');
            expect(request.headers['Authorization'], 'Bearer existing-grant');
            operations.add('verify HTTP $apiStatus');
            return http.Response(jsonEncode({'files': []}), apiStatus);
          }),
        );
        await drive.restoreConnection();
        expect(drive.connected, apiStatus == 200);
        expect(drive.restoring, isFalse);
        expect(operations.contains('connect'), isFalse);
        expect(operations.contains('saveConnection'), apiStatus == 200);
        if (apiStatus == 200) {
          expect(
            operations.indexOf('saveConnection'),
            greaterThan(operations.indexOf('verify HTTP 200')),
          );
        }
        drive.dispose();
      },
    );
  }
}
