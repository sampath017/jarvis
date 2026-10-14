import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/calendar_executor.dart';

void main() {
  final original = <String, dynamic>{
    'id': 'event1',
    'etag': '"version1"',
    'summary': 'Planning',
    'start': {'dateTime': '2026-10-05T10:00:00+05:30'},
    'end': {'dateTime': '2026-10-05T11:00:00+05:30'},
  };
  Map<String, dynamic> proposal(String operation) => {
    'action_id': 'abcdef1234567890abcdef1234567890',
    'operation': operation,
    'default_calendar_id': 'primary',
    'event_id': 'event1',
    if (operation == 'create')
      'event': {...original}
        ..remove('id')
        ..remove('etag'),
    if (operation == 'update') 'event': {'summary': 'New planning'},
  };
  late Map<String, Map<String, dynamic>> receipts;
  late List<http.Request> requests;
  late bool active, foreground;
  late int mutationCode;
  CalendarExecutor executor() => CalendarExecutor(
    client: MockClient((request) async {
      requests.add(request);
      if (request.method != 'GET') {
        return http.Response(
          request.method == 'DELETE'
              ? ''
              : jsonEncode({...original, 'summary': 'New planning'}),
          mutationCode,
        );
      }
      if (request.url.path.contains('/calendarList/')) {
        return http.Response('{"summary":"Work","accessRole":"owner"}', 200);
      }
      if (request.url.path.endsWith('/events')) {
        return http.Response(
          jsonEncode({
            'items': [original],
            'nextPageToken': 'more',
          }),
          200,
        );
      }
      return http.Response(jsonEncode(original), 200);
    }),
    token: () async => 'device-token',
    readReceipt: (id) async => receipts[id],
    writeReceipt: (id, receipt) async {
      receipts[id] = receipt;
    },
    isActive: () async => active,
    isForeground: () => foreground,
  );
  setUp(() {
    receipts = {};
    requests = [];
    active = true;
    foreground = true;
    mutationCode = 200;
  });

  for (final operation in ['create', 'update', 'delete']) {
    test('$operation is never sent without affirmative approval', () async {
      final result = await executor().execute(
        proposal(operation),
        approve: (_) async => false,
      );
      expect(result['status'], 'declined');
      expect(requests.where((r) => r.method != 'GET'), isEmpty);
    });
    test(
      '$operation executes once after approval and memoizes repeated delivery',
      () async {
        var approvals = 0;
        final runner = executor();
        final action = proposal(operation);
        Future<bool> approve(Map<String, dynamic> preview) async {
          approvals++;
          expect(preview['calendar'], 'Work');
          return true;
        }

        expect(
          (await runner.execute(action, approve: approve))['status'],
          'ok',
        );
        expect(
          (await runner.execute(action, approve: approve))['status'],
          'ok',
        );
        expect(approvals, 1);
        final mutation = requests.singleWhere((r) => r.method != 'GET');
        expect(mutation.url.queryParameters['sendUpdates'], 'all');
        if (operation != 'create') {
          expect(mutation.headers['If-Match'], '"version1"');
        }
        if (operation == 'create') {
          expect(jsonDecode(mutation.body)['id'], action['action_id']);
        }
      },
    );
  }
  test('cancellation while preview is open prevents write', () async {
    final result = await executor().execute(
      proposal('create'),
      approve: (_) async {
        active = false;
        return true;
      },
    );
    expect(result['status'], 'not_executed');
    expect(requests.where((r) => r.method != 'GET'), isEmpty);
  });
  test('background execution is refused before any Google request', () async {
    foreground = false;
    expect(
      (await executor().execute(
        proposal('delete'),
        approve: (_) async => true,
      ))['status'],
      'not_executed',
    );
    expect(requests, isEmpty);
  });
  test('uncertain crash receipt never repeats an approved write', () async {
    final action = proposal('create');
    receipts[action['action_id']] = {
      'fingerprint': jsonEncode(action),
      'started_at': 'now',
    };
    expect(
      (await executor().execute(action, approve: (_) async => true))['status'],
      'uncertain',
    );
    expect(requests, isEmpty);
  });
  test('changed proposal cannot reuse previous permission', () async {
    final action = proposal('create');
    await executor().execute(action, approve: (_) async => true);
    final result = await executor().execute({
      ...action,
      'event': {...action['event'], 'summary': 'Unapproved'},
    }, approve: (_) async => true);
    expect(result['status'], 'not_executed');
    expect(requests.where((r) => r.method != 'GET').length, 1);
  });
  test(
    'reads do not request mutation approval and preserve pagination',
    () async {
      final action = {
        ...proposal('list'),
        'start_at': '2026-10-05T00:00:00+05:30',
        'end_at': '2026-10-06T00:00:00+05:30',
      };
      final result = await executor().execute(
        action,
        approve: (_) async => fail('Read requested approval'),
      );
      expect(result['status'], 'ok');
      expect(result['nextPageToken'], 'more');
      expect(requests.every((r) => r.method == 'GET'), true);
    },
  );
  test(
    'invalid time boundaries and hidden settings are rejected before approval',
    () async {
      for (final event in [
        {
          'summary': 'Wrong time',
          'start': {'dateTime': '2026-10-05T10:00:00'},
          'end': {'dateTime': '2026-10-05T11:00:00'},
        },
        {...proposal('create')['event'], 'guestsCanModify': true},
      ]) {
        final result = await executor().execute({
          ...proposal('create'),
          'event': event,
        }, approve: (_) async => fail('Invalid payload reached approval'));
        expect(result['status'], 'not_executed');
        receipts.clear();
      }
    },
  );
  test(
    'conflict does not overwrite a changed event or retry mutation',
    () async {
      mutationCode = 412;
      final runner = executor();
      final action = proposal('update');
      final result = await runner.execute(action, approve: (_) async => true);
      expect(result['message'], contains('changed elsewhere'));
      await runner.execute(
        action,
        approve: (_) async => fail('Retry asked for permission'),
      );
      expect(requests.where((r) => r.method == 'PATCH').length, 1);
    },
  );
}
