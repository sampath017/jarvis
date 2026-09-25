import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/utils/ist_time.dart';
import 'package:jarvis_collector/models/chat_session.dart';

void main() {
  test('UTC and offset timestamps display the same IST time', () {
    expect(IstTime.clock(DateTime.parse('2026-10-08T10:45:00Z')), '16:15 IST');
    expect(
      IstTime.clock(DateTime.parse('2026-10-08T16:15:00+05:30')),
      '16:15 IST',
    );
    expect(
      IstTime.clock(DateTime.parse('2026-10-08T12:45:00+02:00')),
      '16:15 IST',
    );
  });
  test('chat day boundaries use IST', () {
    final time = IstTime.display(DateTime.parse('2026-10-08T20:00:00Z'));
    expect(time.day, 9);
    expect(IstTime.clock(DateTime.parse('2026-10-08T20:00:00Z')), '01:30 IST');
  });
  test(
    'stored chat instants remain UTC rather than shifted display values',
    () {
      final message = ChatMessage(
        text: 'hello',
        isUser: true,
        timestamp: DateTime.parse('2026-10-08T16:15:00+05:30'),
      );
      expect(message.toJson()['timestamp'], '2026-10-08T10:45:00.000Z');
    },
  );
}
