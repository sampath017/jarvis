import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/action_approval_dialog.dart';

void main() {
  testWidgets(
    'approval preview discloses guests, recurring scope and only approves on tap',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      bool? result;
      final preview = {
        'operation': 'delete',
        'calendar': 'Work',
        'whole_series': true,
        'guests': ['guest@example.com'],
        'before': {
          'summary': 'Weekly planning',
          'start': {'dateTime': '2026-10-05T10:00:00+05:30'},
          'end': {'dateTime': '2026-10-05T11:00:00+05:30'},
          'recurrence': ['RRULE:FREQ=WEEKLY'],
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  result = await showActionApproval(context, preview);
                },
                child: const Text('Preview'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Preview'));
      await tester.pumpAndSettle();
      expect(result, isNull);
      expect(tester.takeException(), isNull);
      expect(
        find.text('This affects the entire recurring series.'),
        findsOneWidget,
      );
      expect(
        find.text('Cancellation notices will be sent to guests:'),
        findsOneWidget,
      );
      await tester.tap(find.text('Decline'));
      await tester.pumpAndSettle();
      expect(result, false);
      result = null;
      await tester.tap(find.text('Preview'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete event'));
      await tester.pumpAndSettle();
      expect(result, true);
    },
  );
}
