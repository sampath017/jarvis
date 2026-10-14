import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/api_service.dart';
import 'package:jarvis_collector/services/sensor_service.dart';
import 'package:jarvis_collector/ui/screens/main_navigation_screen.dart';
import 'package:jarvis_collector/ui/screens/apps_screen.dart';
import 'package:jarvis_collector/ui/screens/settings_screen.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  testWidgets('workspace adapts to phone, keyboard, and desktop layouts', (
    tester,
  ) async {
    // Keep layout verification isolated from device storage and permissions.
    databaseFactory = databaseFactorySqflitePlugin;
    addTearDown(
      () => ApiService().didChangeAppLifecycleState(AppLifecycleState.paused),
    );
    const fontPath = String.fromEnvironment('UI_FONT_PATH');
    if (fontPath.isNotEmpty) {
      final loader = FontLoader('Roboto');
      final fonts = File(fontPath).parent;
      for (final name in [
        'roboto-regular.ttf',
        'roboto-medium.ttf',
        'roboto-bold.ttf',
      ]) {
        loader.addFont(
          Future.value(
            ByteData.sublistView(File('${fonts.path}/$name').readAsBytesSync()),
          ),
        );
      }
      await loader.load();
      final icons = FontLoader('MaterialIcons');
      icons.addFont(
        Future.value(
          ByteData.sublistView(
            File('${fonts.path}/materialicons-regular.otf').readAsBytesSync(),
          ),
        ),
      );
      await icons.load();
    }
    final databaseReady = Completer<void>();
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('com.tekartik.sqflite'),
      (call) async {
        switch (call.method) {
          case 'getDatabasesPath':
            await databaseReady.future;
            return Directory.systemTemp.path;
          case 'openDatabase':
            return {'id': 1};
          case 'query':
            final sql = (call.arguments as Map)['sql'] as String;
            if (sql.contains('PRAGMA user_version')) {
              return [
                {'user_version': 7},
              ];
            }
            if (sql.contains('FROM chat_sessions') ||
                sql.contains('FROM "chat_sessions"')) {
              return [
                {
                  'id': 'layout-preview',
                  'title': 'New Chat',
                  'created_at': '2026-10-04T09:00:00',
                  'updated_at': '2026-10-04T09:00:00',
                },
              ];
            }
            if (sql.contains('COUNT(')) {
              return [
                {'count': 0},
              ];
            }
            return <Map<String, Object?>>[];
          case 'execute':
          case 'closeDatabase':
            return null;
          default:
            return null;
        }
      },
    );
    final boundaryKey = GlobalKey();
    final sensors = SensorService();
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: RepaintBoundary(
          key: boundaryKey,
          child: MainNavigationScreen(sensorService: sensors),
        ),
      ),
    );
    // A slow database must not prevent the app shell from being drawn.
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.text('Loading recent chats…'), findsOneWidget);
    expect(find.byType(AppsScreen, skipOffstage: false), findsNothing);
    expect(find.byType(SettingsScreen, skipOffstage: false), findsNothing);
    databaseReady.complete();
    // Chat checks for an older on-disk history file during its initial load.
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 100)),
    );
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.text('How can I help today?'), findsOneWidget);
    expect(tester.takeException(), isNull);

    // Keystrokes and IME composition should update the composer, not rebuild
    // the conversation (whose cost grows with its history).
    final composer = find.byType(TextField).last;
    await tester.showKeyboard(composer);
    await tester.pumpAndSettle();
    final appBarBeforeTyping = tester.widget<AppBar>(find.byType(AppBar).first);
    final send = find.widgetWithIcon(IconButton, Icons.arrow_upward_rounded);
    expect(tester.widget<IconButton>(send).onPressed, isNull);
    await tester.enterText(
      composer,
      'A draft typed without rebuilding history',
    );
    await tester.pump();
    expect(tester.widget<IconButton>(send).onPressed, isNotNull);
    expect(
      identical(
        appBarBeforeTyping,
        tester.widget<AppBar>(find.byType(AppBar).first),
      ),
      isTrue,
    );
    tester
        .widget<TextField>(composer)
        .controller!
        .value = const TextEditingValue(
      text: 'A draft',
      selection: TextSelection.collapsed(offset: 7),
      composing: TextRange(start: 2, end: 7),
    );
    await tester.pump();
    expect(
      identical(
        appBarBeforeTyping,
        tester.widget<AppBar>(find.byType(AppBar).first),
      ),
      isTrue,
    );
    await tester.enterText(composer, '   ');
    await tester.pump();
    expect(tester.widget<IconButton>(send).onPressed, isNull);
    await tester.enterText(composer, '');
    await tester.pump();

    Future<void> capture(String name) async {
      if (!const bool.fromEnvironment('CAPTURE_UI')) return;
      await tester.runAsync(() async {
        final boundary =
            boundaryKey.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await boundary.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        final file = File(
          '../tests/coding_agent_artifacts/evidence/ui/$name.png',
        );
        await file.parent.create(recursive: true);
        await file.writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }

    await capture('chat-phone');
    await tester.tap(find.text('Set a reminder'));
    await tester.pumpAndSettle();
    final input = tester.widget<TextField>(find.byType(TextField).last);
    expect(input.controller!.text, 'Remind me to ');
    expect(input.focusNode!.hasFocus, isTrue);

    tester.view.physicalSize = const Size(320, 640);
    tester.view.viewInsets = const FakeViewPadding(bottom: 280);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byTooltip('Send message').hitTestable(), findsOneWidget);
    tester.view.resetViewInsets();
    FocusManager.instance.primaryFocus?.unfocus();
    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Apps').last);
    await tester.pumpAndSettle();
    expect(find.text('Your everyday tools'), findsOneWidget);
    await tester.tap(find.text('Notes').last);
    await tester.pumpAndSettle();
    expect(find.text('Capture a thought'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await capture('notes-phone');

    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Reminders').last);
    await tester.pumpAndSettle();
    expect(find.text('No reminders yet'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await capture('reminders-phone');
    await tester.pageBack();
    await tester.pumpAndSettle();

    tester.view.physicalSize = const Size(900, 800);
    await tester.pumpAndSettle();
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    expect(tester.takeException(), isNull);
    tester.view.physicalSize = const Size(900, 360);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    tester.view.physicalSize = const Size(1280, 900);
    await tester.pumpAndSettle();
    expect(
      tester.widget<NavigationRail>(find.byType(NavigationRail)).extended,
      isTrue,
    );
    await tester.tap(find.text('Chat').last);
    await tester.pumpAndSettle();
    expect(find.text('How can I help today?'), findsOneWidget);
    expect(
      tester.widget<TextField>(find.byType(TextField).last).controller!.text,
      'Remind me to ',
    );
    expect(tester.takeException(), isNull);
    await capture('chat-desktop');

    // History docks on desktop and can be hidden without losing the draft.
    expect(find.text('Conversations'), findsOneWidget);
    await tester.enterText(
      find.byType(TextField).first,
      'missing conversation',
    );
    await tester.pump(const Duration(milliseconds: 250));
    await tester.tap(find.byTooltip('Conversation history'));
    await tester.pumpAndSettle();
    expect(find.text('Conversations'), findsNothing);
    expect(
      tester.widget<TextField>(find.byType(TextField).last).controller!.text,
      'Remind me to ',
    );
    await tester.tap(find.byTooltip('Conversation history'));
    await tester.pumpAndSettle();
    expect(find.text('Conversations'), findsOneWidget);
    expect(
      tester.widget<TextField>(find.byType(TextField).first).controller!.text,
      'missing conversation',
    );
    await tester.enterText(find.byType(TextField).first, '');
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    tester.view.physicalSize = const Size(320, 640);
    tester.platformDispatcher.textScaleFactorTestValue = 1.6;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byTooltip('Send message').hitTestable(), findsOneWidget);
    await capture('chat-accessible');

    await tester.pumpWidget(const SizedBox.shrink());
    ApiService().didChangeAppLifecycleState(AppLifecycleState.paused);
    sensors.dispose();
    await tester.pumpAndSettle();
  });
}
