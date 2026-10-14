import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/widgets/database_backup_settings.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'weekly backup can be disabled and queued, with truthful completion status',
    (tester) async {
      const channel = MethodChannel('com.jarvis/database_backup');
      var enabled = true;
      var queued = false;
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'configure') enabled = call.arguments as bool;
        if (call.method == 'backupNow') queued = true;
        return {
          'enabled': enabled,
          'connected': true,
          'lastSuccess': 0,
          'state': queued ? 'queued' : 'scheduled',
        };
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: DatabaseBackupSettings())),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('jarvis_db_backup.db'), findsOneWidget);
      expect(find.textContaining('No completed backup yet'), findsOneWidget);
      await tester.tap(find.text('Back up now'));
      await tester.pumpAndSettle();
      expect(queued, true);
      expect(find.textContaining('Waiting for network'), findsOneWidget);
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(enabled, false);
      expect(
        tester
            .widget<TextButton>(find.widgetWithText(TextButton, 'Back up now'))
            .onPressed,
        isNull,
      );
    },
  );
}
