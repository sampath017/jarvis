import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/power_state.dart';
import 'package:jarvis_collector/services/power_http.dart' as gated;
import 'package:jarvis_collector/services/runtime_power_service.dart';
import 'package:jarvis_collector/services/google_calendar_service.dart';
import 'package:jarvis_collector/services/command_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  late bool localOn;
  late bool confirmed;
  setUp(() {
    localOn = true;
    confirmed = true;
    PowerState.setEnabled(true);
    messenger.setMockMethodCallHandler(RuntimePowerService.channel, (
      call,
    ) async {
      if (call.method == 'status') {
        return {'enabled': localOn, 'cloudConfirmed': confirmed};
      }
      if (call.method == 'setEnabled') localOn = call.arguments as bool;
      if (call.method == 'setCloudConfirmed') {
        confirmed = call.arguments as bool;
      }
      return true;
    });
    messenger.setMockMethodCallHandler(
      GoogleCalendarService.channel,
      (_) async => 'a' * 64,
    );
  });
  tearDown(() {
    PowerState.setEnabled(true);
    messenger.setMockMethodCallHandler(RuntimePowerService.channel, null);
    messenger.setMockMethodCallHandler(GoogleCalendarService.channel, null);
  });

  test('Phone power is persisted independently of API confirmation', () async {
    var starts = 0;
    var stops = 0;
    final requests = <bool>[];
    final power = RuntimePowerService(
      controlClientFactory: () => MockClient((request) async {
        expect(request.headers['X-Calendar-Session'], 'a' * 64);
        final on = (jsonDecode(request.body) as Map)['enabled'] as bool;
        expect(localOn, on);
        expect(PowerState.enabled.value, on);
        requests.add(on);
        return http.Response(
          jsonEncode({'enabled': on, 'cloud_ready': true}),
          200,
        );
      }),
    );
    power.startServices = () async {
      starts++;
    };
    power.stopServices = () async {
      stops++;
    };
    await power.setEnabled(false);
    expect(localOn, false);
    expect(confirmed, true);
    await power.setEnabled(true);
    expect(localOn, true);
    expect(starts, 1);
    expect(stops, 2);
    expect(requests, isEmpty);
  });

  test(
    'Offline Off persists the phone setting without contacting a server',
    () async {
      var stopped = false;
      final power = RuntimePowerService(
        controlClientFactory: () => MockClient((_) async {
          throw http.ClientException('offline');
        }),
      );
      power.stopServices = () async {
        stopped = true;
      };
      await power.setEnabled(false);
      expect(localOn, false);
      expect(stopped, true);
      expect(confirmed, true);
      expect(power.error, isNull);
    },
  );

  test(
    'Offline powered-on launch starts local services without a request',
    () async {
      var starts = 0;
      final power = RuntimePowerService(
        controlClientFactory: () {
          fail('Launch must not create a cloud client');
        },
      );
      power.startServices = () async {
        starts++;
      };
      await power.initialize();
      expect(power.enabled, true);
      expect(starts, 1);
    },
  );

  test(
    'Launch exposes readiness before slow services and does not rewrite power',
    () async {
      final serviceReady = Completer<void>();
      final calls = <String>[];
      messenger.setMockMethodCallHandler(RuntimePowerService.channel, (
        call,
      ) async {
        calls.add(call.method);
        return {'enabled': true};
      });
      final power = RuntimePowerService();
      power.startServices = () => serviceReady.future;
      final ready = Completer<void>();
      power.addListener(() {
        if (power.initialized && !ready.isCompleted) ready.complete();
      });
      final launch = power.initialize();
      await ready.future;
      expect(power.enabled, true);
      expect(calls, ['status']);
      serviceReady.complete();
      await launch;
    },
  );

  test('A failed power read leaves a recoverable settings screen', () async {
    messenger.setMockMethodCallHandler(RuntimePowerService.channel, (_) async {
      throw PlatformException(code: 'read_failed');
    });
    final power = RuntimePowerService();
    await power.initialize();
    expect(power.initialized, true);
    expect(power.enabled, false);
    expect(power.error, isNotNull);
  });

  test('Offline power-on keeps local features available', () async {
    final power = RuntimePowerService(
      controlClientFactory: () => MockClient((_) async {
        throw http.ClientException('offline');
      }),
    );
    await power.setEnabled(true);
    expect(localOn, true);
    expect(power.enabled, true);
    expect(power.error, isNull);
  });

  test('Powered-off relaunch never queries cloud or starts services', () async {
    localOn = false;
    final power = RuntimePowerService(
      controlClientFactory: () {
        fail('Off launch must not create an HTTP client');
      },
    );
    power.startServices = () async {
      fail('Off launch must not start services');
    };
    await power.initialize();
    expect(power.initialized, true);
    expect(power.enabled, false);
  });

  test('Off gate prevents HTTP, command sends and reconnection', () async {
    PowerState.setEnabled(false);
    final client = gated.powerClient();
    await expectLater(
      client.get(Uri.parse('https://example.test')),
      throwsA(isA<http.ClientException>()),
    );
    client.close();
    final commands = CommandClient(
      clientFactory: () {
        fail('Off command must not connect');
      },
    );
    final result = await commands.send(
      baseUrl: 'https://example.test',
      headers: {},
      payload: {'request_id': 'one'},
    );
    expect(result['error'], 'Jarvis is powered off.');
  });
}
