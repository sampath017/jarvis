import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/mobile_store.dart';
import 'support/local_database.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'history includes overlapping durable power intervals without sensor observations',
    () async {
      final close = await startLocalDatabase();
      addTearDown(close);
      const channel = MethodChannel('com.jarvis/power');
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(channel, (call) async {
        expect(call.method, 'history');
        return [
          {
            'id': 'long-off',
            'start_at': '2026-10-20T08:00:00Z',
            'end_at': '2026-10-28T09:00:00Z',
          },
          {
            'id': 'unrelated',
            'start_at': '2026-10-19T08:00:00Z',
            'end_at': '2026-10-19T09:00:00Z',
          },
        ];
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
      final result = await MobileStore.instance.historyContext(
        DateTime.parse('2026-10-28T08:00:00Z'),
        DateTime.parse('2026-10-28T10:00:00Z'),
      );
      final documents = result['agent']['records'] as List;
      expect(documents, hasLength(1));
      final data = documents.single['data'];
      expect(data['timestamp'], '2026-10-28T08:00:00.000Z');
      expect(data['power_off_at'], '2026-10-20T08:00:00.000Z');
      expect(data['power_on_at'], '2026-10-28T09:00:00.000Z');
      expect(data['activity'], 'UNKNOWN');
      expect(data['source'], 'phone_power_switch');
    },
  );
}
