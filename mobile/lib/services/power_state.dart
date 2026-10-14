import 'package:flutter/foundation.dart';

/// Shared low-level gate, independent of API and service initialization.
class PowerState {
  static final enabled = ValueNotifier<bool>(true);
  static final Set<VoidCallback> _closers = {};
  static void track(VoidCallback close) => _closers.add(close);
  static void untrack(VoidCallback close) => _closers.remove(close);
  static void setEnabled(bool value) {
    enabled.value = value;
    if (!value) {
      for (final close in _closers.toList()) {
        close();
      }
    }
  }
}
