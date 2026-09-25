import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  late Directory temp;
  late File file;
  late Map<String, String> records;
  late List<http.Request> requests;
  late GoogleDriveService drive;
  late bool shared, cloudUnavailable;
  late Map<String, dynamic> metadata;
  setUp(() async {
    binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    temp = await Directory.systemTemp.createTemp('jarvis_drive_test_');
    file = await File('${temp.path}/picked').writeAsBytes([1, 2, 3, 4]);
    records = {};
    requests = [];
    shared = false;
    cloudUnavailable = false;
    metadata = {
      'id': 'saved-id',
      'name': 'receipt.pdf',
      'mimeType': 'application/pdf',
      'size': '4',
      'description': 'Purchase receipt',
      'parents': ['cache-id'],
      'appProperties': {'jarvisMemory': 'true', 'jarvisStorage': 'cache'},
    };
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      (call) async {
        switch (call.method) {
          case 'status':
            return {'connected': true, 'email': 'owner@example.com'};
          case 'token':
            return 'local-token';
          case 'sessionKey':
            return List.filled(64, 'a').join();
          case 'readRecord':
            return records[call.arguments];
          case 'writeRecord':
            records[call.arguments['key']] = call.arguments['value'];
            return true;
          default:
            return null;
        }
      },
    );
    drive = GoogleDriveService(
      clientFactory: () => MockClient((request) async {
        requests.add(request);
        if (request.url.path == '/file-memories/config') {
          return http.Response(
            '{"media_model":"z-ai/glm-5.3-flash","pdf_model":"google/gemini-3.8-flash","max_analysis_bytes":20971520}',
            200,
          );
        }
        if (request.url.path == '/file-memories/saved-id') {
          expect(request.method, 'PUT');
          expect(request.headers.containsKey('Authorization'), isFalse);
          expect(jsonDecode(request.body)['caption'], 'Purchase receipt');
          expect(jsonDecode(request.body).keys, isNot(contains('raw')));
          return http.Response('{"saved":true}', cloudUnavailable ? 503 : 200);
        }
        if (request.url.path == '/drive/v3/files/root') {
          return http.Response('{"id":"root-id"}', 200);
        }
        if (request.url.path == '/drive/v3/files/saved-id') {
          expect(request.headers['Authorization'], 'Bearer local-token');
          if (request.url.queryParameters['alt'] == 'media') {
            return http.Response.bytes([1, 2, 3, 4], 200);
          }
          if (request.method == 'PATCH') {
            expect(request.url.queryParameters['addParents'], 'root-id');
            expect(request.url.queryParameters['removeParents'], 'cache-id');
            metadata['parents'] = ['root-id'];
            metadata['appProperties'] = jsonDecode(
              request.body,
            )['appProperties'];
          }
          return http.Response(jsonEncode(metadata), 200);
        }
        if (request.url.path == '/file-memories/saved-id/analyze') {
          expect(request.headers.containsKey('Authorization'), isFalse);
          expect(request.bodyBytes, [1, 2, 3, 4]);
          return http.Response(
            '{"status":"ok","answer":"42","file_id":"saved-id"}',
            200,
          );
        }
        if (request.url.path.endsWith('/generateIds')) {
          return http.Response('{"ids":["saved-id"]}', 200);
        }
        if (request.url.path == '/drive/v3/files') {
          expect(
            request.url.queryParameters['q'],
            contains('Jarvis Upload Cache'),
          );
          return http.Response(
            jsonEncode({
              'files': [
                {'id': 'cache-id', 'shared': shared},
              ],
            }),
            200,
          );
        }
        if (request.url.path == '/drive/v3/files/cache-id') {
          return http.Response(
            jsonEncode({'id': 'cache-id', 'shared': shared}),
            200,
          );
        }
        if (request.method == 'POST' &&
            request.url.path.startsWith('/upload/')) {
          final body = jsonDecode(request.body);
          metadata['parents'] = body['parents'];
          metadata['appProperties'] = body['appProperties'];
          return http.Response(
            '',
            200,
            headers: {
              'location':
                  'https://www.googleapis.com/upload/drive/v3/files?upload_id=test',
            },
          );
        }
        if (request.method == 'PUT') {
          return http.Response(jsonEncode(metadata), 200);
        }
        fail('Unexpected request ${request.method} ${request.url}');
      }),
    );
  });
  tearDown(() async {
    drive.dispose();
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      null,
    );
    await file.delete();
    await temp.delete();
  });
  Map<String, dynamic> selected() => {
    'id': 'picked-id',
    'path': file.path,
    'name': 'receipt.pdf',
    'mimeType': 'application/pdf',
    'size': 4,
  };
  int uploads() => requests
      .where((r) => r.method == 'PUT' && r.url.host == 'www.googleapis.com')
      .length;
  Map<String, dynamic> analysis() => {
    'file_id': 'saved-id',
    'question': 'What is the total?',
    'action_id': 'analysis-one',
  };
  test(
    'ordinary attachments use cache without confirmation and upload once',
    () async {
      final memory = await drive.save(selected(), 'Purchase receipt');
      expect(memory['storage'], 'cache');
      expect(metadata['parents'], ['cache-id']);
      await drive.save(selected(), 'Purchase receipt');
      expect(uploads(), 1);
      await drive.refresh();
      expect(drive.contextFor('receipt').single['id'], 'saved-id');
    },
  );
  test(
    'explicit saves upload directly to My Drive without creating cache',
    () async {
      final memory = await drive.save(
        selected(),
        'Purchase receipt',
        saveToDrive: true,
      );
      expect(metadata['parents'], ['root']);
      expect(memory['storage'], 'drive');
      expect(
        requests.any(
          (r) =>
              r.url.queryParameters['q']?.contains('Jarvis Upload Cache') ==
              true,
        ),
        isFalse,
      );
    },
  );
  test(
    'later save moves same cached file without duplicate or repeated move',
    () async {
      final original = await drive.save(selected(), 'Purchase receipt');
      final saved = await drive.saveToMyDrive(
        'saved-id',
        isActive: () async => true,
      );
      expect(saved['id'], original['id']);
      expect(saved['url'], original['url']);
      expect(saved['storage'], 'drive');
      await drive.saveToMyDrive('saved-id', isActive: () async => true);
      expect(requests.where((r) => r.method == 'PATCH').length, 1);
      expect(uploads(), 1);
    },
  );
  test('stopped upload sends no Google writes', () async {
    await expectLater(
      drive.save(selected(), 'Purchase receipt', shouldContinue: () => false),
      throwsA(isA<DriveFailure>()),
    );
    expect(requests, isEmpty);
  });
  test('shared cache refuses upload', () async {
    shared = true;
    records['cacheFolder:owner@example.com'] = '"cache-id"';
    await expectLater(
      drive.save(selected(), 'Purchase receipt'),
      throwsA(isA<DriveFailure>()),
    );
    expect(requests.where((r) => r.method != 'GET'), isEmpty);
  });
  test('cancelled analysis shares no raw bytes', () async {
    await drive.save(selected(), 'Purchase receipt');
    requests.clear();
    expect(
      (await drive.analyze(analysis(), isActive: () async => false))['status'],
      'cancelled',
    );
    expect(
      requests.every(
        (r) => r.method == 'GET' && r.url.path.endsWith('/config'),
      ),
      isTrue,
    );
  });
  test(
    'Firebase failure retries metadata without duplicating the original',
    () async {
      cloudUnavailable = true;
      await expectLater(
        drive.save(selected(), 'Purchase receipt'),
        throwsA(isA<DriveFailure>()),
      );
      cloudUnavailable = false;
      await drive.save(selected(), 'Purchase receipt');
      expect(uploads(), 1);
    },
  );
  test('requested analysis needs no confirmation and deduplicates', () async {
    await drive.save(selected(), 'Purchase receipt');
    expect(
      (await drive.analyze(analysis(), isActive: () async => true))['answer'],
      '42',
    );
    await drive.analyze(analysis(), isActive: () async => true);
    expect(requests.where((r) => r.url.path.endsWith('/analyze')).length, 1);
  });
  test('only explicit save wording uses My Drive', () {
    for (final query in [
      'Save this to Google Drive',
      'upload to gdrive and analyze',
      'put this in my drive',
    ]) {
      expect(GoogleDriveService.requestsDriveSave(query), isTrue);
    }
    for (final query in [
      'Analyze this PDF',
      'What does this say?',
      'remember this file',
      "Don't save this to drive, just analyze",
    ]) {
      expect(GoogleDriveService.requestsDriveSave(query), isFalse);
    }
  });
}
