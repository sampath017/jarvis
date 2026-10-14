/// Calendar-date boundaries shared by typed phone data tools. No NLP routing.
class PhoneDataWindow {
  PhoneDataWindow._(this.start, this.end, this.now);
  static const offset = Duration(hours: 5, minutes: 30);
  final DateTime start, end, now;

  static String dayKey(DateTime day) => day.toIso8601String().substring(0, 10);

  factory PhoneDataWindow.parse(
    String startDate,
    String endDate, {
    DateTime? now,
  }) {
    DateTime parse(String value) {
      if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
        throw const FormatException('Use YYYY-MM-DD dates.');
      }
      final parsed = DateTime.tryParse('${value}T00:00:00Z');
      if (parsed == null || dayKey(parsed) != value) {
        throw const FormatException('Invalid calendar date.');
      }
      return parsed;
    }

    final instant = (now ?? DateTime.now()).toUtc();
    final local = instant.add(offset);
    final today = DateTime.utc(local.year, local.month, local.day);
    final start = parse(startDate),
        end = parse(endDate.isEmpty ? startDate : endDate);
    if (end.isBefore(start) ||
        end.difference(start).inDays >= 31 ||
        end.isAfter(today)) {
      throw const FormatException(
        'Choose 1 to 31 days ending no later than today in Asia/Kolkata.',
      );
    }
    return PhoneDataWindow._(start, end, instant);
  }

  List<DateTime> get days => List.generate(
    end.difference(start).inDays + 1,
    (i) => start.add(Duration(days: i)),
  );
  DateTime midnight(DateTime day) => day.subtract(offset);
  DateTime capAtNow(DateTime value) => value.isAfter(now) ? now : value;
}
