import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/activity_history_service.dart';
import 'package:jarvis_collector/ui/screens/activity_screen.dart';
import 'package:jarvis_collector/ui/theme.dart';

class FakeHistory implements ActivityHistoryService {
  @override
  String dayKey(DateTime day) => day.toIso8601String().substring(0, 10);

  @override
  Future<Map<String, dynamic>?> cachedDay(DateTime day) async => null;

  @override
  Future<Map<String, dynamic>> fetchDay(DateTime day) async => {
    'observations': [
      {
        'timestamp': DateTime(
          day.year,
          day.month,
          day.day,
          9,
        ).toIso8601String(),
        'activity': 'WALKING',
        'transition': 'EXIT',
      },
      {
        'timestamp': DateTime(
          day.year,
          day.month,
          day.day,
          9,
          1,
        ).toIso8601String(),
        'activity': 'STILL',
        'transition': 'ENTER',
      },
    ],
    'timeline': [
      {
        'first_observed_at': DateTime(
          day.year,
          day.month,
          day.day,
          9,
        ).toIso8601String(),
        'last_observed_at': DateTime(
          day.year,
          day.month,
          day.day,
          9,
        ).toIso8601String(),
        'activity': 'WALKING',
        'transition': 'EXIT',
      },
      {
        'first_observed_at': DateTime(
          day.year,
          day.month,
          day.day,
          9,
          1,
        ).toIso8601String(),
        'last_observed_at': DateTime(
          day.year,
          day.month,
          day.day,
          9,
          1,
        ).toIso8601String(),
        'activity': 'STILL',
        'transition': 'ENTER',
      },
    ],
  };
}

void main() {
  testWidgets(
    'shows activity endings and missing locations on a narrow screen',
    (tester) async {
      tester.view.physicalSize = const Size(360, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: ActivityScreen(history: FakeHistory()),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Your day at a glance'), findsOneWidget);
      expect(find.text('2 records have no location'), findsOneWidget);
      expect(find.text('Walking ended'), findsOneWidget);
      expect(find.text('Stationary'), findsOneWidget);
      expect(find.text('Location unavailable'), findsNWidgets(2));
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('Map'));
      await tester.pumpAndSettle();
      expect(
        find.text('No location points were recorded for this day.'),
        findsOneWidget,
      );
      await tester.tap(find.byTooltip('Previous day'));
      await tester.pumpAndSettle();
      expect(find.text('Walking ended'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
