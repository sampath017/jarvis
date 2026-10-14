import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/command_client.dart';
import 'package:jarvis_collector/ui/widgets/chat_progress_bubble.dart';
import 'package:jarvis_collector/ui/theme.dart';

void main() {
  testWidgets('one readable bubble updates steps with no spinner', (
    tester,
  ) async {
    var stopped = false;
    Widget view(CommandProgress progress) => MaterialApp(
      theme: AppTheme.darkTheme,
      home: Scaffold(
        body: Center(
          child: SizedBox(
            width: 320,
            child: ChatProgressBubble(
              progress: progress,
              onStop: () => stopped = true,
            ),
          ),
        ),
      ),
    );
    await tester.pumpWidget(
      view(const CommandProgress(message: 'Checking your reminders')),
    );
    await tester.pump(const Duration(seconds: 80));
    expect(find.text('1m 20s'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    await tester.pumpWidget(
      view(
        const CommandProgress(
          message: 'Saving your reminder',
          steps: ['Reading your request', 'Checking your reminders'],
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(ChatProgressBubble), findsOneWidget);
    expect(find.text('Saving your reminder'), findsOneWidget);
    await tester.tap(find.text('Stop'));
    expect(stopped, isTrue);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
