import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/notes_workspace.dart';

void main() {
  testWidgets(
    'closing or pressing back saves a draft without a permission prompt',
    (tester) async {
      final saved = <Map<String, dynamic>>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: NotesWorkspace(
            notes: const [],
            trash: const [],
            onSave: (note) async {
              saved.add(note);
            },
            onDelete: (_) async {},
            onRestore: (_) async {},
            onRefresh: () async {},
          ),
        ),
      );
      await tester.tap(find.text('New note'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('note-title')),
        'Close saves this',
      );
      await tester.tap(find.byTooltip('Close'));
      await tester.pumpAndSettle();
      expect(saved.single['title'], 'Close saves this');
      await tester.tap(find.text('New note'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('note-content')),
        'Back saves this',
      );
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(saved.last['content'], 'Back saves this');
      expect(saved.length, 2);
    },
  );
  final note = <String, dynamic>{
    'id': 'one',
    'title': 'Shopping',
    'content': 'Milk and bread',
    'place': 'Market',
    'created_at': '2026-10-01T00:00:00Z',
  };
  Widget app({
    Future<void> Function(Map<String, dynamic>)? save,
    Future<void> Function(String)? delete,
    Future<void> Function(String)? restore,
    bool trash = false,
  }) => MaterialApp(
    theme: AppTheme.darkTheme,
    home: NotesWorkspace(
      notes: trash ? [] : [note],
      trash: trash ? [note] : [],
      onSave: save ?? (_) async {},
      onDelete: delete ?? (_) async {},
      onRestore: restore ?? (_) async {},
      onRefresh: () async {},
    ),
  );

  testWidgets('tapping a titled card opens editor and saves the same ID', (
    tester,
  ) async {
    Map<String, dynamic>? saved;
    await tester.pumpWidget(
      app(
        save: (note) async {
          saved = note;
        },
      ),
    );
    expect(find.text('Shopping'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('note-one')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('note-title')),
      'Groceries',
    );
    await tester.enterText(
      find.byKey(const ValueKey('note-content')),
      'Milk, bread, eggs',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved?['id'], 'one');
    expect(saved?['title'], 'Groceries');
    expect(saved?['content'], 'Milk, bread, eggs');
    expect(saved?['created_at'], note['created_at']);
    expect(find.text('Edit note'), findsNothing);
  });

  testWidgets(
    'delete never runs before confirmation and cancel preserves note',
    (tester) async {
      final deleted = <String>[];
      await tester.pumpWidget(
        app(
          delete: (id) async {
            deleted.add(id);
          },
        ),
      );
      await tester.tap(find.byTooltip('Delete note'));
      await tester.pumpAndSettle();
      expect(deleted, isEmpty);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(deleted, isEmpty);
      await tester.tap(find.byTooltip('Delete note'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Delete note'));
      await tester.pumpAndSettle();
      expect(deleted, ['one']);
    },
  );

  testWidgets('editor deletion also requires confirmation', (tester) async {
    var deleted = false;
    await tester.pumpWidget(
      app(
        delete: (_) async {
          deleted = true;
        },
      ),
    );
    await tester.tap(find.byKey(const ValueKey('note-one')));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Delete note').last);
    await tester.pumpAndSettle();
    expect(deleted, false);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(deleted, false);
    expect(find.text('Edit note'), findsOneWidget);
  });

  testWidgets('save error retains draft and allows retry', (tester) async {
    var attempts = 0;
    await tester.pumpWidget(
      app(
        save: (_) async {
          if (++attempts == 1) throw Exception('disk');
        },
      ),
    );
    await tester.tap(find.text('New note'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('note-title')),
      'A new idea',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(
      find.text('Could not save. Your draft is still here. Try again.'),
      findsOneWidget,
    );
    expect(find.text('A new idea'), findsOneWidget);
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.byKey(const ValueKey('note-title')), findsNothing);
  });

  testWidgets('search and trash restore work on a narrow screen', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(app());
    await tester.enterText(find.byType(TextField), 'no match');
    await tester.pumpAndSettle();
    expect(find.text('No matching notes'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'market');
    await tester.pumpAndSettle();
    expect(find.text('Shopping'), findsOneWidget);
    String? restored;
    await tester.pumpWidget(
      app(
        trash: true,
        restore: (id) async {
          restored = id;
        },
      ),
    );
    await tester.tap(find.text('Trash'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Restore note'));
    await tester.pumpAndSettle();
    expect(restored, 'one');
    expect(tester.takeException(), isNull);
  });
}
