import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/location_result.dart';

void main() {
  test('device errors retain a specific reason', () async {
    final result = await readLocationResult(() async {
      throw const LocationReadFailure('permission_denied', 'Allow Location.');
    });
    expect(result['status'], 'unavailable');
    expect(result['reason'], 'permission_denied');
    expect(result['message'], 'Allow Location.');
  });
  test('missing fix does not claim GPS is disabled', () async {
    final result = await readLocationResult(() async => null);
    expect(result['reason'], 'no_fix');
    expect(result['message'], contains('does not establish'));
  });
  test('unexpected plugin failure becomes a reportable result', () async {
    final result = await readLocationResult(
      () async => throw StateError('plugin'),
    );
    expect(result['status'], 'unavailable');
    expect(result['reason'], 'read_failed');
  });
  test('cached fix retains observation time, not retrieval time', () async {
    final observed = DateTime.utc(2026, 10, 6, 12);
    final result = await readLocationResult(
      () async => {
        'latitude': 0.0,
        'longitude': 10.0,
        'accuracy': 12.0,
        'timestamp_ms': observed.millisecondsSinceEpoch.toDouble(),
      },
    );
    expect(result['status'], 'ok');
    expect(result['observed_at'], observed.toIso8601String());
    expect(result['gps'], {
      'latitude': 0.0,
      'longitude': 10.0,
      'accuracy': 12.0,
    });
  });
}
