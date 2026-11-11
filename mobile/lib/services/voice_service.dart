import 'dart:convert';
import 'package:flutter/services.dart';

class VoiceService {
  static const channel = MethodChannel('com.jarvis/voice');
  static void initialize(void Function() open) {
    channel.setMethodCallHandler((call) async {
      if (call.method == 'openVoice') open();
    });
  }

  Future<Map<String, dynamic>> status() async => Map<String, dynamic>.from(
    jsonDecode((await channel.invokeMethod<String>('status'))!) as Map,
  );
  Future<bool> start() async =>
      await channel.invokeMethod<bool>('start') ?? false;
  Future<void> stop() async {
    await channel.invokeMethod('stop');
  }

  Future<void> newChat() async {
    await channel.invokeMethod('newChat');
  }

  Future<void> speakReplies(bool value) async {
    await channel.invokeMethod('speakReplies', value);
  }
}
