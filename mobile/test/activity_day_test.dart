import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/activity_day.dart';

void main() {
  test(
    'keeps sampled events in their journey and rejects invalid map points',
    () {
      final day = ActivityDay.fromJson({
        'truncated': false,
        'gap_count': 1,
        'observations': [
          {
            'timestamp': '2026-09-29T08:00:00+00:00',
            'activity': 'IN_VEHICLE',
            'session_id': 'trip-1',
            'gps': {'latitude': 12.9, 'longitude': 77.6},
          },
          {
            'timestamp': '2026-09-29T08:30:00+00:00',
            'activity': 'WALKING',
            'gps': {'latitude': 999, 'longitude': 77.6},
          },
          {'timestamp': '2026-09-29T10:00:00+00:00', 'activity': 'STILL'},
        ],
        'timeline': [
          {
            'first_observed_at': '2026-09-29T08:00:00+00:00',
            'last_observed_at': '2026-09-29T08:00:00+00:00',
            'activity': 'IN_VEHICLE',
            'session_id': 'trip-1',
          },
          {
            'first_observed_at': '2026-09-29T08:30:00+00:00',
            'last_observed_at': '2026-09-29T08:30:00+00:00',
            'activity': 'WALKING',
          },
          {
            'first_observed_at': '2026-09-29T10:00:00+00:00',
            'last_observed_at': '2026-09-29T10:00:00+00:00',
            'activity': 'STILL',
          },
        ],
        'sessions': [
          {
            'session_id': 'trip-1',
            'started_at': '2026-09-29T07:55:00+00:00',
            'last_updated': '2026-09-29T08:05:00+00:00',
            'status': 'PAUSED',
          },
        ],
      });

      expect(day.groups.length, 3);
      expect(day.observationsFor('trip-1').length, 1);
      expect(day.observationsFor(day.groups[1].key).length, 1);
      expect(day.observationsFor(day.groups[2].key).length, 1);
      expect(day.observations.first.hasLocation, true);
      expect(day.observations[1].hasLocation, false);
      expect(day.gapCount, 1);
    },
  );
}
