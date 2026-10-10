import 'dart:convert';
import 'package:flutter/services.dart';

class ReminderAlertService {
  static const channel = MethodChannel('com.jarvis/foreground_service');
  static bool isRinging(Map<String, dynamic> reminder) =>
      const ['alarm', 'in_app_call'].contains(reminder['delivery_mode']);

  static Future<void> sync(List<Map<String, dynamic>> reminders) async {
    try {
      await channel.invokeMethod('syncRingingReminders', jsonEncode(reminders));
    } on MissingPluginException {
      // Android-only feature.
    }
  }
}
