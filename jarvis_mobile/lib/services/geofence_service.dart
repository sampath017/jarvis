import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:geolocator/geolocator.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../models/task.dart';

/// Intelligent GeofenceService with movement detection.
///
/// - Polls GPS every 30s while stationary, every 10s while moving.
/// - Detects movement speed to identify bike/car travel.
/// - Fires local push notifications when geofence boundaries are crossed.
/// - Uses reverse geocoding to provide area-aware context in notifications.
class GeofenceService {
  static final GeofenceService _instance = GeofenceService._internal();
  factory GeofenceService() => _instance;
  GeofenceService._internal();

  static const double _geofenceRadiusMeters = 150; // 150m trigger radius
  static const double _nearbyRadiusMeters = 500; // 500m "getting close" radius
  static const double _movingSpeedThreshold = 2.0; // m/s (~7 km/h) — walking fast / cycling
  static const Duration _stationaryPollInterval = Duration(seconds: 30);
  static const Duration _movingPollInterval = Duration(seconds: 10);

  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();

  Timer? _pollTimer;
  Position? _lastKnownPosition;
  bool _isMoving = false;
  final Set<String> _firedTaskIds = {}; // Prevent duplicate geofence notifications
  final Set<String> _nearbyAlertedIds = {}; // Prevent duplicate "approaching" alerts

  // ── Public API ──────────────────────────────────────────────────────────

  /// Initialise the notification channel and start monitoring.
  Future<void> init() async {
    // --- Notification setup ---
    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);
    await _notifications.initialize(initSettings);

    // Create notification channels
    final androidPlugin = _notifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>();

    await androidPlugin?.createNotificationChannel(
      const AndroidNotificationChannel(
        'jarvis_geofence',
        'Location Reminders',
        description: 'Notifications triggered by location-based tasks',
        importance: Importance.high,
      ),
    );
    await androidPlugin?.createNotificationChannel(
      const AndroidNotificationChannel(
        'jarvis_nearby',
        'Nearby Alerts',
        description: 'Heads-up when you are approaching a task location',
        importance: Importance.defaultImportance,
      ),
    );

    // --- Location permissions ---
    await _ensureLocationPermission();

