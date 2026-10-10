import 'package:health/health.dart';
import 'package:intl/intl.dart';

/// Reads Health Connect only when the user asks; no background health polling.
class HealthService {
  HealthService._();
  static final HealthService instance = HealthService._();

  final Health _health = Health();
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

  static bool isHealthQuestion(String text) {
    final q = text.toLowerCase();
    if (RegExp(
      r'\b(remind|reminder|note|save|record|alarm|wake|call)\b',
    ).hasMatch(q)) {
      return false;
    }
    return RegExp(r'\b(steps?|step count|sleep|slept)\b').hasMatch(q) &&
        RegExp(
          r'\b(how|many|much|did|do|today|yesterday|last night|show|tell|count|total)\b',
        ).hasMatch(q);
  }

  Future<String> answer(String question) async {
    try {
      final q = question.toLowerCase();
      if (!await available) {
        return 'Health Connect is unavailable on this phone. Open Health Connect to finish its setup, then try again.';
      }
      if (RegExp(r'\b(steps?|step count)\b').hasMatch(q)) {
        if (RegExp(
          r'\b(week|month|days|ago|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        ).hasMatch(q)) {
          return 'I can check steps for today or yesterday. Which day do you mean?';
        }
        if (!await hasStepsAccess()) {
          return 'I need read access to steps. Open Health Connect → App permissions → Jarvis, allow steps, then ask me again.';
        }
        final now = DateTime.now();
        final day = q.contains('yesterday')
            ? now.subtract(const Duration(days: 1))
            : now;
        final start = DateTime(day.year, day.month, day.day);
        final end = q.contains('yesterday')
            ? start.add(const Duration(days: 1))
            : now;
        final records = await _health.getHealthDataFromTypes(
          types: [HealthDataType.STEPS],
          startTime: start,
          endTime: end,
        );
        if (records.isEmpty) {
          return 'Health Connect has no step records for ${q.contains('yesterday') ? 'yesterday' : 'today'}. Check that Google Fit or your tracking app is sharing steps with Health Connect.';
        }
        final count = await _health.getTotalStepsInInterval(start, end);
        if (count == null) {
          return 'Health Connect could not read your steps right now. Please try again.';
        }
        final label = q.contains('yesterday') ? 'yesterday' : 'today';
        return 'Health Connect shows ${NumberFormat.decimalPattern().format(count)} steps $label.';
      }
      if (!await hasSleepAccess() && !await connectSleep()) {
        return 'Sleep read access is not granted. In Health Connect → App permissions → Jarvis, allow Sleep (or use Settings → Sleep records in Jarvis). Your sleep app or watch also needs to share sleep sessions with Health Connect; phone inactivity alone cannot measure sleep.';
      }
      if (RegExp(r'\b(week|month|days|ago)\b').hasMatch(q)) {
        return 'I can check your most recent sleep session. Ask me about last night.';
      }
      final now = DateTime.now();
      final yesterday = now.subtract(const Duration(days: 1));
      final start = DateTime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        18,
      );
      final end = now;
      final sessions = await _health.getHealthDataFromTypes(
        types: [HealthDataType.SLEEP_SESSION],
        startTime: start,
        endTime: end,
      );
      if (sessions.isEmpty) {
        return 'Health Connect has no sleep session for last night. Check that your sleep app or watch is sharing sleep data there.';
      }
      sessions.sort(
        (a, b) => b.dateTo
            .difference(b.dateFrom)
            .compareTo(a.dateTo.difference(a.dateFrom)),
      );
      final session = sessions.first;
      final duration = session.dateTo.difference(session.dateFrom);
      final hours = duration.inHours;
      final minutes = duration.inMinutes.remainder(60);
      final time = DateFormat.jm();
      return 'Health Connect recorded a sleep session of ${hours}h ${minutes}m, from ${time.format(session.dateFrom)} to ${time.format(session.dateTo)}. This is session time, not a medical measure of time asleep.';
    } catch (_) {
      return 'I could not read Health Connect right now. Check Jarvis access in Health Connect, then try again.';
    }
  }
}
