import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/sync_coordinator.dart';

void main() {
  test(
    'local saves coalesce into one push without pulling the archive',
    () async {
      final done = Completer<void>();
      final calls = <bool>[];
      final sync = SyncCoordinator((pull) {
        calls.add(pull);
        return done.future;
      });
      final a = sync.run(pullRemote: false);
      final b = sync.run(pullRemote: false);
      expect(calls, [false]);
      done.complete();
      await Future.wait([a, b]);
    },
  );

  test(
    'refresh during push waits and performs exactly one full sync',
    () async {
      final push = Completer<void>();
      final full = Completer<void>();
      final calls = <bool>[];
      final sync = SyncCoordinator((pull) {
        calls.add(pull);
        return pull ? full.future : push.future;
      });
      final a = sync.run(pullRemote: false);
      final b = sync.run();
      final c = sync.run();
      expect(calls, [false]);
      push.complete();
      await a;
      await Future<void>.delayed(Duration.zero);
      expect(calls, [false, true]);
      full.complete();
      await Future.wait([b, c]);
    },
  );

  test('failed sync releases ownership so a later refresh can retry', () async {
    var calls = 0;
    final sync = SyncCoordinator((_) async {
      if (++calls == 1) throw StateError('offline');
    });
    await expectLater(sync.run(pullRemote: false), throwsStateError);
    await sync.run();
    expect(calls, 2);
  });
}
