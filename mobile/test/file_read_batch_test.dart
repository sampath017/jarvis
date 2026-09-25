import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/file_read_batch.dart';

void main() {
  test(
    'independent file reads overlap and preserve their call identities',
    () async {
      final first = Completer<Map<String, dynamic>>();
      final second = Completer<Map<String, dynamic>>();
      final started = <String>[];
      final result = runFileReadBatch(
        [
          {'call_id': 'a', 'operation': 'file_analyze'},
          {'call_id': 'b', 'operation': 'file_analyze'},
        ],
        (action) {
          started.add(action['call_id']);
          return action['call_id'] == 'a' ? first.future : second.future;
        },
      );
      expect(started, ['a', 'b']);
      second.complete({'answer': 'second'});
      first.complete({'answer': 'first'});
      expect((await result).map((entry) => entry['call_id']), ['a', 'b']);
    },
  );
  test('writes cannot enter a read batch', () async {
    var invoked = false;
    await expectLater(
      runFileReadBatch(
        [
          {'call_id': 'a', 'operation': 'file_save'},
        ],
        (action) async {
          invoked = true;
          return {};
        },
      ),
      throwsArgumentError,
    );
    expect(invoked, isFalse);
  });
}
