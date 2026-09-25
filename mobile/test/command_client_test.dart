import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_collector/services/command_client.dart';

class FakeClient extends http.BaseClient {
  FakeClient(this.handle);
  final Future<http.StreamedResponse> Function(http.BaseRequest) handle;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      handle(request);
}

void main() {
  test(
    'parses fragmented UTF-8, heartbeat comments, and result frames',
    () async {
      final bytes = utf8.encode(
        ': ping\n\nevent: progress\ndata: {"message":"Checking café"}\n\nevent: result\ndata: {"status":"ok","message":"Done"}\n\n',
      );
      final frames = await decodeCommandEvents(
        Stream.fromIterable(bytes.map((b) => [b])),
      ).toList();
      expect(frames.length, 2);
      expect(frames.first['data']['message'], 'Checking café');
      expect(frames.last['event'], 'result');
    },
  );

  test(
    'recovers saved result after a disconnected stream without resubmitting actions',
    () async {
      final paths = <String>[];
      final bodies = <String>[];
      final progress = <String>[];
      final client = CommandClient(
        clientFactory: () => FakeClient((request) async {
          paths.add(request.url.path);
          if (request.method == 'POST') {
            bodies.add((request as http.Request).body);
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  'event: progress\ndata: {"message":"Saving your reminder","status":"running"}\n\n',
                ),
              ),
              200,
            );
          }
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                '{"status":"complete","response":{"status":"ok","message":"Saved once"}}',
              ),
            ),
            200,
          );
        }),
      );
      final result = await client.send(
        baseUrl: 'https://example.test',
        headers: {},
        payload: {'request_id': 'stable-id', 'text': 'test'},
        onProgress: (p) => progress.add(p.message),
      );
      expect(result['message'], 'Saved once');
      expect(paths, ['/commands/stream', '/commands/requests/stable-id']);
      expect(bodies.length, 1);
      expect(progress, contains('Saving your reminder'));
    },
  );
}
