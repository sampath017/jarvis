import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/screens/motion_monitoring_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('com.jarvis/foreground_service');
  final calls = <String>[];
  setUp(() {
    calls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call.method);
          if (call.method == 'motionDiagnostics') {
            return jsonEncode({'monitoring': true, 'records': []});
          }
          if (call.method == 'motionClock') {
            return {'wallMs': 1000, 'elapsedMs': 100, 'bootCount': 1};
          }
          return true;
        });
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null),
  );

  testWidgets(
    'Starting an annotation does not save an unobserved future interval',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: MotionMonitoringScreen()),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Start activity label'), 200);
      await tester.tap(find.text('Start activity label'));
      await tester.pumpAndSettle();
      expect(calls, contains('motionClock'));
      expect(calls, isNot(contains('labelMotion')));
      await tester.scrollUntilVisible(find.text('Finish and save label'), 200);
      await tester.tap(find.text('Finish and save label'));
      await tester.pumpAndSettle();
      expect(calls.where((c) => c == 'labelMotion').length, 1);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets('Discarding a label never creates training ground truth', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: MotionMonitoringScreen()));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Start activity label'), 200);
    await tester.tap(find.text('Start activity label'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Discard label'), 200);
    await tester.tap(find.text('Discard label'));
    await tester.pumpAndSettle();
    expect(calls, isNot(contains('labelMotion')));
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
