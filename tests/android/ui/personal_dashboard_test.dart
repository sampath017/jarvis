import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/screens/personal_dashboard_screen.dart';
import 'package:jarvis_collector/ui/screens/activity_screen.dart';
import 'package:jarvis_collector/services/power_state.dart';
import 'package:jarvis_collector/ui/theme.dart';

void main() {
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
    await tester.drag(find.byType(ListView), const Offset(0, -400));
    await tester.pumpAndSettle();
    expect(
      find.text('Your Android activity, stored on this phone.'),
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
    expect(find.text('—'), findsOneWidget);
    expect(find.text('0 min'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Activity'), findsOneWidget);
    // Route verification stays offline; Activity displays its unavailable state.
    final wasEnabled = PowerState.enabled.value;
    PowerState.setEnabled(false);
    addTearDown(() => PowerState.setEnabled(wasEnabled));
    await tester.tap(find.text('Activity'));
    await tester.pumpAndSettle();
    expect(find.byType(ActivityScreen), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Overview'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
