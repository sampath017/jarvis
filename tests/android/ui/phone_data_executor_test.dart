import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/phone_data_executor.dart';

void main() {
  test(
    'routes typed reads independently without local NLP or permission prompts',
    () async {
      final calls = <Map<String, dynamic>>[];
      final executor = PhoneDataExecutor(
        usageReader: (args) async {
          calls.add(args);
          return {'status': 'ok', 'source': 'android_app_usage'};
        },
        healthReader: (args) async {
          calls.add(args);
          return {'status': 'permission_required', 'source': 'health_connect'};
        },
      );
      final usage = await executor.execute(
        {'operation': 'app_usage_read', 'start_date': '2026-10-26'},
        isActive: () async => true,
        isForeground: () => true,
      );
      final health = await executor.execute(
        {'operation': 'health_records_read', 'metric': 'sleep'},
        isActive: () async => true,
        isForeground: () => true,
      );
      expect(usage['source'], 'android_app_usage');
      expect(health['status'], 'permission_required');
      expect(calls.length, 2);
      expect(calls.first['start_date'], '2026-10-26');
    },
  );
  test(
    'inactive/background requests never read and cancelled reads do not leak results',
    () async {
      var count = 0;
      var active = true;
      final executor = PhoneDataExecutor(
        usageReader: (_) async {
          count++;
          active = false;
          return {'status': 'ok', 'private': 'result'};
        },
      );
      final background = await executor.execute(
        {'operation': 'app_usage_read'},
        isActive: () async => true,
        isForeground: () => false,
      );
      expect(background['status'], 'cancelled');
      expect(count, 0);
      final ended = await executor.execute(
        {'operation': 'app_usage_read'},
        isActive: () async => false,
        isForeground: () => true,
      );
      expect(ended['status'], 'cancelled');
      expect(count, 0);
      final cancelled = await executor.execute(
        {'operation': 'app_usage_read'},
        isActive: () async => active,
        isForeground: () => true,
      );
      expect(cancelled['status'], 'cancelled');
      expect(cancelled.containsKey('private'), isFalse);
    },
  );
  test('invalid and failed reads remain explicit failures', () async {
    final executor = PhoneDataExecutor(
      usageReader: (_) async => throw const FormatException('Bad date'),
      healthReader: (_) async => throw StateError('Read failed'),
    );
    for (final entry in {
      'app_usage_read': 'invalid_arguments',
      'health_records_read': 'unavailable',
      'unsupported': 'invalid_arguments',
    }.entries) {
      final result = await executor.execute(
        {'operation': entry.key},
        isActive: () async => true,
        isForeground: () => true,
      );
      expect(result['status'], entry.value);
    }
  });
}
