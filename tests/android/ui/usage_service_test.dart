import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/usage_service.dart';
import 'package:jarvis_collector/services/phone_data_window.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final now = DateTime.utc(2026, 10, 26, 19); // 27 Oct IST
  final reads = <String>[];
  var responses = <String, Map<String, dynamic>>{};
  Map<String, dynamic> records(String day, List<int> durations) => {
    'day': day,
    'total_ms': durations.fold<int>(0, (a, b) => a + b),
    'apps': [
      for (var i = 0; i < durations.length; i++)
        {
          'name': 'App $i',
          'package': 'package.$i',
          'milliseconds': durations[i],
        },
    ],
  };
  setUp(() {
    reads.clear();
    responses = {};
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(UsageService.channel, (call) async {
          expect(call.method, 'read');
          final day = call.arguments as String;
          reads.add(day);
          return jsonEncode(responses[day] ?? {'error': 'no_records'});
        });
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(UsageService.channel, null),
  );

  test('model dates reach native reader with precise durations', () async {
    responses['2026-10-26'] = records('2026-10-26', [90000, 30000]);
    final data = await UsageService.readToolRecords({
      'start_date': '2026-10-26',
    }, now: now);
    expect(reads, ['2026-10-26']);
    expect(data['source'], 'android_app_usage');
    expect(data['status'], 'ok');
    final day = (data['days'] as List).single;
    expect(day['total_ms'], 120000);
    expect(day['apps'].map((app) => app['milliseconds']), [90000, 30000]);
    expect(data.containsKey('markdown'), isFalse); // Model owns formatting.
  });
  test(
    'bounded categories retain all recorded time in an Other aggregate',
    () async {
      responses['2026-10-26'] = records(
        '2026-10-26',
        List.generate(20, (i) => (i + 1) * 60000),
      );
      final data = await UsageService.readToolRecords({
        'start_date': '2026-10-26',
        'max_apps': 12,
      }, now: now);
      final day = (data['days'] as List).single;
      final apps = day['apps'] as List;
      expect(apps.length, 12);
      expect(apps.last['name'], 'Other apps');
      expect(
        apps.fold<num>(0, (sum, app) => sum + (app['milliseconds'] as num)),
        day['total_ms'],
      );
      expect(day['aggregated_remainder'], isTrue);
    },
  );
  test(
    'filter precedes limit and full day stays distinct from matching total',
    () async {
      responses['2026-10-26'] = records('2026-10-26', [90000, 30000]);
      final data = await UsageService.readToolRecords({
        'start_date': '2026-10-26',
        'app_query': 'PACKAGE.1',
        'max_apps': 1,
      }, now: now);
      final day = (data['days'] as List).single;
      expect(day['total_ms'], 120000);
      expect(day['matched_ms'], 30000);
      expect((day['apps'] as List).single['name'], 'App 1');
    },
  );
  test(
    'inclusive range keeps unavailable days unknown and reports partial data',
    () async {
      responses['2026-10-26'] = records('2026-10-26', [60000]);
      final data = await UsageService.readToolRecords({
        'start_date': '2026-10-25',
        'end_date': '2026-10-26',
      }, now: now);
      expect(reads, ['2026-10-25', '2026-10-26']);
      expect(data['status'], 'partial');
      final missing = (data['days'] as List).first;
      expect(missing['status'], 'unavailable');
      expect(missing.containsKey('total_ms'), isFalse);
    },
  );
  test(
    'permission and incorrect native dates cannot become zero usage',
    () async {
      responses['2026-10-26'] = {'error': 'usage_access_required'};
      var data = await UsageService.readToolRecords({
        'start_date': '2026-10-26',
      }, now: now);
      expect(data['status'], 'unavailable');
      expect((data['days'] as List).single['reason'], 'usage_access_required');
      responses['2026-10-26'] = records('2026-10-25', [60000]);
      data = await UsageService.readToolRecords({
        'start_date': '2026-10-26',
      }, now: now);
      expect(data['status'], 'unavailable');
      expect((data['days'] as List).single.containsKey('total_ms'), isFalse);
    },
  );
  test(
    'strict dates, future dates, reversed and oversized windows are rejected before reads',
    () async {
      for (final args in [
        {'start_date': '2026-02-30'},
        {'start_date': '2026-10-28'},
        {'start_date': '2026-10-26', 'end_date': '2026-10-25'},
        {'start_date': '2026-09-26', 'end_date': '2026-10-27'},
        {'start_date': '2026-10-26', 'max_apps': 101},
      ]) {
        await expectLater(
          UsageService.readToolRecords(args, now: now),
          throwsFormatException,
        );
      }
      expect(reads, isEmpty);
    },
  );
  test('phone windows use IST midnight across the UTC date boundary', () {
    final window = PhoneDataWindow.parse('2026-10-27', '', now: now);
    expect(window.midnight(window.start), DateTime.utc(2026, 10, 26, 18, 30));
    expect(
      window.capAtNow(window.midnight(window.end).add(const Duration(days: 1))),
      now,
    );
  });
}
