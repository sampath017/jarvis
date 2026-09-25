import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/health_service.dart';

void main() {
  test('routes step and sleep questions to the local health reader', () {
    expect(HealthService.isHealthQuestion('How many steps did I do today?'), isTrue);
    expect(HealthService.isHealthQuestion('How did I sleep last night?'), isTrue);
    expect(HealthService.isHealthQuestion('Remind me to check my steps today'), isFalse);
    expect(HealthService.isHealthQuestion('I slept badly; save a note'), isFalse);
  });
}
