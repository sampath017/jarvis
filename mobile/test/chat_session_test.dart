import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/chat_session.dart';

void main() {
  test(
    'restored messages follow actual time across UTC and local timestamps',
    () {
      final session = ChatSession.fromJson({
        'title': 'Chat',
        'messages': [
          {
            'id': 'reply',
            'text': 'Reply',
            'is_user': false,
            'timestamp': '2026-10-04T10:40:05Z',
          },
          {
            'id': 'question',
            'text': 'Question',
            'is_user': true,
            'timestamp': '2026-10-04T16:10:00+05:30',
          },
        ],
      });

      expect(session.messages.map((m) => m.id), ['question', 'reply']);
      expect(session.copyWith().messages.last.id, 'reply');
    },
  );

  test('equal timestamps keep the question before the reply', () {
    final timestamp = DateTime.utc(2026, 10, 4, 10, 40);
    final input = [
      ChatMessage(
        id: 'reply',
        text: 'Reply',
        isUser: false,
        timestamp: timestamp,
      ),
      ChatMessage(
        id: 'question',
        text: 'Question',
        isUser: true,
        timestamp: timestamp,
      ),
    ];
    final session = ChatSession(
      title: 'Chat',
      createdAt: timestamp,
      updatedAt: timestamp,
      messages: input,
    );

    expect(session.messages.map((m) => m.id), ['question', 'reply']);
    expect(input.first.id, 'reply');
  });

  test(
    'orders restored chats by real activity despite mixed timezone strings',
    () {
      final empty = ChatSession(
        id: 'empty',
        title: 'New Chat',
        createdAt: DateTime.parse('2026-10-03T17:38:34+05:30'),
        updatedAt: DateTime.parse('2026-10-03T17:38:34+05:30'),
        messages: [],
      );
      final latest = ChatSession(
        id: 'latest',
        title: 'Where am I',
        createdAt: DateTime.parse('2026-10-03T07:00:00Z'),
        updatedAt: DateTime.parse('2026-10-03T13:12:52Z'),
        messages: [
          ChatMessage(
            id: 'hi',
            text: 'Hi',
            isUser: true,
            timestamp: DateTime.parse('2026-10-03T18:42:22+05:30'),
          ),
          ChatMessage(
            id: 'reply',
            text: 'Hello!',
            isUser: false,
            timestamp: DateTime.parse('2026-10-03T18:42:27+05:30'),
          ),
        ],
      );
      final sessions = [empty, latest]
        ..sort((a, b) => b.lastActivityAt.compareTo(a.lastActivityAt));
      expect(sessions.first.id, 'latest');
      expect(latest.messages.last.text, 'Hello!');
    },
  );

  test('a recently saved message outranks stale cloud session metadata', () {
    final recent = DateTime.parse('2026-10-03T13:12:27Z');
    final session = ChatSession(
      title: 'Chat',
      createdAt: recent,
      updatedAt: DateTime.parse('2026-10-03T10:00:00Z'),
      messages: [ChatMessage(text: 'Hi', isUser: true, timestamp: recent)],
    );
    expect(session.lastActivityAt, recent);
    expect(session.updatedAt, DateTime.parse('2026-10-03T10:00:00Z'));
  });
}
