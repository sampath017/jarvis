import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/chat_session.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/chat_date_divider.dart';
import 'package:jarvis_collector/ui/widgets/chat_history_list.dart';
import 'package:jarvis_collector/ui/widgets/chat_archive_confirmation.dart';

void main() {
  testWidgets('long-press options remain scrollable in a short window', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 260);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final date = DateTime.utc(2026, 10, 15);
    final chat = ChatSession(
      id: 'short',
      title: 'A conversation with a long title that wraps onto another line',
      createdAt: date,
      updatedAt: date,
      messages: [],
    );
    var archived = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: Scaffold(
          body: ChatHistoryList(
            sessions: [chat],
            onSelect: (_) {},
            onRename: (_) {},
            onDelete: (_) {},
            onArchive: (_) => archived = true,
          ),
        ),
      ),
    );
    await tester.longPress(find.byKey(const ValueKey('chat-history-short')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.text('Archive'));
    await tester.tap(find.text('Archive'));
    await tester.pumpAndSettle();
    expect(archived, true);
    expect(tester.takeException(), isNull);
  });
  for (final action in ['Rename', 'Archive', 'Delete']) {
    testWidgets(
      'long-press shows $action without dots and dispatches only that action',
      (tester) async {
        final date = DateTime.utc(2026, 10, 15);
        final chat = ChatSession(
          id: 'menu-chat',
          title: 'Selected conversation',
          createdAt: date,
          updatedAt: date,
          messages: [],
          storedMessageCount: 42,
        );
        final calls = <String>[];
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: ChatHistoryList(
                sessions: [chat],
                onSelect: (chat) => calls.add('open:${chat.id}'),
                onRename: (chat) => calls.add('Rename:${chat.id}'),
                onDelete: (chat) => calls.add('Delete:${chat.id}'),
                onArchive: (chat) => calls.add('Archive:${chat.id}'),
              ),
            ),
          ),
        );
        expect(find.byIcon(Icons.more_horiz), findsNothing);
        await tester.tap(find.byKey(const ValueKey('chat-history-menu-chat')));
        expect(calls, ['open:menu-chat']);
        calls.clear();
        await tester.longPress(
          find.byKey(const ValueKey('chat-history-menu-chat')),
        );
        await tester.pumpAndSettle();
        expect(find.text('Rename'), findsOneWidget);
        expect(find.text('Archive'), findsOneWidget);
        expect(find.text('Delete'), findsOneWidget);
        expect(calls, isEmpty);
        await tester.tap(find.text(action));
        await tester.pumpAndSettle();
        expect(calls, ['$action:menu-chat']);
        expect(find.byType(BottomSheet), findsNothing);
      },
    );
  }

  testWidgets(
    'working chat cannot be archived and in-progress archive cannot be repeated',
    (tester) async {
      final date = DateTime.utc(2026, 10, 15);
      final chat = ChatSession(
        id: 'busy',
        title: 'Busy chat',
        createdAt: date,
        updatedAt: date,
        messages: [],
      );
      var calls = 0;
      Widget panel({String? working, String? archiving}) => MaterialApp(
        theme: AppTheme.darkTheme,
        home: Scaffold(
          body: ChatHistoryList(
            sessions: [chat],
            workingId: working,
            archivingId: archiving,
            onSelect: (_) {},
            onRename: (_) {},
            onDelete: (_) {},
            onArchive: (_) => calls++,
          ),
        ),
      );
      await tester.pumpWidget(panel(working: 'busy'));
      await tester.longPress(find.byKey(const ValueKey('chat-history-busy')));
      await tester.pumpAndSettle();
      final archive = find.ancestor(
        of: find.text('Archive'),
        matching: find.byType(ListTile),
      );
      expect(tester.widget<ListTile>(archive).enabled, false);
      await tester.tap(find.text('Archive'));
      await tester.pumpAndSettle();
      expect(calls, 0);
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      await tester.pumpWidget(panel(archiving: 'busy'));
      await tester.longPress(find.byKey(const ValueKey('chat-history-busy')));
      await tester.pumpAndSettle();
      expect(find.byType(BottomSheet), findsNothing);
      expect(find.text('Archiving to Drive…'), findsOneWidget);
      expect(calls, 0);
    },
  );

  testWidgets(
    'archive confirmation explains local organization and respects cancellation',
    (tester) async {
      final date = DateTime.utc(2026, 10, 15);
      final chat = ChatSession(
        id: 'confirm',
        title: 'My chat',
        createdAt: date,
        updatedAt: date,
        messages: [],
        storedMessageCount: 42,
      );
      bool? approved;
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  approved = await confirmChatArchive(context, chat);
                },
                child: const Text('Archive'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Archive'));
      await tester.pumpAndSettle();
      expect(approved, isNull);
      expect(
        find.textContaining(
          'Move this conversation to Archived on this phone.',
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(approved, false);
      await tester.tap(find.text('Archive'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Archive'));
      await tester.pumpAndSettle();
      expect(approved, true);
    },
  );

  test('day grouping distinguishes years and the local midnight boundary', () {
    final now = DateTime.utc(2026, 10, 14, 5);
    expect(
      chatDayLabel(DateTime.utc(2026, 10, 13, 18, 31), now: now),
      'Today · Wed, 14 Oct 2026',
    );
    expect(
      chatDayLabel(DateTime.utc(2026, 10, 13, 18, 29), now: now),
      'Yesterday · Tue, 13 Oct 2026',
    );
    expect(chatDayKey(DateTime.utc(2025, 10, 14)), isNot(chatDayKey(now)));
  });

  testWidgets(
    'archived chats remain accessible from Recents without day headers on a narrow screen',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final date = DateTime.utc(2026, 9, 1);
      ChatSession chat(String id, bool archived) => ChatSession(
        id: id,
        title: id,
        createdAt: date,
        updatedAt: date,
        messages: [],
        storedMessageCount: 42,
        isArchived: archived,
        hasArchive: archived,
      );
      String? selected;
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: ChatHistoryList(
              sessions: [
                chat('Active conversation', false),
                chat('Saved earlier conversation', true),
              ],
              onSelect: (chat) => selected = chat.id,
              onRename: (_) {},
              onDelete: (_) {},
            ),
          ),
        ),
      );
      expect(find.text('Active conversation'), findsOneWidget);
      expect(find.text('Saved earlier conversation'), findsNothing);
      expect(find.text('Start a conversation'), findsNothing);
      await tester.tap(find.text('Archived (1)').last);
      await tester.pumpAndSettle();
      expect(find.text('Saved earlier conversation'), findsOneWidget);
      expect(find.text('Active conversation'), findsNothing);
      expect(find.text('Archived · saved to Drive'), findsOneWidget);
      expect(find.byType(ChatDateDivider), findsNothing);
      await tester.tap(find.text('Saved earlier conversation'));
      expect(selected, 'Saved earlier conversation');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'continued archive moves to Chats and retains its history badge',
    (tester) async {
      final date = DateTime.utc(2026, 9, 1);
      ChatSession session(bool archived) => ChatSession(
        id: 'continued',
        title: 'Continued conversation',
        createdAt: date,
        updatedAt: date,
        messages: [],
        storedMessageCount: archived ? 42 : 43,
        isArchived: archived,
        hasArchive: true,
      );
      Widget panel(bool archived) => MaterialApp(
        theme: AppTheme.darkTheme,
        home: Scaffold(
          body: ChatHistoryList(
            sessions: [session(archived)],
            onSelect: (_) {},
            onRename: (_) {},
            onDelete: (_) {},
          ),
        ),
      );
      await tester.pumpWidget(panel(true));
      await tester.tap(find.text('Archived (1)').last);
      await tester.pumpAndSettle();
      final rowIcon = tester.widget<Icon>(
        find.descendant(
          of: find.byType(ListTile),
          matching: find.byIcon(Icons.archive_outlined),
        ),
      );
      expect(rowIcon.color, AppTheme.amber);
      await tester.pumpWidget(panel(false));
      expect(find.text('Archived (0)'), findsOneWidget);
      expect(find.text('No archived chats yet'), findsOneWidget);
      await tester.tap(find.text('Recents').last);
      await tester.pumpAndSettle();
      expect(find.text('Continued conversation'), findsOneWidget);
      expect(find.text('Includes archived history'), findsOneWidget);
      expect(find.text('Archived · saved to Drive'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Recents is a simple title list sorted newest first across days',
    (tester) async {
      ChatSession session(String title, DateTime date) => ChatSession(
        id: title,
        title: title,
        createdAt: date,
        updatedAt: date,
        messages: [],
        storedMessageCount: 3,
      );
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: ChatHistoryList(
              sessions: [
                session('Older day', DateTime.utc(2025, 9, 1, 3)),
                session('Same day earlier', DateTime.utc(2025, 9, 2, 3)),
                session('Newest conversation', DateTime.utc(2025, 9, 2, 4)),
              ],
              onSelect: (_) {},
              onRename: (_) {},
              onDelete: (_) {},
            ),
          ),
        ),
      );
      expect(find.text('Recents'), findsOneWidget);
      expect(find.byType(ChatDateDivider), findsNothing);
      expect(find.textContaining('messages ·'), findsNothing);
      expect(find.byIcon(Icons.chat_bubble_outline_rounded), findsNothing);
      expect(
        tester.getTopLeft(find.text('Newest conversation')).dy,
        lessThan(tester.getTopLeft(find.text('Same day earlier')).dy),
      );
      expect(
        tester.getTopLeft(find.text('Same day earlier')).dy,
        lessThan(tester.getTopLeft(find.text('Older day')).dy),
      );
      expect(tester.takeException(), isNull);
    },
  );
}
