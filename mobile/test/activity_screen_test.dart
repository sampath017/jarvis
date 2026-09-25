import 'package:flutter/material.dart';
import 'package:jarvis_collector/services/session_preferences.dart';
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

class FakePreferences extends SessionPreferences {
  final Map<String, Map<String, Object?>> values = {};
  @override
  Future<Map<String, Map<String, Object?>>> load() async => Map.of(values);
  @override
  Future<void> save(String id, String? name, bool archived) async {
    values[id] = {'name': name, 'archived': archived ? 1 : 0};
  }
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
          home: ActivityScreen(
            history: FakeHistory(),
            preferences: FakePreferences(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Your day at a glance'), findsOneWidget);
      expect(find.text('2 records have no location'), findsOneWidget);
      await tester.drag(find.byType(ListView).first, const Offset(0, -250));
      await tester.pumpAndSettle();
      expect(find.text('Walking ended'), findsOneWidget);
      expect(find.text('Stationary'), findsOneWidget);
      expect(find.text('Location unavailable'), findsNWidgets(2));
      expect(tester.takeException(), isNull);
      await tester.drag(find.byType(ListView).first, const Offset(0, 500));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Map'));
      await tester.pumpAndSettle();
      expect(
        find.text('No location points were recorded for this day.'),
        findsOneWidget,
      );
      await tester.tap(find.byTooltip('Previous day'));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).first, const Offset(0, -500));
      await tester.pumpAndSettle();
      expect(find.text('Walking ended'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('session archive and name survive reopening the screen', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final preferences = FakePreferences();
    Widget screen() => MaterialApp(
      theme: AppTheme.darkTheme,
      home: ActivityScreen(history: FakeHistory(), preferences: preferences),
    );
    await tester.pumpWidget(screen());
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Manage session').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Rename'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), 'Morning walk');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Morning walk'), findsOneWidget);
    await tester.tap(find.byTooltip('Manage session').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuItem<String>).last);
    await tester.pumpAndSettle();
    expect(find.text('Morning walk'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(screen());
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, 'Archive'));
    await tester.pumpAndSettle();
    expect(find.text('Morning walk'), findsOneWidget);
    await tester.tap(find.byTooltip('Manage session').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Restore'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, 'Archive'));
    await tester.pumpAndSettle();
    expect(find.text('Morning walk'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
