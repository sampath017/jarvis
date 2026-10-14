import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/api_service.dart';
import 'package:jarvis_collector/services/power_state.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('com.jarvis/context_runtime');

  test('Background endpoint follows the chat endpoint and user selection', () async {
    final configurations = <Map<dynamic, dynamic>>[];
    PowerState.setEnabled(false); // This configuration test must perform no HTTP.
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'configure') {
            configurations.add(Map<dynamic, dynamic>.from(call.arguments as Map));
          }
          return <String, dynamic>{};
        });
    final api = ApiService();
    await Future<void>.delayed(Duration.zero);
    expect(configurations.last['baseUrl'], api.baseUrl);
    api.setBaseUrl('https://context-test.invalid/');
    api.setUserId('context-test-user');
    await Future<void>.delayed(Duration.zero);
    expect(configurations.last, {
      'baseUrl': 'https://context-test.invalid',
      'userId': 'context-test-user',
    });
    api.dispose();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });
}
