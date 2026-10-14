import 'support/local_database.dart';
import 'package:flutter/services.dart';
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
  late Map<String, Map<String, dynamic>> folders;
  late Future<void> Function() closeDatabase;
  setUpAll(() async {closeDatabase=await startLocalDatabase();});
  tearDownAll(() async {await closeDatabase();});
  setUp(() async {
    binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    temp = await Directory.systemTemp.createTemp('jarvis_drive_test_');
    file = await File('${temp.path}/picked').writeAsBytes([1, 2, 3, 4]);
    binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('plugins.flutter.io/path_provider'),(_) async=>temp.path);
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
    Map<String, dynamic> folder(String id, String name, List<String> parents) =>
        {
          'id': id,
          'name': name,
          'mimeType': 'application/vnd.google-apps.folder',
          'parents': parents,
          'ownedByMe': true,
          'shared': false,
          'trashed': false,
        };
    folders = {
      'jarvis-root': folder('jarvis-root', 'Jarvis', ['root-id']),
      'cache-id': folder('cache-id', 'Upload Cache', ['jarvis-root']),
      'saved-folder': folder('saved-folder', 'Saved Files', ['jarvis-root']),
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
            expect(request.url.queryParameters['addParents'], 'saved-folder');
            expect(request.url.queryParameters['removeParents'], 'cache-id');
            metadata['parents'] = ['saved-folder'];
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
          final query = request.url.queryParameters['q'] ?? '';
          final key = query.contains("name='Jarvis'")
              ? 'jarvis-root'
              : query.contains("name='Saved Files'")
              ? 'saved-folder'
              : 'cache-id';
          return http.Response(
            jsonEncode({
              'files': [
                {...folders[key]!, if (key == 'cache-id') 'shared': shared},
              ],
            }),
            200,
          );
        }
        final folderId = request.url.path.split('/').last;
        if (folders.containsKey(folderId)) {
          if (request.method == 'PATCH') {
            folders[folderId]!.addAll(
              Map<String, dynamic>.from(jsonDecode(request.body)),
            );
            if (request.url.queryParameters['addParents'] != null) {
              folders[folderId]!['parents'] = [
                request.url.queryParameters['addParents'],
              ];
            }
          }
          return http.Response(
            jsonEncode({
              ...folders[folderId]!,
              if (folderId == 'cache-id') 'shared': shared,
            }),
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
    await temp.delete(recursive:true);
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
  test('ordinary attachments stay local and never create a Google request',() async {
    final memory=await drive.save(selected(),'Purchase receipt');
    expect(memory['storage'],'local');expect(requests,isEmpty);
    expect(await File(memory['path']).readAsBytes(),[1,2,3,4]);
    await drive.refresh();expect(drive.contextFor('receipt').single['id'],'local_picked-id');
    expect(drive.contextFor('receipt').single.containsKey('path'),isFalse);
  });
  test(
    'unrelated cached files do not accompany activity or calendar questions',
    () {
      drive.memories = [
        {
          'id': 'prompt',
          'name': 'What I am doing today',
          'caption': '',
          'mimeType': 'text/plain',
          'url': 'https://aistudio.google.com/app/prompts',
        },
        {
          'id': 'notebook',
          'name': 'notebook.ipynb',
          'caption': 'Research notes',
          'mimeType': 'application/json',
          'url': 'https://colab.research.google.com/drive/notebook',
        },
      ];
      expect(
        drive.contextFor('Where and what I am doing yesterday 12:36 pm'),
        isEmpty,
      );
      expect(
        drive.contextFor(
          'Create a meet at 4 to 5 today, name it as lokesh meet',
        ),
        isEmpty,
      );
    },
  );
  test(
    'matching files and explicit attachments are selected without irrelevant filler',
    () {
      drive.memories = List.generate(
        15,
        (i) => {
          'id': 'file-$i',
          'name': i == 0 ? 'receipt.pdf' : 'notebook-$i',
          'caption': '',
          'mimeType': 'text/plain',
          'url': 'https://drive.google.com/file/d/file-$i/view',
        },
      );
      expect(drive.contextFor('receipt').map((m) => m['id']), ['file-0']);
      expect(
        drive
            .contextFor('What is this?', prioritizedIds: ['file-14'])
            .map((m) => m['id']),
        ['file-14'],
      );
      expect(
        drive
            .contextFor('receipt', prioritizedIds: ['file-14'])
            .map((m) => m['id']),
        ['file-14', 'file-0'],
      );
      expect(drive.contextFor('notebook').length, 12);
    },
  );
  test(
    'explicit saves upload into Jarvis Saved Files without creating cache',
    () async {
      final memory = await drive.save(
        selected(),
        'Purchase receipt',
        saveToDrive: true,
      );
      expect(metadata['parents'], ['saved-folder']);
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
  test('later explicit Drive save uploads a local attachment once',() async {
    final original=await drive.save(selected(),'Purchase receipt');
    final saved=await drive.saveToMyDrive(original['id'],isActive:() async=>true);
    expect(saved['storage'],'drive');expect(uploads(),1);
    await drive.saveToMyDrive(original['id'],isActive:() async=>true);
    expect(uploads(),1);
  });
  test('stopped upload sends no Google writes', () async {
    await expectLater(
      drive.save(selected(), 'Purchase receipt', shouldContinue: () => false),
      throwsA(isA<DriveFailure>()),
    );
    expect(requests, isEmpty);
  });
  test('cancelled analysis shares no raw bytes', () async {
    await drive.save(selected(), 'Purchase receipt',saveToDrive:true);
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
  test('removed cloud metadata endpoint cannot block an explicit Drive save',() async {
    cloudUnavailable=true;
    await drive.save(selected(),'Purchase receipt',saveToDrive:true);
    expect(uploads(),1);
    expect(requests.where((r)=>r.url.path.startsWith('/file-memories')),isEmpty);
  });
  test('requested analysis needs no confirmation and deduplicates', () async {
    await drive.save(selected(), 'Purchase receipt',saveToDrive:true);
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
