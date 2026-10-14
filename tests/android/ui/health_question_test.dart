import 'package:flutter_test/flutter_test.dart';
import 'package:health/health.dart';
import 'package:jarvis_collector/services/health_service.dart';

class FakeHealth extends Health {
  bool permitted = true, enabled = true;
  int permissionRequests = 0;
  List<HealthDataPoint> records = [];
  List<(DateTime, DateTime)> windows = [];
  List<HealthDataType>? requestedTypes;
  @override
  Future<void> configure() async {}
  @override
  Future<bool> isHealthConnectAvailable() async => enabled;
  @override
  Future<bool?> hasPermissions(
    List<HealthDataType> types, {
    List<HealthDataAccess>? permissions,
  }) async => permitted;
  @override
  Future<bool> requestAuthorization(
    List<HealthDataType> types, {
    List<HealthDataAccess>? permissions,
  }) async {
    permissionRequests++;
    return permitted;
  }

  @override
  Future<List<HealthDataPoint>> getHealthDataFromTypes({
    required List<HealthDataType> types,
    Map<HealthDataType, HealthDataUnit>? preferredUnits,
    required DateTime startTime,
    required DateTime endTime,
    List<RecordingMethod> recordingMethodsToFilter = const [],
  }) async {
    windows.add((startTime, endTime));
    requestedTypes = types;
    return records;
  }

  @override
  Future<int?> getTotalStepsInInterval(
    DateTime startTime,
    DateTime endTime, {
    bool includeManualEntry = true,
  }) async => 1234;
}

HealthDataPoint point(
  String from,
  String to, {
  String source = 'Example watch',
}) => HealthDataPoint(
  uuid: '$from-$source',
  value: NumericHealthValue(numericValue: 1),
  type: HealthDataType.SLEEP_SESSION,
  unit: HealthDataUnit.MINUTE,
  dateFrom: DateTime.parse(from),
  dateTo: DateTime.parse(to),
  sourcePlatform: HealthPlatformType.googleHealthConnect,
  sourceDeviceId: 'private-device',
  sourceId: 'private-source',
  sourceName: source,
);
void main() {
  final now = DateTime.utc(2026, 10, 27, 6);
  test(
    'missing permission is explicit and does not open OS authorization',
    () async {
      final client = FakeHealth()..permitted = false;
      final service = HealthService(client: client);
      final result = await service.readToolRecords({
        'metric': 'steps',
        'start_date': '2026-10-26',
      }, now: now);
      expect(result['status'], 'permission_required');
      expect(client.permissionRequests, 0);
      expect(client.windows, isEmpty);
    },
  );
  test('missing provider and empty records stay unknown, not zero', () async {
    final client = FakeHealth()..enabled = false;
    final service = HealthService(client: client);
    expect(
      (await service.readToolRecords({
        'metric': 'steps',
        'start_date': '2026-10-26',
      }, now: now))['status'],
      'unavailable',
    );
    client.enabled = true;
    final result = await service.readToolRecords({
      'metric': 'steps',
      'start_date': '2026-10-26',
    }, now: now);
    final day = (result['days'] as List).single;
    expect(day['status'], 'no_records');
    expect(day.containsKey('steps'), isFalse);
  });
  test('steps use aggregated provider count in exact IST day window', () async {
    final client = FakeHealth()
      ..records = [point('2026-10-26T01:00:00Z', '2026-10-26T02:00:00Z')];
    final result = await HealthService(client: client).readToolRecords({
      'metric': 'steps',
      'start_date': '2026-10-26',
    }, now: now);
    expect(result['source'], 'health_connect');
    expect((result['days'] as List).single['steps'], 1234);
    expect(client.windows.single, (
      DateTime.utc(2026, 10, 25, 18, 30),
      DateTime.utc(2026, 10, 26, 18, 30),
    ));
    expect(client.requestedTypes, [HealthDataType.STEPS]);
    expect(result.toString(), isNot(contains('private-device')));
  });
  test(
    'sleep date is the night ending that day and overlapping sessions count once',
    () async {
      final client = FakeHealth()
        ..records = [
          point('2026-10-25T17:30:00Z', '2026-10-25T22:30:00Z'),
          point(
            '2026-10-25T21:30:00Z',
            '2026-10-26T00:30:00Z',
            source: 'Example phone',
          ),
          point('2026-10-25T17:30:00Z', '2026-10-25T22:30:00Z'),
        ];
      final result = await HealthService(client: client).readToolRecords({
        'metric': 'sleep',
        'start_date': '2026-10-26',
      }, now: now);
      expect(client.windows.single, (
        DateTime.utc(2026, 10, 25, 12, 30),
        DateTime.utc(2026, 10, 26, 12, 30),
      ));
      final day = (result['days'] as List).single;
      expect(
        day['recorded_session_ms'],
        const Duration(hours: 7).inMilliseconds,
      );
      expect(day['session_count'], 2);
      expect(result['notes'], contains('not a medical measure'));
      expect(client.requestedTypes, [HealthDataType.SLEEP_SESSION]);
    },
  );
  test('today is capped at now and unsupported metrics never read', () async {
    final client = FakeHealth();
    final service = HealthService(client: client);
    await service.readToolRecords({
      'metric': 'steps',
      'start_date': '2026-10-27',
    }, now: now);
    expect(client.windows.single.$2, now);
    await expectLater(
      service.readToolRecords({
        'metric': 'movement',
        'start_date': '2026-10-27',
      }, now: now),
      throwsFormatException,
    );
    expect(client.windows.length, 1);
  });
}
