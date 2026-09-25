import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class ChatNotificationService {
  static const _channel = MethodChannel('com.jarvis/chat_notifications');
  static final chatVisible = ValueNotifier<bool>(true);
  static final openThread = ValueNotifier<String?>(null);
  static final updatedThread = ValueNotifier<String?>(null);
  static Future<void> initialize() async {
    _channel.setMethodCallHandler((call) async {
      final thread = call.arguments?.toString();
      if (thread == null || thread.isEmpty) return;
      final target = call.method == 'openChat' ? openThread : updatedThread;
      target.value = null;
      target.value = thread;
    });
    try { openThread.value = await _channel.invokeMethod<String>('takeInitialThread'); } catch (_) {}
  }
  static Future<void> setVisibleThread(String? id) async {
    try { await _channel.invokeMethod('setVisibleThread', id ?? ''); } catch (_) {}
  }
}
