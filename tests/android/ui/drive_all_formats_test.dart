import 'support/local_database.dart';
import 'package:jarvis_collector/services/mobile_index_catalog.dart';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  late Future<void> Function() closeDatabase;
  setUpAll(() async {closeDatabase=await startLocalDatabase();});
  tearDownAll(() async {await closeDatabase();});
  setUp(() {
    binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      (call) async => switch (call.method) {
        'status' => {'connected': true, 'email': 'test@example.com'},
        'token' => 'local-token',
        'sessionKey' => List.filled(64, 'a').join(),
        _ => null,
      },
    );
  });
  tearDown(
    () => binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      null,
    ),
  );

  test(
    'all formats submit, shortcuts resolve, Forms paginate and failures are recorded',
    () async {
      final types = {
        'word':
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'zip': 'application/zip',
        'exe': 'application/octet-stream',
        'drawing': 'application/vnd.google-apps.drawing',
        'form': 'application/vnd.google-apps.form',
        'shortcut': 'application/vnd.google-apps.shortcut',
        'denied': 'application/octet-stream',
        'folder': 'application/vnd.google-apps.folder',
      };
      Map<String, dynamic> file(String id) => {
        'id': id,
        'name': id == 'word' ? 'note.docx' : '$id.file',
        'mimeType': types[id],
        'size': '7',
        'version': '1',
        if (id == 'shortcut') 'shortcutDetails': {'targetId': 'word'},
      };
      final submitted = <String>{};
      final catalogued = <String>{};
      final stored = <String, String>{};
      final drive = GoogleDriveService(
        clientFactory: () => MockClient((request) async {
          final path = request.url.path;
          if (path == '/drive-index/status') {
            return http.Response('{"configured":true,"background":true}', 200);
          }
          if (path == '/drive/v3/files') {
            return http.Response(
              jsonEncode({'files': types.keys.map(file).toList()}),
              200,
            );
          }
          if (path == '/drive-index/uploads') {
            final id = jsonDecode(request.body)['id'].toString();
            final first = submitted.add(id);
            return http.Response(
              jsonEncode({
                'job_id': id,
                'upload_required': first,
                'upload_url': '/drive-index/uploads/$id/content',
              }),
              200,
            );
          }
          if (path == '/drive-index/catalog') {
            catalogued.add(jsonDecode(request.body)['memory']['id']);
            return http.Response('{}', 200);
          }
          if (path == '/drive/v3/files/word' &&
              request.url.queryParameters['alt'] != 'media') {
            return http.Response(jsonEncode(file('word')), 200);
          }
          if (path == '/v1/forms/form') {
            return http.Response(
              '{"info":{"title":"Launch survey"},"items":[]}',
              200,
            );
          }
          if (path == '/v1/forms/form/responses') {
            return http.Response(
              request.url.queryParameters['pageToken'] == null
                  ? '{"responses":[{"responseId":"response-one"}],"nextPageToken":"next"}'
                  : '{"responses":[{"responseId":"response-two"}]}',
              200,
            );
          }
          if (path == '/drive/v3/files/drawing/export') {
            expect(request.url.queryParameters['mimeType'], 'image/png');
            return http.Response('payload', 200);
          }
          if (path.startsWith('/drive/v3/files/')) {
            return http.Response(
              'payload',
              path.endsWith('/denied') ? 403 : 200,
            );
          }
          if(path.startsWith('/drive-index/files/')){
            final id=path.split('/').last;
            submitted.add(id);stored[id]=request.body;
            final metadata=jsonDecode(utf8.decode(base64Decode(request.headers['X-File-Metadata']??request.headers['x-file-metadata']!)));
            expect(metadata['id'],id);
            return http.Response('{"status":"indexed","chunks":1,"coverage":"content"}',200);
          }
          throw StateError('Unexpected request $path');
        }),
      );
      await drive.indexAllDrive();
      expect(
        submitted,
        containsAll(['word', 'zip', 'exe', 'drawing', 'form']),
      );
      final results=(await MobileIndexCatalog.instance.request('/results?account=test%40example.com'))['items'] as List;
      expect(results.where((r)=>r['status']=='attention').map((r)=>r['id']),containsAll(['shortcut','denied']));
      expect(stored['form'], contains('response-one'));
      expect(stored['form'], contains('response-two'));
      expect(drive.indexProgress, isNot(contains('unsupported')));
      drive.dispose();
    },
  );

  test(
    'indexed Office reading rechecks Drive version before returning passages',
    () async {
      var evidenceCalls = 0;
      final memory = {
        'id': 'word',
        'name': 'note.docx',
        'mimeType':
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'size': 30 * 1024 * 1024,
        'account': 'test@example.com',
        'source_version': 'old',
      };
      binding.defaultBinaryMessenger.setMockMethodCallHandler(
        GoogleDriveService.channel,
        (call) async => switch (call.method) {
          'status' => {'connected': true, 'email': 'test@example.com'},
          'token' => 'local-token',
          'sessionKey' => List.filled(64, 'a').join(),
          'readRecord' =>
            call.arguments == 'memories' ? jsonEncode([memory]) : null,
          _ => null,
        },
      );
      final drive = GoogleDriveService(
        clientFactory: () => MockClient((request) async {
          if (request.url.path == '/file-memories/config') {
            return http.Response('{"max_analysis_bytes":20971520}', 200);
          }
          if (request.url.path == '/drive/v3/files/word') {
            return http.Response(
              '{"name":"note.docx","version":"7","trashed":false}',
              200,
            );
          }
          if (request.url.path == '/drive-index/evidence') {
            evidenceCalls++;
            expect(jsonDecode(request.body)['source_version'], '7');
            return http.Response(
              '{"evidence":[{"text":"ORBIT-417","locator":"paragraph 1","coverage":"content","content_kind":"content"}]}',
              200,
            );
          }
          throw StateError('Unexpected source upload ${request.url}');
        }),
      );
      final result = await drive.analyze({
        'file_id': 'word',
        'question': 'calibration code',
        'action_id': 'read',
      }, isActive: () async => true);
      expect(evidenceCalls, 1);
      expect(result['answer'], contains('ORBIT-417'));
      expect(result['source_kind'], 'retrieved_passages');
      drive.dispose();
    },
  );
}
