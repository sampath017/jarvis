import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../utils/ist_time.dart';
import '../theme.dart';

String chatDayKey(DateTime instant) =>
    DateFormat('yyyy-MM-dd').format(IstTime.display(instant));

String chatDayLabel(DateTime instant, {DateTime? now}) {
  final date = IstTime.display(instant);
  final today = IstTime.display(now ?? DateTime.now());
  final days = DateTime.utc(
    today.year,
    today.month,
    today.day,
  ).difference(DateTime.utc(date.year, date.month, date.day)).inDays;
  final full = DateFormat('EEE, d MMM yyyy').format(date);
  return days == 0
      ? 'Today · $full'
      : days == 1
      ? 'Yesterday · $full'
      : full;
}

class ChatDateDivider extends StatelessWidget {
  final DateTime date;
  final DateTime? now;
  final bool compact;
  const ChatDateDivider({
    super.key,
    required this.date,
    this.now,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.symmetric(vertical: compact ? 12 : 20),
    child: Row(
      children: [
        const Expanded(child: Divider(color: AppTheme.border)),
        const SizedBox(width: 8),
        Flexible(
          flex: 4,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: AppTheme.surfaceBright,
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppTheme.border),
            ),
            child: Text(
              chatDayLabel(date, now: now),
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: compact ? 11 : 12,
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
          ),
        ),
        const SizedBox(width: 8),
        const Expanded(child: Divider(color: AppTheme.border)),
      ],
    ),
  );
}
