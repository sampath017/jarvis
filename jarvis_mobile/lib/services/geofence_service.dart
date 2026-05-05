import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:native_geofence/native_geofence.dart';
import '../models/task.dart';

/// Native GeofenceService using OS-level Geofencing APIs (Rule 2).
///
/// - Zero backend polling.
/// - Zero manual GPS loops in mobile app.
/// - Registers boundaries with Android/iOS native geofencing clients.
/// - Fires notifications via a static background entry point.
class GeofenceService {
  static final GeofenceService _instance = GeofenceService._internal();
  factory GeofenceService() => _instance;
  GeofenceService._internal();

  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();
  
  StreamSubscription? _tasksSubscription;

  // ── Public API ──────────────────────────────────────────────────────────

  /// Initialize the geofence manager and sync from Firestore.
  Future<void> init() async {
    try {
      // 1. Initialize Native Geofencing
      await NativeGeofenceManager.instance.initialize();
      
      // 2. Initialise Local Notifications
      const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
      const initSettings = InitializationSettings(android: androidSettings);
      await _notifications.initialize(initSettings);

      // 3. Start listening to Firestore tasks to keep geofences in sync
      _startFirestoreSync();
      
      debugPrint('[GeofenceService] ✅ Initialized — Native OS Geofencing Active.');
    } catch (e) {
      debugPrint('[GeofenceService] ❌ Initialization Error: $e');
    }
  }

  /// Stop listening to Firestore changes.
  void dispose() {
    _tasksSubscription?.cancel();
    debugPrint('[GeofenceService] Disposed.');
  }

  // ── Firestore Sync ──────────────────────────────────────────────────────

  void _startFirestoreSync() {
    _tasksSubscription?.cancel();
    _tasksSubscription = FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'jarvis')
        .collection('tasks')
        .where('isCompleted', isEqualTo: false)
        .snapshots()
        .listen((snapshot) {
      final tasks = snapshot.docs.map((doc) {
        final data = doc.data();
        if (!data.containsKey('id')) data['id'] = doc.id;
        return Task.fromJson(data);
      }).where((t) => t.hasLocationReminder).toList();

      _syncNativeGeofences(tasks);
    });
  }

  Future<void> _syncNativeGeofences(List<Task> tasks) async {
    try {
      // 1. Get currently registered geofences
      final registered = await NativeGeofenceManager.instance.getRegisteredGeofences();
      final registeredIds = registered.map((g) => g.id).toSet();
      final taskIds = tasks.map((t) => t.id).toSet();

      // 2. Remove geofences that no longer exist or are completed
      for (final id in registeredIds) {
        if (!taskIds.contains(id)) {
          await NativeGeofenceManager.instance.removeGeofenceById(id);
          debugPrint('[GeofenceService] ➖ Removed geofence: $id');
        }
      }

      // 3. Add or update geofences
      for (final task in tasks) {
        final geofence = Geofence(
          id: task.id,
          location: Location(latitude: task.latitude!, longitude: task.longitude!),
          radiusMeters: task.radius?.toDouble() ?? 150.0,
          triggers: {
            if (task.triggerType == LocationTrigger.onEnter) GeofenceEvent.enter,
            if (task.triggerType == LocationTrigger.onExit) GeofenceEvent.exit,
          },
          iosSettings: const IosGeofenceSettings(
            initialTrigger: true,
          ),
          androidSettings: const AndroidGeofenceSettings(
            initialTriggers: {GeofenceEvent.enter},
            expiration: Duration(days: 30),
          ),
        );

        await NativeGeofenceManager.instance.createGeofence(geofence, geofenceTriggered);
        debugPrint('[GeofenceService] ➕ Registered geofence: ${task.title} (ID: ${task.id})');
      }
    } catch (e) {
      debugPrint('[GeofenceService] ❌ Sync Error: $e');
    }
  }
}

// ── Background Callback ──────────────────────────────────────────────────

/// Global background entry point for native geofence events.
@pragma('vm:entry-point')
Future<void> geofenceTriggered(GeofenceCallbackParams params) async {
  if (params.geofences.isEmpty) return;
  
  final geofenceId = params.geofences.first.id;
  debugPrint('[Geofence Callback] 📍 Triggered: $geofenceId Event: ${params.event}');
  
  // Initialize Firebase if needed
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp();
  }

  try {
    final doc = await FirebaseFirestore.instanceFor(app: Firebase.app(), databaseId: 'jarvis')
        .collection('tasks')
        .doc(geofenceId)
        .get();

    if (!doc.exists) return;
    final task = Task.fromJson(doc.data()!);

    final notifications = FlutterLocalNotificationsPlugin();
    const androidDetails = AndroidNotificationDetails(
      'jarvis_geofence',
      'Location Reminders',
      channelDescription: 'Notifications triggered by location-based tasks',
      importance: Importance.high,
      priority: Priority.high,
    );

    final triggerLabel = params.event == GeofenceEvent.exit ? 'left' : 'arrived at';

    await notifications.show(
      task.id.hashCode,
      '📍 Jarvis Reminder',
      'You just $triggerLabel ${task.locationName}! Don\'t forget: ${task.title}',
      const NotificationDetails(android: androidDetails),
    );
  } catch (e) {
    debugPrint('[Geofence Callback] ❌ Error handling event: $e');
  }
}
