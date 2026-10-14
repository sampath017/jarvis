import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/activity_history_service.dart';

void main() {
  test(
    'empty API cache retains saved activity; changed observations replace by ID',
    () {
      final saved = <String, dynamic>{
        'observations': [
          {'event_id': 'old', 'activity': 'WALKING'},
          {'event_id': 'updated', 'activity': 'UNKNOWN'},
        ],
        'sessions': [
          {'session_id': 'journey', 'status': 'ACTIVE'},
        ],
        'micromoments': [
          {'moment_id': 'one', 'session_id': 'journey'},
          {'moment_id': 'two', 'session_id': 'journey'},
        ],
      };
      expect(
        mergeActivityHistory(saved, {'observations': [], 'sessions': []}),
        saved,
      );
      final merged = mergeActivityHistory(saved, {
        'observations': [
          {'event_id': 'updated', 'activity': 'STILL'},
          {'event_id': 'new', 'activity': 'WALKING'},
        ],
        'sessions': [
          {'session_id': 'journey', 'status': 'COMPLETED'},
        ],
      });
      expect((merged['observations'] as List).length, 3);
      expect((merged['observations'] as List)[1]['activity'], 'STILL');
      expect((merged['sessions'] as List).single['status'], 'COMPLETED');
      expect((merged['micromoments'] as List).length, 2);
    },
  );
}
