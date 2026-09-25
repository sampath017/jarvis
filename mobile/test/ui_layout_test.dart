import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/api_service.dart';
import 'package:jarvis_collector/services/sensor_service.dart';
import 'package:jarvis_collector/ui/screens/main_navigation_screen.dart';
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
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('com.tekartik.sqflite'),
      (call) async {
        switch (call.method) {
          case 'getDatabasesPath':
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
    // Chat checks for an older on-disk history file during its initial load.
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 100)),
    );
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.text('How can I help today?'), findsOneWidget);
    expect(tester.takeException(), isNull);

    Future<void> capture(String name) async {
      if (!const bool.fromEnvironment('CAPTURE_UI')) return;
      await tester.runAsync(() async {
        final boundary =
            boundaryKey.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await boundary.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        final file = File('build/ui-preview/$name.png');
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
    await tester.tap(find.text('Notes').last);
    await tester.pumpAndSettle();
    expect(find.text('No notes yet'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await capture('notes-phone');

    await tester.tap(find.text('Reminders').last);
    await tester.pumpAndSettle();
    expect(find.text('No reminders yet'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await capture('reminders-phone');

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

    await tester.pumpWidget(const SizedBox.shrink());
    ApiService().didChangeAppLifecycleState(AppLifecycleState.paused);
    sensors.dispose();
    await tester.pumpAndSettle();
  });
}
