import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  setUp(
    () => binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      (call) async => switch (call.method) {
        'status' => {'connected': true, 'email': 'test@example.com'},
        'token' => 'local-token',
        'sessionKey' => List.filled(64, 'a').join(),
        _ => null,
      },
    ),
  );
  tearDown(
    () => binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      null,
    ),
  );

  for (final allowed in [true, false]) {
    test(
      'content match under unrelated filename checks access: $allowed',
      () async {
        var verified = false;
        var contentRequests = 0;
        final drive = GoogleDriveService(
          clientFactory: () => MockClient((request) async {
            switch (request.url.path) {
              case '/drive/v3/files':
                expect(request.url.queryParameters['q'], contains('UIDAI'));
                return http.Response('{"files":[]}', 200);
              case '/drive-index/status':
                return http.Response('{"configured":true}', 200);
              case '/drive-index/search':
                expect(
                  jsonDecode(request.body)['query'],
                  'Find the identity document by its contents',
                );
                return http.Response(
                  '{"matches":[{"file_id":"generic","source_version":"7"}]}',
                  200,
                );
              case '/drive/v3/files/generic':
                verified = allowed;
                return http.Response(
                  '{"id":"generic","name":"0042.pdf","mimeType":"application/pdf","version":"7","size":"5"}',
                  allowed ? 200 : 403,
                );
              case '/drive-index/search-contents':
                contentRequests++;
                expect(verified, isTrue);
                expect(jsonDecode(request.body)['files'], [
                  {'file_id': 'generic', 'source_version': '7'},
                ]);
                return http.Response(
                  '{"evidence":[{"file_id":"generic","name":"0042.pdf","text":"Synthetic identity document body","locator":"page 1","content_kind":"content"}]}',
                  200,
                );
              default:
                throw StateError('Unexpected ${request.url.path}');
            }
          }),
        );
        final result = await drive.searchFiles(
          'Aadhar',
          contentQuery: 'Find the identity document by its contents',
        );
        expect(result['contents_read'], allowed);
        expect(contentRequests, allowed ? 1 : 0);
        if (allowed) {
          expect(
            (result['passages'] as List).single['text'],
            contains('Synthetic identity'),
          );
        }
        drive.dispose();
      },
    );
  }

  test('explicit filenames-only request never reads indexed contents', () async {
    final drive = GoogleDriveService(
      clientFactory: () => MockClient((request) async {
        expect(request.url.path, '/drive/v3/files');
        return http.Response(
          '{"files":[{"id":"f","name":"resume.pdf","mimeType":"application/pdf","size":"5"}]}',
          200,
        );
      }),
    );
    final result = await drive.searchFiles('resume', readContents: false);
    expect(result['contents_read'], isFalse);
    expect(result['passages'], isEmpty);
    drive.dispose();
  });
}
