import 'dart:convert';
import 'package:flutter/services.dart';

/// Local platform capability: no HTTP, accounts, sensors or assistant power gate.
class ClockService {
  static const channel = MethodChannel('com.jarvis/clock');
  static void initialize(void Function() open) {
    channel.setMethodCallHandler((call) async {
      if (call.method == 'openClock') open();
    });
  }

  Future<Map<String, dynamic>> execute(
    String action, [
    Map<String, dynamic> arguments = const {},
  ]) async {
    final raw = await channel.invokeMethod<String>('execute', {
      'action': action,
      'arguments': arguments,
    });
    return Map<String, dynamic>.from(jsonDecode(raw!) as Map);
  }

  Future<String?> pickSound() => channel.invokeMethod<String>('pickSound');
  Future<void> permissions(String type) async {
    await channel.invokeMethod('permissions', type);
  }

  Future<void> sleep(String sound, int minutes, {bool stop = false}) async {
    await channel.invokeMethod('sleep', {
      'sound': sound,
      'minutes': minutes,
      'stop': stop,
    });
  }
}

String clockDuration(int milliseconds, {bool hundredths = false}) {
  final ms = milliseconds.clamp(0, 31536000000);
  final seconds = ms ~/ 1000;
  final h = seconds ~/ 3600;
  final m = (seconds ~/ 60) % 60;
  final s = seconds % 60;
  final base = h > 0
      ? '$h:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}'
      : '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  return hundredths
      ? '$base.${((ms % 1000) ~/ 10).toString().padLeft(2, '0')}'
      : base;
}