    // --- Start polling ---
    _startPolling(_stationaryPollInterval);
    debugPrint('[GeofenceService] ✅ Initialized — polling every 30s (stationary mode).');
  }

  /// Cleanly stop the background poll timer.
  void dispose() {
    _pollTimer?.cancel();
    debugPrint('[GeofenceService] Disposed.');
  }

  /// Allow the app to clear fired alerts (e.g. when a task is marked complete).
  void clearFiredAlert(String taskId) {
    _firedTaskIds.remove(taskId);
    _nearbyAlertedIds.remove(taskId);
  }

  // ── Location Permissions ────────────────────────────────────────────────

  Future<void> _ensureLocationPermission() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      debugPrint('[GeofenceService] ⚠️ Location services disabled.');
      return;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) {
      debugPrint('[GeofenceService] ⚠️ Location permission permanently denied.');
    }
  }

  // ── Adaptive Polling ────────────────────────────────────────────────────

  void _startPolling(Duration interval) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(interval, (_) => _checkGeofences());
    // Also run immediately
    _checkGeofences();
  }

  /// Adjust polling frequency based on whether the user is moving.
  void _adjustPollingRate(double speedMs) {
    final wasMoving = _isMoving;
    _isMoving = speedMs > _movingSpeedThreshold;

    if (_isMoving && !wasMoving) {
      debugPrint('[GeofenceService] 🚴 Movement detected (${(speedMs * 3.6).toStringAsFixed(1)} km/h) — switching to fast polling (10s).');
      _startPolling(_movingPollInterval);
    } else if (!_isMoving && wasMoving) {
      debugPrint('[GeofenceService] 🧍 Stationary — switching to slow polling (30s).');
      _startPolling(_stationaryPollInterval);
    }
  }

  // ── Core Geofence Check ─────────────────────────────────────────────────

  Future<void> _checkGeofences() async {
    try {
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
        ),
      );

      // Adjust poll rate based on speed
      _adjustPollingRate(position.speed);

      // Fetch all incomplete tasks that have location data
      final snapshot = await FirebaseFirestore.instance
          .collection('tasks')
          .where('isCompleted', isEqualTo: false)
          .get();

      final locationTasks = snapshot.docs
          .map((doc) {
            final data = doc.data();
            if (!data.containsKey('id')) data['id'] = doc.id;
            return Task.fromJson(data);
          })
          .where((t) => t.hasLocationReminder)
          .toList();

      for (final task in locationTasks) {
        final distance = _distanceInMeters(
          position.latitude,
          position.longitude,
          task.latitude!,
          task.longitude!,
        );

        final wasInside = _lastKnownPosition != null &&
            _distanceInMeters(
                  _lastKnownPosition!.latitude,
                  _lastKnownPosition!.longitude,
                  task.latitude!,
                  task.longitude!,
                ) <=
                _geofenceRadiusMeters;

        final isInsideNow = distance <= _geofenceRadiusMeters;

        // ── 1) Geofence trigger (ON_EXIT / ON_ENTER) ────────────────────
        if (!_firedTaskIds.contains(task.id)) {
          bool shouldFire = false;
          if (task.locationTrigger == LocationTrigger.onExit) {
            shouldFire = wasInside && !isInsideNow;
          } else if (task.locationTrigger == LocationTrigger.onEnter) {
            shouldFire = !wasInside && isInsideNow;
          }

          if (shouldFire) {
            await _fireGeofenceNotification(task);
            _firedTaskIds.add(task.id);
          }
        }

        // ── 2) Proactive "approaching" alert (while moving) ─────────────
        if (_isMoving &&
            !_nearbyAlertedIds.contains(task.id) &&
            !_firedTaskIds.contains(task.id) &&
            distance <= _nearbyRadiusMeters &&
            distance > _geofenceRadiusMeters) {
          await _fireNearbyNotification(task, distance.round());
          _nearbyAlertedIds.add(task.id);
        }
      }

      _lastKnownPosition = position;
    } catch (e) {
      debugPrint('[GeofenceService] ❌ Error: $e');
    }
  }

  // ── Notifications ───────────────────────────────────────────────────────

  Future<void> _fireGeofenceNotification(Task task) async {
    final triggerLabel = task.locationTrigger == LocationTrigger.onExit
        ? 'left'
        : 'arrived at';

    await _notifications.show(
      task.id.hashCode,
      '📍 Jarvis Reminder',
      'You just $triggerLabel ${task.locationName}! Don\'t forget: ${task.title}',
      const NotificationDetails(
        android: AndroidNotificationDetails(
          'jarvis_geofence',
          'Location Reminders',
          channelDescription: 'Notifications triggered by location-based tasks',
          importance: Importance.high,
          priority: Priority.high,
          icon: '@mipmap/ic_launcher',
        ),
      ),
    );
    debugPrint('[GeofenceService] 🔔 GEOFENCE TRIGGERED for task: ${task.title}');
  }

  Future<void> _fireNearbyNotification(Task task, int distanceMeters) async {
    final action = task.locationTrigger == LocationTrigger.onExit
        ? 'you\'ll need to do when you leave'
        : 'waiting for you at';

    await _notifications.show(
      '${task.id}_nearby'.hashCode,
      '🗺️ Heads up!',
      'You\'re ${distanceMeters}m from ${task.locationName} — "${task.title}" is $action ${task.locationName}.',
      const NotificationDetails(
        android: AndroidNotificationDetails(
          'jarvis_nearby',
          'Nearby Alerts',
          channelDescription: 'Heads-up when you are approaching a task location',
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
          icon: '@mipmap/ic_launcher',
        ),
      ),
    );
    debugPrint('[GeofenceService] 📌 NEARBY ALERT (${distanceMeters}m) for task: ${task.title}');
  }

  // ── Haversine Distance (meters) ─────────────────────────────────────────

  double _distanceInMeters(
      double lat1, double lon1, double lat2, double lon2) {
    const earthRadius = 6371000.0;
    final dLat = _degToRad(lat2 - lat1);
    final dLon = _degToRad(lon2 - lon1);
    final a = sin(dLat / 2) * sin(dLat / 2) +
        cos(_degToRad(lat1)) *
            cos(_degToRad(lat2)) *
            sin(dLon / 2) *
            sin(dLon / 2);
    final c = 2 * atan2(sqrt(a), sqrt(1 - a));
    return earthRadius * c;
  }

  double _degToRad(double deg) => deg * (pi / 180);
}
