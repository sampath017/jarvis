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
  test(
    'index scan refreshes an expired download token and submits source',
    () async {
      binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      var refreshed = false;
      var downloads = 0;
      var completed = false;
      binding.defaultBinaryMessenger.setMockMethodCallHandler(
        GoogleDriveService.channel,
        (call) async {
          switch (call.method) {
            case 'status':
              return {'connected': true, 'email': 'test@example.com'};
            case 'token':
              return refreshed ? 'new-token' : 'old-token';
            case 'clearToken':
              refreshed = true;
              return null;
            case 'sessionKey':
              return List.filled(64, 'a').join();
            case 'readRecord':
              return call.arguments.toString().startsWith('indexCursor:')
                  ? jsonEncode('old-page')
                  : null;
            default:
              return null;
          }
        },
      );
      final drive = GoogleDriveService(
        clientFactory: () => MockClient((request) async {
          switch (request.url.path) {
            case '/drive-index/status':
              return http.Response(
                '{"configured":true,"background":true}',
                200,
              );
            case '/drive/v3/files':
              expect(
                request.url.queryParameters.containsKey('pageToken'),
                isFalse,
              );
              return http.Response(
                jsonEncode({
                  'files': [
                    {
                      'id': 'test-file',
                      'name': 'test.txt',
                      'mimeType': 'text/plain',
                      'size': '5',
                    },
                  ],
                }),
                200,
              );
            case '/drive-index/uploads':
              return http.Response(
                '{"job_id":"job","upload_required":true,"upload_url":"/drive-index/uploads/job/content"}',
                200,
              );
            case '/drive/v3/files/test-file':
              downloads++;
              if (downloads == 1) return http.Response('', 401);
              expect(request.headers['Authorization'], 'Bearer new-token');
              return http.Response('hello', 200);
            case '/drive-index/files/test-file':
              expect(request.headers.containsKey('Authorization'),isFalse);
              expect(request.body,'hello');
              completed=true;
              return http.Response('{"status":"indexed","chunks":1,"coverage":"content"}',200);
            default:
              throw StateError('Unexpected request ${request.url.path}');
          }
        }),
      );
      try {
        await drive.indexAllDrive();
        expect(downloads, 2);
        expect(completed, isTrue);
        expect((await MobileIndexCatalog.instance.request('/results?account=test%40example.com'))['items'],hasLength(1));
        expect(drive.indexing, isFalse);
      } finally {
        drive.dispose();
        binding.defaultBinaryMessenger.setMockMethodCallHandler(
          GoogleDriveService.channel,
          null,
        );
      }
    },
  );
}
