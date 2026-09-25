import 'package:flutter/services.dart';

/// One silent restoration per app launch. Only Google may grant access; a saved
/// account preference alone never marks a service connected.
class GoogleConnectionRestore {
  Future<void>? _attempt;

  Future<void> run({
    required MethodChannel channel,
    required String preferredEmail,
    required Future<void> Function() refresh,
    required bool Function() connected,
    required Future<void> Function(Map<String, dynamic>) accept,
    required void Function(bool) setRestoring,
  }) => _attempt ??= _run(
    channel: channel,
    preferredEmail: preferredEmail,
    refresh: refresh,
    connected: connected,
    accept: accept,
    setRestoring: setRestoring,
  );

  Future<void> _run({
    required MethodChannel channel,
    required String preferredEmail,
    required Future<void> Function() refresh,
    required bool Function() connected,
    required Future<void> Function(Map<String, dynamic>) accept,
    required void Function(bool) setRestoring,
  }) async {
    setRestoring(true);
    try {
      await refresh();
      if (connected()) return;
      final authorization = await channel.invokeMapMethod<String, dynamic>(
        'restoreConnection',
        {'preferredEmail': preferredEmail},
      );
      if (authorization != null) await accept(authorization);
    } catch (_) {
      // Offline, a removed account or missing consent leaves setup available.
      // Never turn a silent restoration into an interactive authorization.
    } finally {
      await refresh();
      setRestoring(false);
    }
  }
}
