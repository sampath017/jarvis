import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;

class CommandProgress {
  const CommandProgress({
    required this.message,
    this.steps = const [],
    this.elapsedSeconds = 0,
    this.canStop = false,
  });
  final String message;
  final List<String> steps;
  final int elapsedSeconds;
  final bool canStop;
  factory CommandProgress.fromJson(Map<String, dynamic> json) =>
      CommandProgress(
        message: json['message']?.toString() ?? 'Working through your request',
        steps: (json['steps'] as List? ?? []).map((e) => e.toString()).toList(),
        elapsedSeconds: (json['elapsed_seconds'] as num?)?.toInt() ?? 0,
        canStop: json['status'] == 'running',
      );
}

/// Parses fragmented UTF-8 and SSE frames without treating a heartbeat as a result.
Stream<Map<String, dynamic>> decodeCommandEvents(
  Stream<List<int>> bytes,
) async* {
  var event = '';
  final data = <String>[];
  await for (final line
      in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
    if (line.isEmpty) {
      if (data.isNotEmpty) {
        final payload = jsonDecode(data.join('\n')) as Map<String, dynamic>;
        yield {'event': event, 'data': payload};
      }
      event = '';
      data.clear();
    } else if (line.startsWith('event:')) {
      event = line.substring(6).trim();
    } else if (line.startsWith('data:')) {
      data.add(line.substring(5).trimLeft());
    }
  }
}

class CommandClient {
  CommandClient({http.Client Function()? clientFactory})
    : _clientFactory = clientFactory ?? http.Client.new;
  final http.Client Function() _clientFactory;

  Future<Map<String, dynamic>> send({
    required String baseUrl,
    required Map<String, String> headers,
    required Map<String, dynamic> payload,
    void Function(CommandProgress)? onProgress,
  }) async {
    final watch = Stopwatch()..start();
    var failures = 0;
    var latest = const CommandProgress(message: 'Connecting to Jarvis');
    final body = jsonEncode(payload); // Immutable across every reconnect.
    while (watch.elapsed < const Duration(minutes: 15)) {
      final client = _clientFactory();
      try {
        final request =
            http.Request('POST', Uri.parse('$baseUrl/commands/stream'))
              ..headers.addAll({...headers, 'Accept': 'text/event-stream'})
              ..body = body;
        final response = await client
            .send(request)
            .timeout(const Duration(seconds: 20));
        if (response.statusCode != 200) {
          final raw = await response.stream.bytesToString().timeout(
            const Duration(seconds: 15),
          );
          if (response.statusCode >= 500) {
            throw http.ClientException('Service temporarily unavailable');
          }
          String detail =
              'Jarvis could not accept the request (${response.statusCode}).';
          try {
            detail = '${(jsonDecode(raw) as Map)['detail'] ?? detail}';
          } catch (_) {}
          return {'status': 'error', 'error': detail};
        }
        await for (final frame in decodeCommandEvents(
          response.stream.timeout(const Duration(seconds: 40)),
        )) {
          failures = 0;
          final data = Map<String, dynamic>.from(frame['data'] as Map);
          if (frame['event'] == 'result') return data;
          if (frame['event'] == 'progress') {
            latest = CommandProgress.fromJson(data);
            onProgress?.call(latest);
          }
        }
        throw http.ClientException(
          'Connection ended before the response arrived',
        );
      } catch (_) {
        failures++;
        onProgress?.call(
          CommandProgress(
            message: 'Reconnecting to your request',
            steps: latest.steps,
            elapsedSeconds: watch.elapsed.inSeconds,
          ),
        );
      } finally {
        client.close();
      }
      // Fetch a saved result before reopening the same request. Never use a new ID.
      final recovery = _clientFactory();
      try {
        final response = await recovery
            .get(
              Uri.parse(
                '$baseUrl/commands/requests/${Uri.encodeComponent(payload['request_id'].toString())}',
              ),
              headers: headers,
            )
            .timeout(const Duration(seconds: 15));
        if (response.statusCode == 200) {
          final snapshot = jsonDecode(response.body) as Map<String, dynamic>;
          if (snapshot['response'] is Map) {
            return Map<String, dynamic>.from(snapshot['response'] as Map);
          }
          latest = CommandProgress.fromJson(snapshot);
          onProgress?.call(latest);
          failures = 0;
        }
      } catch (_) {
        // Keep the accepted request's identity even when the network is unavailable.
      } finally {
        recovery.close();
      }
      if (failures >= 5) {
        return {
          'status': 'error',
          'error':
              'Connection lost while Jarvis was processing. Your request may still finish and sync into this chat. Check saved changes before sending it again.',
        };
      }
      await Future<void>.delayed(Duration(seconds: failures.clamp(1, 5)));
    }
    return {
      'status': 'error',
      'error':
          'This request exceeded the safe processing window. Check saved changes before sending it again.',
    };
  }
}
