import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/chat_message_content.dart';

void main() {
  testWidgets('formatted replies stay selectable and code copies verbatim', (
    tester,
  ) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData')
          copied = (call.arguments as Map)['text'] as String;
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    tester.view.physicalSize = const Size(320, 750);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    const code =
        'first line\nsecond line with **literal** markers and a very long value that scrolls';
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: const Scaffold(
          body: SingleChildScrollView(
            padding: EdgeInsets.all(20),
            child: ChatMessageContent(
              text:
                  '## A useful reply\nUse **bold** and `inline code`.\n\n```dart\n$code\n```\n\nDone.',
            ),
          ),
        ),
      ),
    );
    expect(find.text(code), findsOneWidget);
    expect(find.text('Done.', findRichText: true), findsOneWidget);
    expect(find.byType(SelectableText), findsNWidgets(3));
    await tester.tap(find.byTooltip('Copy code'));
    await tester.pump();
    expect(copied, code);
    expect(tester.takeException(), isNull);
  });

  testWidgets('unfinished code and user markdown remain readable', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: const Scaffold(
          body: Column(
            children: [
              ChatMessageContent(text: '```text\nfirst\nsecond'),
              ChatMessageContent(
                text: '**Keep my original text**',
                isUser: true,
              ),
            ],
          ),
        ),
      ),
    );
    expect(find.text('first\nsecond'), findsOneWidget);
    expect(find.text('**Keep my original text**'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
