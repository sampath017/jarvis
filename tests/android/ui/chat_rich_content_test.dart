import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/chat_chart.dart';
import 'package:jarvis_collector/ui/widgets/chat_message_content.dart';

Map<String, dynamic> chart([String type = 'bar']) => {
  'type': type,
  'title': 'Sample walking log',
  'unit': 'minutes',
  'labels': ['Mon', 'Tue', 'Wed'],
  'series': [
    {
      'name': 'Walking',
      'values': [20, 35, 25],
    },
  ],
};

Widget page(Widget child) => MaterialApp(
  theme: AppTheme.darkTheme,
  home: Scaffold(
    body: SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: child,
    ),
  ),
);

void main() {
  test(
    'chart data rejects malformed, nonfinite, oversized and inconsistent values',
    () {
      for (final source in [
        'not json',
        '[]',
        '{}',
        jsonEncode({...chart(), 'type': 'javascript'}),
        jsonEncode({
          ...chart(),
          'series': [
            {
              'name': 'Walking',
              'values': [20, 35],
            },
          ],
        }),
        jsonEncode({
          ...chart(),
          'series': [
            {
              'name': 'Walking',
              'values': [1, 'bad', 3],
            },
          ],
        }),
        jsonEncode({...chart(), 'labels': List.filled(25, 'Day')}),
        jsonEncode({
          ...chart('pie'),
          'series': [
            {
              'name': 'Walking',
              'values': [-1, 2, 3],
            },
          ],
        }),
        jsonEncode({
          ...chart('pie'),
          'series': [
            {
              'name': 'Walking',
              'values': [0, 0, 0],
            },
          ],
        }),
        '{"type":"bar","title":"x","labels":["x"],"series":[{"name":"x","values":[1e999]}]}',
      ]) {
        expect(ChatChartData.tryParse(source), isNull, reason: source);
      }
    },
  );

  testWidgets('comparison tables scroll at phone width and links open on tap', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Uri? opened;
    await tester.pumpWidget(
      page(
        ChatMessageContent(
          onOpenLink: (uri) async => opened = uri,
          text:
              '## Laptop comparison\n\n| Model | Price | Source |\n|---|---:|---|\n'
              '| Laptop A | ₹34,400 | [Seller A](https://example.com/a) |\n'
              '| Laptop B | ₹69,990 | [Seller B](https://example.com/b) |\n\n'
              '• First point\n• Second point\n\n[Read details](https://example.com/details)',
        ),
      ),
    );
    expect(find.byType(MarkdownBody), findsOneWidget);
    expect(find.byType(Table), findsOneWidget);
    expect(find.text('₹34,400', findRichText: true), findsWidgets);
    await tester.tap(find.text('Read details', findRichText: true));
    await tester.pump();
    expect(opened, Uri.parse('https://example.com/details'));
    final horizontal = find.byWidgetPredicate(
      (w) => w is SingleChildScrollView && w.scrollDirection == Axis.horizontal,
    );
    expect(horizontal, findsOneWidget);
    await tester.drag(horizontal, const Offset(-220, 0));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'nonweb links and remote images never launch or load automatically',
    (tester) async {
      final opened = <Uri>[];
      await tester.pumpWidget(
        page(
          ChatMessageContent(
            onOpenLink: (uri) async => opened.add(uri),
            text:
                '[Bad link](javascript:alert)\n\n![Tracking image](https://example.com/pixel.png)',
          ),
        ),
      );
      expect(find.byType(Image), findsNothing);
      expect(opened, isEmpty);
      await tester.tap(find.text('Bad link', findRichText: true));
      await tester.pump();
      expect(opened, isEmpty);
      expect(find.text("This link couldn't be opened."), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  for (final type in ['bar', 'line', 'pie']) {
    testWidgets('$type chart renders and reveals exact accessible data', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        page(
          ChatMessageContent(
            text:
                'These are sample values.\n\n```chart\n${jsonEncode(chart(type))}\n```\n\nA short explanation.',
          ),
        ),
      );
      expect(find.byType(ChatChart), findsOneWidget);
      expect(
        find.byType(
          type == 'bar'
              ? BarChart
              : type == 'line'
              ? LineChart
              : PieChart,
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('View data'));
      await tester.pumpAndSettle();
      expect(find.byType(DataTable), findsOneWidget);
      expect(
        find.descendant(of: find.byType(DataTable), matching: find.text('35')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'invalid chart stays readable instead of crashing or inventing a graph',
    (tester) async {
      await tester.pumpWidget(
        page(const ChatMessageContent(text: '```chart\n{"bad":"data"}\n```')),
      );
      expect(find.byType(ChatChart), findsNothing);
      expect(find.text('{"bad":"data"}'), findsOneWidget);
      expect(find.byTooltip('Copy code'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('rich chat visual preview at phone width', (tester) async {
    final fontPath = Platform.environment['JARVIS_CHAT_PREVIEW_FONT'];
    if (fontPath != null) {
      final loader = FontLoader('Roboto')
        ..addFont(
          Future.value(ByteData.sublistView(File(fontPath).readAsBytesSync())),
        );
      await tester.runAsync(loader.load);
    }
    tester.view.physicalSize = const Size(390, 1300);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      page(
        RepaintBoundary(
          key: const Key('preview'),
          child: ColoredBox(
            color: AppTheme.background,
            child: ChatMessageContent(
              text:
                  '## A clearer answer\n\nA short introduction with **important details** and a [source link](https://example.com).\n\n'
                  '### Compare the options\n\n| Option | Rate | Best for |\n|---|---:|---|\n'
                  '| Sample A | ₹34,400 | Everyday use |\n| Sample B | ₹69,990 | Heavier work |\n\n'
                  '- Easy-to-scan lists\n- Swipe wide tables to see more columns\n\n'
                  '```chart\n${jsonEncode(chart())}\n```\n\n'
                  '> Sample data for this preview. Real answers chart only verified numbers.',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final output = Platform.environment['JARVIS_CHAT_PREVIEW'];
    if (output != null) {
      final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byKey(const Key('preview')),
      );
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await File(output).writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
  });
}
