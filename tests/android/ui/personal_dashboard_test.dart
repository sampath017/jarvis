import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/screens/personal_dashboard_screen.dart';
import 'package:jarvis_collector/ui/screens/activity_screen.dart';
import 'package:jarvis_collector/services/power_state.dart';
import 'package:jarvis_collector/services/usage_service.dart';
import 'package:jarvis_collector/ui/theme.dart';

Finder dayContent(Finder matching, [int daysAgo = 0]) {
  final day = DateTime.now()
      .toUtc()
      .add(const Duration(hours: 5, minutes: 30))
      .subtract(Duration(days: daysAgo))
      .toIso8601String()
      .substring(0, 10);
  return find.descendant(
    of: find.byKey(ValueKey('overview-day-$day')),
    matching: matching,
  );
}

void main() {
  testWidgets('cached date navigation stays instant during background collection', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 1000);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final today = DateTime.now().toUtc().add(
      const Duration(hours: 5, minutes: 30),
    );
    String key(int offset) => today
        .subtract(Duration(days: offset))
        .toIso8601String()
        .substring(0, 10);
    Map<String, dynamic> summary(String name, int minutes) => {
      'total_ms': minutes * 60000,
      'apps': [
        {'name': name, 'package': name, 'milliseconds': minutes * 60000},
      ],
    };
    final cached = {
      key(0): summary('Today app', 15),
      key(1): summary('Yesterday app', 25),
      key(2): summary('Older app', 35),
    };
    final collection = Completer<String>();
    final calls = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(UsageService.channel, (call) async {
      calls.add(call.method);
      if (call.method == 'cachedDays') return jsonEncode(cached);
      if (call.method == 'refreshCache') return collection.future;
      if (call.method == 'takeInitialDay') return null;
      throw StateError(
        'Date navigation must not query Android: ${call.method}',
      );
    });
    addTearDown(() {
      messenger.setMockMethodCallHandler(UsageService.channel, null);
      UsageService.overviewDays.value = {};
    });
    await UsageService.initialize();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: const PersonalDashboardScreen(),
      ),
    );
    await tester.pump();
    expect(find.text('Today app'), findsOneWidget);
    expect(dayContent(find.text('—')), findsNothing);
    expect(calls.where((call) => call == 'cachedDays'), hasLength(1));
    final previous = find.byKey(
      ValueKey('overview-day-${key(1)}'),
      skipOffstage: false,
    );
    // The neighboring page is already laid out at full size before navigation.
    expect(tester.getSize(previous).width, 390);
    expect(
      find.descendant(
        of: previous,
        matching: find.text('Yesterday app', skipOffstage: false),
        skipOffstage: false,
      ),
      findsOneWidget,
    );
    final beforeNavigation = [...calls];
    final todayPage = find.byKey(ValueKey('overview-day-${key(0)}'));
    await tester.tap(find.byTooltip('Previous day').hitTestable());
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 60));
    // Both complete pages slide across the same viewport; neither blanks out.
    expect(tester.getTopLeft(todayPage).dx, inExclusiveRange(0, 390));
    expect(tester.getTopLeft(previous).dx, inExclusiveRange(-390, 0));
    expect(dayContent(find.text('—'), 1), findsNothing);
    await tester.pumpAndSettle();
    expect(find.text('Yesterday app'), findsOneWidget);
    expect(find.text('Today app').hitTestable(), findsNothing);
    await tester.tap(find.byTooltip('Previous day').hitTestable());
    await tester.pumpAndSettle();
    expect(find.text('Older app'), findsOneWidget);
    await tester.tap(find.byTooltip('Next day').hitTestable());
    await tester.pumpAndSettle();
    expect(find.text('Yesterday app'), findsOneWidget);
    expect(calls, beforeNavigation);
    // Native collection publishes days incrementally, without a navigation reload.
    cached[key(1)] = summary('Updated yesterday', 30);
    await messenger.handlePlatformMessage(
      UsageService.channel.name,
      const StandardMethodCodec().encodeMethodCall(
        MethodCall('usageDayUpdated', {
          'day': key(1),
          'data': jsonEncode(cached[key(1)]),
        }),
      ),
      (_) {},
    );
    await tester.pump();
    expect(find.text('Updated yesterday'), findsOneWidget);
    // A completed background refresh must not replace the selected day with today.
    collection.complete(
      jsonEncode({...cached, key(0): summary('Updated today', 20)}),
    );
    await tester.pumpAndSettle();
    expect(find.text('Updated yesterday'), findsOneWidget);
    // Swipes use the same cached pages, with no additional usage query.
    final pager = find.byKey(const ValueKey('overview-days'));
    await tester.drag(pager, const Offset(-350, 0));
    await tester.pumpAndSettle();
    final controller = tester.widget<PageView>(pager).controller!;
    expect(controller.page, 29);
    await tester.tap(find.byTooltip('Next day').hitTestable());
    await tester.pumpAndSettle();
    expect(controller.page, 29);
    expect(calls, beforeNavigation);
    await tester.pumpWidget(const SizedBox.shrink());
    // Reopening Overview uses the already hydrated cache without a SQLite read.
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: const PersonalDashboardScreen(),
      ),
    );
    expect(find.text('Updated today'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(calls.where((call) => call == 'cachedDays'), hasLength(1));
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('overview shows top five apps while keeping the complete total', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(600, 1600);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: PersonalDashboardScreen(
          load: (_) async => {
            'phone': {
              'total_ms': 28 * 60000,
              'apps': [
                for (var minutes = 1; minutes <= 7; minutes++)
                  {
                    'name': 'App $minutes',
                    'package': 'app.$minutes',
                    'milliseconds': minutes * 60000,
                  },
              ],
            },
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('28 min'), findsOneWidget);
    for (var minutes = 3; minutes <= 7; minutes++) {
      expect(find.text('App $minutes'), findsOneWidget);
    }
    expect(find.text('App 1'), findsNothing);
    expect(find.text('App 2'), findsNothing);
    final names = tester
        .widgetList<Text>(dayContent(find.byType(Text)))
        .map((text) => text.data)
        .where((text) => text?.startsWith('App ') ?? false);
    expect(names, ['App 7', 'App 6', 'App 5', 'App 4', 'App 3']);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('day pages preserve scrolling when revisiting a date', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 640);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: PersonalDashboardScreen(
          load: (_) async => {
            'phone': {
              'total_ms': 30 * 60000,
              'apps': [
                for (var index = 0; index < 5; index++)
                  {
                    'name': 'App $index',
                    'package': 'app.$index',
                    'milliseconds': (index + 1) * 60000,
                  },
              ],
            },
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    final scrollable = dayContent(find.byType(Scrollable));
    final original = tester.state<ScrollableState>(scrollable).position;
    await tester.drag(dayContent(find.byType(ListView)), const Offset(0, -300));
    await tester.pumpAndSettle();
    final offset = original.pixels;
    expect(offset, greaterThan(0));
    final pager = find.byKey(const ValueKey('overview-days'));
    await tester.drag(pager, const Offset(350, 0));
    await tester.pumpAndSettle();
    await tester.drag(pager, const Offset(-350, 0));
    await tester.pumpAndSettle();
    final returned = tester
        .state<ScrollableState>(dayContent(find.byType(Scrollable)))
        .position;
    expect(identical(original, returned), isTrue);
    expect(returned.pixels, offset);
    returned.jumpTo(0);
    await tester.pump();
    await tester.tap(find.byTooltip('Previous day').hitTestable());
    await tester.pumpAndSettle();
    expect(tester.widget<PageView>(pager).controller!.page, 28);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('dashboard shows local Android usage and fits a phone', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final boundary = GlobalKey();
    const fontPath = String.fromEnvironment('UI_FONT_PATH');
    if (fontPath.isNotEmpty) {
      final font = FontLoader('Roboto')
        ..addFont(
          Future.value(ByteData.sublistView(File(fontPath).readAsBytesSync())),
        );
      await font.load();
    }
    const iconPath = String.fromEnvironment('UI_ICON_PATH');
    if (iconPath.isNotEmpty) {
      final icons = FontLoader('MaterialIcons')
        ..addFont(
          Future.value(ByteData.sublistView(File(iconPath).readAsBytesSync())),
        );
      await icons.load();
    }
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: RepaintBoundary(
          key: boundary,
          child: PersonalDashboardScreen(
            load: (_) async => {
              'phone': {
                'total_ms': 7200000,
                'apps': [
                  {
                    'name': 'YouTube',
                    'package': 'youtube',
                    'milliseconds': 5400000,
                  },
                  {
                    'name': 'WhatsApp',
                    'package': 'whatsapp',
                    'milliseconds': 1800000,
                  },
                ],
              },
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('2h 0m'), findsOneWidget);
    expect(find.text('WINDOWS'), findsNothing);
    expect(find.text('YouTube'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (const bool.fromEnvironment('CAPTURE_UI')) {
      await tester.runAsync(() async {
        final render =
            boundary.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await render.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        final file = File(
          '../tests/coding_agent_artifacts/evidence/ui/mobile-overview.png',
        );
        await file.parent.create(recursive: true);
        await file.writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    await tester.drag(dayContent(find.byType(ListView)), const Offset(0, -400));
    await tester.pumpAndSettle();
    expect(
      dayContent(find.text('Your Android activity, stored on this phone.')),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('unavailable data is distinct from zero use', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: PersonalDashboardScreen(load: (_) async => {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(dayContent(find.text('—')), findsOneWidget);
    expect(find.text('0 min'), findsNothing);
    expect(
      dayContent(find.widgetWithText(FilledButton, 'Activity')),
      findsOneWidget,
    );
    // Route verification stays offline; Activity displays its unavailable state.
    final wasEnabled = PowerState.enabled.value;
    PowerState.setEnabled(false);
    addTearDown(() => PowerState.setEnabled(wasEnabled));
    await tester.tap(find.text('Activity').hitTestable());
    await tester.pumpAndSettle();
    expect(find.byType(ActivityScreen), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Overview'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
