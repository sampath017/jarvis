import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      GoogleDriveService.channel,
      (call) async {
        return switch (call.method) {
          'status' => {'connected': true, 'email': 'test@example.com'},
          'token' => 'test-token',
          'readRecord' => null,
          _ => true,
        };
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
    'search discovers existing files without Jarvis app properties',
    () async {
      final drive = GoogleDriveService(
        clientFactory: () => MockClient((request) async {
          final query = request.url.queryParameters['q']!;
          expect(query, isNot(contains('jarvisMemory')));
          expect(query, contains("fullText contains 'Aadhaar'"));
          expect(request.url.queryParameters['pageSize'], '50');
          return http.Response(
            jsonEncode({
              'files': [
                {
                  'id': 'existing',
                  'name': 'Aadhaar.pdf',
                  'mimeType': 'application/pdf',
                  'size': '100',
                },
              ],
            }),
            200,
          );
        }),
      );
      final files = await drive.searchDrive('Aadhaar');
      expect(files.single['id'], 'existing');
      expect(drive.memories.single['account'], 'test@example.com');
    },
  );

  test('Drive query escapes apostrophes', () async {
    final drive = GoogleDriveService(
      clientFactory: () => MockClient((request) async {
        expect(
          request.url.queryParameters['q'],
          contains(r"fullText contains 'Sam\'s'"),
        );
        return http.Response('{"files":[]}', 200);
      }),
    );
    await drive.searchDrive("Sam's");
  });

  test(
    'missing file and denied permission have distinct actionable errors',
    () {
      expect(
        GoogleDriveService.driveError(404),
        contains('deleted or is not accessible'),
      );
      expect(
        GoogleDriveService.driveError(403),
        contains('download restrictions'),
      );
      expect(GoogleDriveService.driveError(401), contains('Reconnect'));
    },
  );
}
