import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/usage_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('recognizes screen-time questions without stealing reminders', () {
    expect(UsageService.isUsageQuestion('Instagram usage today'), isTrue);
    expect(
      UsageService.isUsageQuestion('How much time did I spend on WhatsApp?'),
      isTrue,
    );
    expect(UsageService.isUsageQuestion('Show all apps screen time'), isTrue);
    expect(
      UsageService.isUsageQuestion('Remind me to stop using Instagram'),
      isFalse,
    );
    expect(UsageService.isUsageQuestion('Where am I?'), isFalse);
    expect(UsageService.isUsageQuestion('digital wellbeing today'), isTrue);
    expect(UsageService.isUsageQuestion('give today total report'), isTrue);
  });
  test('day total is retained when a report also names an app', () {
    final data = {
      'day': '2026-10-04',
      'apps': [
        {
          'name': 'Instagram',
          'package': 'com.instagram.android',
          'milliseconds': 7200000,
        },
      ],
      'text': 'Day total screen time: 7h 0m\nInstagram: 2h 0m\nYouTube: 2h 0m',
    };
    expect(
      UsageService.formatAnswer(
        'today total digital wellbeing including Instagram',
        data,
      ),
      data['text'],
    );
  });
  test('filters app names and preserves unavailable-data distinction', () {
    final answer = UsageService.formatAnswer('Instagram usage', {
      'day': '2026-10-03',
      'apps': [
        {
          'name': 'Instagram',
          'package': 'com.instagram.android',
          'milliseconds': 5400000,
        },
        {
          'name': 'Chrome',
          'package': 'com.android.chrome',
          'milliseconds': 60000,
        },
      ],
      'text': 'All apps',
    });
    expect(answer, contains('1h 30m'));
    expect(answer, isNot(contains('Chrome')));
    expect(
      UsageService.formatAnswer('screen time', {'error': 'no_records'}),
      contains('does not mean'),
    );
  });
  test(
    'uses IST day boundaries and yesterday instead of the host timezone',
    () async {
      String? requestedDay;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(UsageService.channel, (
            MethodCall call,
          ) async {
            requestedDay = call.arguments as String;
            return '{"error":"no_records"}';
          });
      await UsageService.answer(
        'screen time yesterday',
        now: DateTime.utc(2026, 10, 3, 20),
      );
      expect(requestedDay, '2026-10-03');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(UsageService.channel, null);
    },
  );
}
