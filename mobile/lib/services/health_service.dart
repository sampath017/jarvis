import 'package:health/health.dart';
import 'phone_data_window.dart';

/// Reads Health Connect only when the user asks; no background health polling.
class HealthService {
  HealthService({Health? client}) : _health = client ?? Health();
  static final HealthService instance = HealthService();

  final Health _health;
  bool _configured = false;

  Future<void> _configure() async {
    if (_configured) return;
    await _health.configure();
    _configured = true;
  }

  Future<bool> get available async {
    await _configure();
    return _health.isHealthConnectAvailable();
  }

  Future<bool> hasStepsAccess() async {
    if (!await available) return false;
    return await _health.hasPermissions([HealthDataType.STEPS]) ?? false;
  }

  Future<bool> hasSleepAccess() async {
    if (!await available) return false;
    return await _health.hasPermissions([HealthDataType.SLEEP_SESSION]) ??
        false;
  }

  Future<bool> connectSteps() async {
    if (!await available) return false;
    await _health.requestAuthorization([HealthDataType.STEPS]);
    return hasStepsAccess();
  }

  Future<bool> connectSleep() async {
    if (!await available) return false;
    await _health.requestAuthorization([HealthDataType.SLEEP_SESSION]);
    return hasSleepAccess();
  }

  Future<Map<String, dynamic>> readToolRecords(
    Map<String, dynamic> arguments, {
    DateTime? now,
  }) async {
    final metric = arguments['metric'];
    if (metric != 'steps' && metric != 'sleep') {
      throw const FormatException('metric must be steps or sleep.');
    }
    final window = PhoneDataWindow.parse(
      arguments['start_date']?.toString() ?? '',
      arguments['end_date']?.toString() ?? '',
      now: now,
    );
    if (!await available) {
      return {
        'status': 'unavailable',
        'source': 'health_connect',
        'reason': 'not_available',
        'message':
            'Health Connect is unavailable on this phone. Finish Health Connect setup, then retry.',
      };
    }
    final type = metric == 'steps'
        ? HealthDataType.STEPS
        : HealthDataType.SLEEP_SESSION;
    if (await _health.hasPermissions([type]) != true) {
      return {
        'status': 'permission_required',
        'source': 'health_connect',
        'metric': metric,
        'message':
            'Allow ${metric == 'steps' ? 'Steps' : 'Sleep'} in Health Connect → App permissions → Jarvis, then retry. Reading cannot grant permission.',
      };
    }
    final days = <Map<String, dynamic>>[];
    for (final day in window.days) {
      final start = metric == 'steps'
          ? window.midnight(day)
          : window.midnight(day).subtract(const Duration(hours: 6));
      final end = window.capAtNow(
        window.midnight(day).add(Duration(hours: metric == 'steps' ? 24 : 18)),
      );
      final records = await _health.getHealthDataFromTypes(
        types: [type],
        startTime: start,
        endTime: end,
      );
      final row = <String, dynamic>{
        'day': PhoneDataWindow.dayKey(day),
        'start_at': start.toIso8601String(),
        'end_at': end.toIso8601String(),
        'record_count': records.length,
      };
      if (records.isEmpty) {
        days.add({
          ...row,
          'status': 'no_records',
          'message':
              'No shared Health Connect records for this window. This is unknown, not zero.',
        });
        continue;
      }
      if (metric == 'steps') {
        final count = await _health.getTotalStepsInInterval(start, end);
        days.add({
          ...row,
          'status': count == null ? 'unavailable' : 'ok',
          'steps': ?count,
          'sources': records
              .map((record) => record.sourceName)
              .toSet()
              .take(10)
              .toList(),
        });
      } else {
        final sessions = <Map<String, dynamic>>[];
        final seen = <String>{};
        for (final record in records) {
          final from = record.dateFrom.toUtc().isBefore(start)
              ? start
              : record.dateFrom.toUtc();
          final to = record.dateTo.toUtc().isAfter(end)
              ? end
              : record.dateTo.toUtc();
          if (!to.isAfter(from)) continue;
          final key =
              '${from.toIso8601String()}|${to.toIso8601String()}|${record.sourceName}';
          if (!seen.add(key)) continue;
          sessions.add({
            'start_at': from.toIso8601String(),
            'end_at': to.toIso8601String(),
            'duration_ms': to.difference(from).inMilliseconds,
            'source': record.sourceName,
          });
        }
        sessions.sort(
          (a, b) =>
              (a['start_at'] as String).compareTo(b['start_at'] as String),
        );
        var union = 0;
        DateTime? from, to;
        for (final session in sessions) {
          final nextFrom = DateTime.parse(session['start_at']);
          final nextTo = DateTime.parse(session['end_at']);
          if (from == null || to == null) {
            from = nextFrom;
            to = nextTo;
          } else if (!nextFrom.isAfter(to)) {
            if (nextTo.isAfter(to)) to = nextTo;
          } else {
            union += to.difference(from).inMilliseconds;
            from = nextFrom;
            to = nextTo;
          }
        }
        if (from != null && to != null) {
          union += to.difference(from).inMilliseconds;
        }
        final limit = (300 ~/ window.days.length).clamp(1, 100);
        days.add({
          ...row,
          'status': sessions.isEmpty ? 'no_records' : 'ok',
          if (sessions.isNotEmpty) 'recorded_session_ms': union,
          'sessions': sessions.take(limit).toList(),
          'session_count': sessions.length,
          'truncated_sessions': sessions.length > limit,
        });
      }
    }
    final good = days.where((day) => day['status'] == 'ok').length;
    return {
      'status': good == days.length
          ? 'ok'
          : good > 0
          ? 'partial'
          : 'unavailable',
      'source': 'health_connect',
      'metric': metric,
      'timezone': 'Asia/Kolkata',
      'start_date': arguments['start_date'],
      'end_date': PhoneDataWindow.dayKey(window.end),
      'days': days,
      'notes': metric == 'steps'
          ? 'Health Connect aggregated step counts. Do not infer steps from movement duration.'
          : 'Dates label the night ending that day (18:00 previous day to 18:00, capped at now). Overlapping session intervals are counted once. Session duration is not a medical measure of actual sleep.',
    };
  }
}
