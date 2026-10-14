import 'dart:async';
import 'package:flutter/widgets.dart';
import 'power_state.dart';
import 'local_db_service.dart';
import 'reminder_alert_service.dart';
import 'sync_coordinator.dart';

/// Maintains on-device reminder schedules. App records never synchronize to a server.
class SyncService with WidgetsBindingObserver {
  static final SyncService _instance = SyncService._internal();
  factory SyncService() => _instance;
  SyncService._internal();

  final LocalDbService _localDb = LocalDbService();

  Timer? _syncTimer;
  Timer? _reminderTimer;
  late final _syncCoordinator = SyncCoordinator(
    (pullRemote) => _performSync(pullRemote: pullRemote),
  );
  bool _enabled = false;

  /// Poll only while the app is visible. Android workers handle background delivery.
  void startPeriodicSync() {
    if (!PowerState.enabled.value) return;
    if (!_enabled) {
      _enabled = true;
      WidgetsBinding.instance.addObserver(this);
    }
    if (WidgetsBinding.instance.lifecycleState != null &&
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed) {
      return;
    }
    _resumeTimers();
  }

  void _resumeTimers() {
    if (!PowerState.enabled.value) return;
    _syncTimer?.cancel();
    _syncTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      syncNow();
    });

    _reminderTimer?.cancel();
    _reminderTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      evaluateDueReminders();
    });

    // Run background sync and reminder checks non-blockingly after initial UI render
    Future.delayed(const Duration(milliseconds: 1500), () {
      if (!_enabled ||
          (WidgetsBinding.instance.lifecycleState != null &&
              WidgetsBinding.instance.lifecycleState !=
                  AppLifecycleState.resumed)) {
        return;
      }
      syncNow();
      evaluateDueReminders();
    });
  }

  void stopPeriodicSync() {
    _enabled = false;
    WidgetsBinding.instance.removeObserver(this);
    _pauseTimers();
  }

  void _pauseTimers() {
    _syncTimer?.cancel();
    _syncTimer = null;
    _reminderTimer?.cancel();
    _reminderTimer = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_enabled) return;
    if (state == AppLifecycleState.resumed) {
      _resumeTimers();
    } else {
      _pauseTimers();
    }
  }

  /// Local saves push immediately; periodic/resume/explicit refreshes also pull.
  Future<void> syncNow({bool pullRemote = true}) =>
      _syncCoordinator.run(pullRemote: pullRemote);

  Future<void> _performSync({required bool pullRemote}) async {
    await ReminderAlertService.sync(await _localDb.getReminders());
    await evaluateDueReminders();
  }

  /// Evaluate active reminders with due_at against current UTC time.
  /// Triggers system notification and marks status as TRIGGERED when due.
  Future<void> evaluateDueReminders() async {
    if (PowerState.enabled.value) {
      await ReminderAlertService.sync(await _localDb.getReminders());
    }
  }
}
