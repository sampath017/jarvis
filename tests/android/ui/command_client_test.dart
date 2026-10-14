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
    'CRLF multiline events preserve split Unicode text and ignore comments',
    () async {
      final bytes = utf8.encode(
        ': heartbeat\r\nevent: result\r\ndata: {"status":"ok",\r\ndata: "message":"తెలుగు 😀"}\r\n\r\n',
      );
      final frames = await decodeCommandEvents(
        Stream.fromIterable(bytes.map((b) => [b])),
      ).toList();
      expect(frames.single['event'], 'result');
      expect(frames.single['data']['message'], 'తెలుగు 😀');
    },
  );
  test('incomplete SSE frame is not mistaken for a completed result', () async {
    final frames = await decodeCommandEvents(
      Stream.value(
        utf8.encode('event: result\ndata: {"message":"unfinished"}\n'),
      ),
    ).toList();
    expect(frames, isEmpty);
  });
  for (final raw in [
    '<html>Bad gateway</html>',
    '{"detail":{"internal":"private"}}',
    '[]',
  ]) {
    test('permanent errors with unusual bodies stay readable: $raw', () async {
      var calls = 0;
      final client = CommandClient(
        clientFactory: () => FakeClient((request) async {
          calls++;
          return http.StreamedResponse(Stream.value(utf8.encode(raw)), 400);
        }),
      );
      final result = await client.send(
        baseUrl: 'https://example.test',
        headers: {},
        payload: {'request_id': 'stable', 'text': 'test'},
      );
      expect(result['error'], 'Jarvis could not accept the request (400).');
      expect(calls, 1);
    });
  }
  test(
    'malformed stream recovers the saved result using original request identity',
    () async {
      final payload = <String, dynamic>{
        'request_id': 'original',
        'text': 'test',
      };
      final paths = <String>[];
      final client = CommandClient(
        clientFactory: () => FakeClient((request) async {
          paths.add(request.url.path);
          if (request.method == 'POST') {
            payload['request_id'] = 'changed-after-send';
            return http.StreamedResponse(
              Stream.value(
                utf8.encode('event: progress\ndata: broken-json\n\n'),
              ),
              200,
            );
          }
          return http.StreamedResponse(
            Stream.value(
              utf8.encode('{"response":{"status":"ok","message":"Recovered"}}'),
            ),
            200,
          );
        }),
      );
      final result = await client.send(
        baseUrl: 'https://example.test',
        headers: {},
        payload: payload,
      );
      expect(result['message'], 'Recovered');
      expect(paths, ['/commands/stream', '/commands/requests/original']);
    },
  );
  test(
    'missing processing session never repeats a potentially executed command',
    () async {
      final bodies = <String>[];
      final progress = <String>[];
      final client = CommandClient(
        clientFactory: () => FakeClient((request) async {
          if (request.method == 'GET') {
            return http.StreamedResponse(
              Stream.value(utf8.encode('{"detail":"not found"}')),
              404,
            );
          }
          bodies.add((request as http.Request).body);
          if (bodies.length == 1) {
            return http.StreamedResponse(
              Stream.value(utf8.encode('unavailable')),
              503,
            );
          }
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                'event: progress\ndata: {"message":"Working"}\n\nevent: result\ndata: {"status":"ok","message":"Done"}\n\n',
              ),
            ),
            200,
          );
        }),
      );
      final result = await client.send(
        baseUrl: 'https://example.test',
        headers: {},
        payload: {'request_id': 'stable', 'text': 'test'},
        onProgress: (p) => progress.add(p.message),
      );
      expect(result['status'], 'error');
      expect(result['error'],contains('processing session ended'));
      expect(bodies.length, 1);
    },
  );
  test(
    'file validation failures show a readable message without raw metadata',
    () async {
      final client = CommandClient(
        clientFactory: () => FakeClient((request) async {
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'detail': [
                    {
                      'type': 'string_pattern_mismatch',
                      'loc': ['body', 'file_memories', 4, 'url'],
                      'input':
                          'https://aistudio.google.com/app/prompts?private=value',
                    },
                  ],
                }),
              ),
            ),
            422,
          );
        }),
      );
      final result = await client.send(
        baseUrl: 'https://example.test',
        headers: {},
        payload: {'text': 'Where was I yesterday?'},
      );
      expect(result['status'], 'error');
      expect(result['error'], contains('file references'));
      expect(result['error'], isNot(contains('string_pattern_mismatch')));
      expect(result['error'], isNot(contains('private=value')));
    },
  );
  test(
    'other validation failures and readable server errors remain usable',
    () async {
      for (final status in [422, 403]) {
        final client = CommandClient(
          clientFactory: () => FakeClient((request) async {
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'detail': status == 422
                        ? [
                            {
                              'loc': ['body', 'text'],
                              'type': 'string_too_long',
                            },
                          ]
                        : 'Reconnect your account.',
                  }),
                ),
              ),
              status,
            );
          }),
        );
        final result = await client.send(
          baseUrl: 'https://example.test',
          headers: {},
          payload: {'text': 'test'},
        );
        expect(
          result['error'],
          status == 422
              ? 'Jarvis could not accept this message. Check the text and attachments, then try again.'
              : 'Reconnect your account.',
        );
      }
    },
  );
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
