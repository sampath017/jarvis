/// Full current-chat history and separately bounded recall from saved answers.
class ConversationMemory {
  static final _separator = RegExp(r'[^\p{L}\p{M}\p{N}]+', unicode: true);
  static const _ignored = {
    'a',
    'an',
    'and',
    'are',
    'as',
    'at',
    'be',
    'by',
    'can',
    'could',
    'did',
    'do',
    'does',
    'for',
    'from',
    'give',
    'have',
    'how',
    'in',
    'is',
    'it',
    'me',
    'my',
    'of',
    'on',
    'or',
    'please',
    'show',
    'tell',
    'that',
    'the',
    'this',
    'to',
    'was',
    'were',
    'what',
    'when',
    'where',
    'which',
    'with',
    'would',
    'you',
    'your',
    'number',
    'card',
    'again',
  };
  static final _fresh = RegExp(
    r'\b(today|yesterday|tomorrow|now|current|currently|latest|refresh|recheck|reread|updated)\b|search again|check again|read again',
    caseSensitive: false,
  );
  static final _correction = RegExp(
    r'\b(wrong|incorrect|correction|actually|forget|delete)\b|not (mine|my)|do not remember|don.t remember',
    caseSensitive: false,
  );

  static Set<String> terms(String text) => text
      .toLowerCase()
      .split(_separator)
      .map(
        (word) => const {'aadhar', 'adhar', 'aadhaar', 'adhaar'}.contains(word)
            ? 'aadhaar'
            : word,
      )
      .where((word) => word.length > 1 && !_ignored.contains(word))
      .toSet();

  static List<String> searchTerms(String question) {
    if (_fresh.hasMatch(question)) return [];
    final words = terms(question).take(8).toSet();
    if (words.contains('aadhaar')) words.addAll(['aadhar', 'adhar', 'adhaar']);
    return words.toList();
  }

  static List<Map<String, dynamic>> fullHistory(
    Iterable<Map<String, dynamic>> history,
  ) {
    final selected = <Map<String, dynamic>>[];
    for (final message in history) {
      final content = message['content'];
      if (content is! String ||
          content.trim().isEmpty ||
          !['user', 'assistant'].contains(message['role']) ||
          content.startsWith('Added to Jarvis Upload Cache:')) {
        continue;
      }
      final rawTime = message['timestamp']?.toString() ?? '';
      final timestamp = RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(rawTime)
          ? DateTime.tryParse(rawTime)?.toUtc()
          : null;
      selected.add({
        'role': message['role'],
        'content': content,
        if (message['is_error'] == true ||
            '${message['id'] ?? ''}'.startsWith('err_'))
          'is_error': true,
        if (timestamp != null) 'timestamp': timestamp.toIso8601String(),
      });
    }
    return selected;
  }

  static List<Map<String, dynamic>> select(
    String question,
    List<Map<String, dynamic>> candidates, {
    List<Map<String, dynamic>> recentHistory = const [],
  }) {
    if (_fresh.hasMatch(question)) return [];
    final query = terms(question);
    if (query.isEmpty) return [];
    final ranked = <({Map<String, dynamic> row, int score, DateTime at})>[];
    for (final row in candidates) {
      final prompt = row['question'];
      final answer = row['answer'];
      if (prompt is! String ||
          answer is! String ||
          answer.trim().isEmpty ||
          prompt.length > 2000 ||
          answer.length > 6000 ||
          '${row['answer_id']}'.startsWith('err_') ||
          answer.startsWith('Added to Jarvis Upload Cache:') ||
          (row['executed_records'] != null &&
              row['executed_records'] != '[]') ||
          _correction.hasMatch('${row['next_user_text'] ?? ''}')) {
        continue;
      }
      final overlap = query.intersection(terms(prompt)).length;
      final required = query.length == 1
          ? 1
          : (query.length * 0.6).ceil().clamp(2, 8);
      if (overlap < required) continue;
      ranked.add((
        row: row,
        score: overlap,
        at:
            DateTime.tryParse('${row['answered_at']}') ??
            DateTime.fromMillisecondsSinceEpoch(0),
      ));
    }
    ranked.sort((a, b) {
      final score = b.score.compareTo(a.score);
      return score != 0 ? score : b.at.compareTo(a.at);
    });
    final seen = <String>{};
    final result = <Map<String, dynamic>>[];
    var remaining = 12000;
    for (final entry in ranked) {
      final row = entry.row;
      // Keep the newest answer for equivalent questions, including corrections.
      final key = (terms(row['question'] as String).toList()..sort()).join(' ');
      if (!seen.add(key)) continue;
      if (recentHistory.any(
        (m) => m['role'] == 'assistant' && m['content'] == row['answer'],
      )) {
        continue;
      }
      final size =
          (row['question'] as String).length + (row['answer'] as String).length;
      if (size > remaining) continue;
      result.add({
        for (final key in [
          'question',
          'answer',
          'thread_id',
          'question_id',
          'answer_id',
          'answered_at',
        ])
          key: row[key],
      });
      remaining -= size;
      if (result.length == 5) break;
    }
    return result;
  }
}
