import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';

class UsageService {
  static const channel = MethodChannel('com.jarvis/usage');
  static final openReport = ValueNotifier<String?>(null);
  static Future<void> initialize() async {
    channel.setMethodCallHandler((call) async {
      if (call.method == 'openReport') {
        openReport.value = null;
        openReport.value = call.arguments as String?;
      }
    });
    try {
      openReport.value = await channel.invokeMethod<String>('takeInitialDay');
    } catch (_) {}
  }

  static bool isUsageQuestion(String text) {
    final q = text.toLowerCase();
    if (RegExp(r'\b(remind|reminder|delete|save|note)\b').hasMatch(q)) {
      return false;
    }
    if (RegExp(
      r'^(?:(?:show|give|send) )?(?:me )?(?:my |the )?(?:daily )?report[?.!]*$',
    ).hasMatch(q.trim())) {
      return true;
    }
    return RegExp(
      r'digital\s*well\s*being|digital\s*wellbeing|(?:daily|today|day).*(?:total|report)|(?:total|report).*(?:daily|today|day)|screen\s*time|app\s*(usage|time)|\busage\b|time (?:did i |have i )?(?:spend|spent)|how (?:much|long).*(?:use|used| on )',
    ).hasMatch(q);
  }

  static String duration(num ms) {
    final minutes = ms ~/ 60000;
    if (minutes == 0) return ms == 0 ? '0 min' : 'less than 1 min';
    return minutes < 60 ? '$minutes min' : '${minutes ~/ 60}h ${minutes % 60}m';
  }

  static String errorText(String? error) => switch (error) {
    'before_reset' =>
      'That period is before your fresh-data reset. Jarvis is collecting from the reset onward.',
    'usage_access_required' =>
      'Enable Usage Access for Jarvis in Settings → Screen time → Usage Access, then ask again. Android requires you to switch this on yourself.',
    'phone_locked_after_restart' =>
      'Unlock your phone once after restarting, then ask again.',
    'no_records' || 'records_unavailable' =>
      'Android has no usable activity records for that period. That does not mean your usage was zero.',
    'date_unavailable' =>
      'I can read today and the previous six days while Android retains the activity records.',
    _ =>
      'I could not read screen time. Check Usage Access in Jarvis Settings and try again.',
  };
  static Future<String> savedReport(String day) async {
    try {
      final data =
          jsonDecode(
                await channel.invokeMethod<String>('savedReport', day) ?? '{}',
              )
              as Map<String, dynamic>;
      return data['text']?.toString() ?? errorText(data['error']?.toString());
    } catch (_) {
      return errorText(null);
    }
  }

  static Future<String> answer(String question, {DateTime? now}) async {
    final q = question.toLowerCase();
    if (RegExp(r'\b(week|month|year|average|ago)\b').hasMatch(q)) {
      return 'Which day should I check? Ask for today, yesterday, or a date such as 2026-10-02. Android retains only recent detailed usage.';
    }
    // Reports use IST consistently, independent of the phone's current timezone.
    final today = (now ?? DateTime.now()).toUtc().add(
      const Duration(hours: 5, minutes: 30),
    );
    final iso = RegExp(r'\b\d{4}-\d{2}-\d{2}\b').firstMatch(q)?.group(0);
    final day =
        iso ??
        DateFormat('yyyy-MM-dd').format(
          q.contains('yesterday')
              ? today.subtract(const Duration(days: 1))
              : today,
        );
    try {
      final data =
          jsonDecode(await channel.invokeMethod<String>('read', day) ?? '{}')
              as Map<String, dynamic>;
      return formatAnswer(question, data);
    } catch (_) {
      return errorText(null);
    }
  }

  static String formatAnswer(String question, Map<String, dynamic> data) {
    if (data['error'] != null) return errorText(data['error'].toString());
    final q = question.toLowerCase();
    final apps = List<Map<String, dynamic>>.from(data['apps'] ?? []);
    final matches = apps.where((a) {
      final name = a['name'].toString().toLowerCase();
      final package = a['package'].toString().toLowerCase();
      return name.length > 2 &&
          (RegExp('\\b${RegExp.escape(name)}\\b').hasMatch(q) ||
              q.contains(package));
    }).toList();
    final all = RegExp(
      r'\b(all|total|breakdown|report|apps)\b|screen\s*time|digital\s*well\s*being|digital\s*wellbeing',
    ).hasMatch(q);
    if (matches.isNotEmpty && !all) {
      return '${data['day']} · foreground app time\n${matches.map((a) => '${a['name']}: ${duration(a['milliseconds'] as num)}').join('\n')}\n\nBased on Android activity records; background use is excluded.';
    }
    if (!all) {
      return 'I could not match a named app with recorded usage for ${data['day']}. Here is the available breakdown; an absent app may have no recorded foreground use.\n\n${data['text'] ?? 'No breakdown available.'}';
    }
    return data['text']?.toString() ?? errorText(null);
  }
}
