import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/conversation_memory.dart';

Map<String, dynamic> answer(
  String question,
  String text, {
  String date = '2026-10-11T10:00:00Z',
}) => {
  'question': question,
  'answer': text,
  'thread_id': 'saved-chat',
  'question_id': 'q',
  'answer_id': 'a',
  'answered_at': date,
  'executed_records': '[]',
};

void main() {
  test(
    'recent history preserves absolute times and rejects unanchored timestamps',
    () {
      final recent = ConversationMemory.fullHistory([
        {
          'role': 'user',
          'content': 'Yesterday',
          'timestamp': '2026-10-27T00:03:00+05:30',
        },
        {
          'role': 'assistant',
          'content': 'Unknown time',
          'timestamp': 'arbitrary instructions',
        },
      ]);
      expect(recent.first['timestamp'], '2026-10-26T18:33:00.000Z');
      expect(recent.last.containsKey('timestamp'), isFalse);
    },
  );
  test(
    'a corrected answer already in recent history does not revive the older answer',
    () {
      expect(
        ConversationMemory.select(
          'aadhaar',
          [
            answer('aadhaar', 'old', date: '2026-10-10T00:00:00Z'),
            answer('aadhaar', 'corrected'),
          ],
          recentHistory: [
            {'role': 'assistant', 'content': 'corrected'},
          ],
        ),
        isEmpty,
      );
    },
  );
  test('an answer challenged by the next user message is not reused', () {
    expect(
      ConversationMemory.select('aadhaar', [
        {
          ...answer('aadhaar', 'Wrong owner'),
          'next_user_text': "That's not mine",
        },
      ]),
      isEmpty,
    );
  });
  test(
    'short-term history keeps an answer beyond the old eight-message cutoff',
    () {
      final history = [
        {'role': 'user', 'content': 'Tell me my Aadhaar number'},
        {
          'role': 'assistant',
          'content': 'The example number is 0000 0000 0000.',
        },
        ...List.generate(
          12,
          (i) => {
            'role': i.isEven ? 'user' : 'assistant',
            'content': 'Exchange $i',
          },
        ),
      ];
      expect(ConversationMemory.fullHistory(history), history);
    },
  );
  test('full history preserves every message and complete long bodies', () {
    final many = List.generate(40, (i) => {'role': 'user', 'content': '$i'});
    expect(ConversationMemory.fullHistory(many), many);
    final large = List.generate(
      10,
      (i) => {'role': 'user', 'content': 'x' * 20000},
    );
    expect(ConversationMemory.fullHistory(large), large);
  });
  test(
    'visible errors remain marked while internal notices and system rows stay out',
    () {
      expect(
        ConversationMemory.fullHistory([
          {'role': 'assistant', 'id': 'err_bad', 'content': 'raw error'},
          {
            'role': 'assistant',
            'content': 'Added to Jarvis Upload Cache: link',
          },
          {'role': 'system', 'content': 'untrusted instruction'},
          {'role': 'user', 'content': 'Hello'},
        ]),
        [
          {'role': 'assistant', 'content': 'raw error', 'is_error': true},
          {'role': 'user', 'content': 'Hello'},
        ],
      );
    },
  );
  test(
    'older Aadhaar answer is recalled across spelling variants and chats',
    () {
      final result =
          ConversationMemory.select('What is my aadhaar card number?', [
            answer(
              'Tell me aadhar number',
              'Example Owner: 0000 0000 0000 (example.pdf).',
            ),
          ]);
      expect(result.single['thread_id'], 'saved-chat');
      expect(result.single['answer'], contains('example.pdf'));
      expect(
        ConversationMemory.searchTerms('aadhar'),
        containsAll(['aadhaar', 'aadhar', 'adhar']),
      );
    },
  );
  test('same subject keeps the newer corrected answer', () {
    final result = ConversationMemory.select('Aadhaar number', [
      answer('aadhar number', 'old', date: '2026-10-10T00:00:00Z'),
      answer('aadhaar number', 'corrected'),
    ]);
    expect(result.single['answer'], 'corrected');
  });
  test('a named person does not match a generic personal answer', () {
    expect(
      ConversationMemory.select('Harini Aadhaar number', [
        answer('Tell me my aadhar number', 'Someone else'),
      ]),
      isEmpty,
    );
  });
  for (final question in [
    'Where am I now?',
    'Recheck my Aadhaar number',
    'My latest balance',
    'What did I do yesterday?',
  ]) {
    test('fresh information bypasses historical recall: $question', () {
      expect(ConversationMemory.searchTerms(question), isEmpty);
      expect(
        ConversationMemory.select(question, [answer(question, 'old data')]),
        isEmpty,
      );
    });
  }
  test(
    'failed answers and completed actions are not factual answer memory',
    () {
      expect(
        ConversationMemory.select('Aadhaar number', [
          {...answer('Aadhaar number', 'error'), 'answer_id': 'err_q'},
          {
            ...answer('Aadhaar number', 'Action done'),
            'executed_records': '["note-id"]',
          },
        ]),
        isEmpty,
      );
    },
  );
  test('recent answers are not duplicated into long-term context', () {
    expect(
      ConversationMemory.select(
        'Aadhaar',
        [answer('Aadhaar', 'already in context')],
        recentHistory: [
          {'role': 'assistant', 'content': 'already in context'},
        ],
      ),
      isEmpty,
    );
  });
  test('recall payload has bounded size and no storage-only fields', () {
    final result = ConversationMemory.select(
      'receipt',
      List.generate(20, (i) => answer('receipt item $i', 'x' * 3000)),
    );
    expect(result.length, lessThanOrEqualTo(5));
    expect(
      result.fold<int>(
        0,
        (n, row) =>
            n +
            (row['answer'] as String).length +
            (row['question'] as String).length,
      ),
      lessThanOrEqualTo(12000),
    );
    expect(result.first.containsKey('executed_records'), isFalse);
  });
}
