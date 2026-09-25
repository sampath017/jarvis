import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/local_db_service.dart';
import '../../services/sensor_service.dart';
import '../../services/sync_service.dart';
import '../theme.dart';

/// Dedicated Reminders Screen:
/// Displays all active and fired reminders directly from offline-first Local Mobile SQLite.
/// Automatically evaluates and triggers reminders using local GPS/sensors even when offline,
/// and synchronizes with Google Cloud Firestore in the background.
class RemindersScreen extends StatefulWidget {
  final SensorService sensorService;

  const RemindersScreen({super.key, required this.sensorService});

  @override
  State<RemindersScreen> createState() => _RemindersScreenState();
}

class _RemindersScreenState extends State<RemindersScreen> {
  final ApiService _apiService = ApiService();
  final LocalDbService _localDb = LocalDbService();
  final SyncService _syncService = SyncService();

  List<Map<String, dynamic>> _reminders = [];
  List<Map<String, dynamic>> _places = [];
  bool _isLoading = false;
  Timer? _timeReminderTimer;
  DateTime? _lastContextPipelineCall;

  @override
  void initState() {
    super.initState();
    _apiService.addListener(_onServiceUpdate);
    _localDb.addListener(_onLocalDbUpdate);
    widget.sensorService.addListener(_onSensorUpdate);
    _initAndLoad();
    _timeReminderTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      _evaluateTimeReminders();
    });
  }

  @override
  void dispose() {
    _timeReminderTimer?.cancel();
    _apiService.removeListener(_onServiceUpdate);
    _localDb.removeListener(_onLocalDbUpdate);
    widget.sensorService.removeListener(_onSensorUpdate);
    super.dispose();
  }


  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  void _onLocalDbUpdate() {
    _refreshFromLocalDb();
  }

  Future<void> _initAndLoad() async {
    await _refreshFromLocalDb();
    _syncWithCloud(showFullLoader: false);
  }

  Future<void> _refreshFromLocalDb() async {
    final list = await _localDb.getReminders();
    final places = await _localDb.getPlaces();
    if (mounted) {
      setState(() {
        _reminders = list;
        _places = places;
      });
    }
  }

  Future<void> _syncWithCloud({bool showFullLoader = false}) async {
    if (showFullLoader) {
      setState(() => _isLoading = true);
    }
    try {
      await _syncService.syncNow();
      await _refreshFromLocalDb();
      await _apiService.fetchNotifications();
    } catch (_) {}
    if (mounted && showFullLoader) {
      setState(() => _isLoading = false);
    }
  }

  void _onSensorUpdate() {
    // Evaluate reminders offline directly against local mobile SQLite
    if (widget.sensorService.hasGpsFix && _reminders.isNotEmpty) {
      _evaluateOfflineReminders(
        latitude: widget.sensorService.lat,
        longitude: widget.sensorService.lon,
        activity: widget.sensorService.lastActivityTransition,
        activityTransitionTime: widget.sensorService.lastActivityTransitionTime,
        speedKmh: widget.sensorService.speedKmh,
      );

      // Also forward context event to cloud if online (throttled to at most once per 30 seconds)
      if (_apiService.isOnline) {
        final now = DateTime.now();
        if (_lastContextPipelineCall == null || now.difference(_lastContextPipelineCall!).inSeconds >= 30) {
          _lastContextPipelineCall = now;
          _apiService.evaluateAndTriggerContextPipeline(
            latitude: widget.sensorService.lat,
            longitude: widget.sensorService.lon,
            activity: widget.sensorService.lastActivityTransition,
          );
        }
      }
    }
  }

  /// Offline Haversine distance calculation in meters
  double _distanceMeters(double lat1, double lon1, double lat2, double lon2) {
    const p = 0.017453292519943295;
    final a = 0.5 -
        cos((lat2 - lat1) * p) / 2 +
        cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2;
    return 12742000 * asin(sqrt(a));
  }

  /// Evaluate reminder triggers locally on device without network dependency
  void _evaluateOfflineReminders({
    required double latitude,
    required double longitude,
    String? activity,
    DateTime? activityTransitionTime,
    double speedKmh = 0.0,
  }) {
    for (final r in _reminders) {
      final status = (r['status'] ?? 'ACTIVE').toString().toUpperCase();
      if (status != 'ACTIVE') continue;

      double? rLat = (r['latitude'] as num?)?.toDouble();
      double? rLon = (r['longitude'] as num?)?.toDouble();
      final rLocName = r['location_name']?.toString().trim();
      final hasLocationRequirement = (rLat != null && rLon != null) || (rLocName != null && rLocName.isNotEmpty);

      // If lat/lon missing but location_name exists, try resolving from saved places
      if ((rLat == null || rLon == null) && rLocName != null && rLocName.isNotEmpty) {
        final locLower = rLocName.toLowerCase();
        for (final p in _places) {
          final pName = (p['name'] ?? '').toString().toLowerCase().trim();
          final pAlias = (p['alias'] ?? '').toString().toLowerCase().trim();
          if (locLower == pName || locLower == pAlias || locLower.contains(pName) || pName.contains(locLower)) {
            rLat = (p['latitude'] as num?)?.toDouble();
            rLon = (p['longitude'] as num?)?.toDouble();
            break;
          }
        }
      }

      final radius = (r['radius_m'] as num?)?.toDouble() ?? 150.0;
      final hasGeofence = (rLat != null && rLon != null);

      final rAct = r['activity']?.toString().toUpperCase();
      final hasActivity = (rAct != null && rAct.isNotEmpty);

      // Require at least one valid trigger condition
      if (!hasLocationRequirement && !hasActivity) continue;
      final dueRaw = (r['due_at'] ?? '').toString().trim();
      if (dueRaw.isNotEmpty) {
        final due = DateTime.tryParse(dueRaw);
        if (due == null || DateTime.now().toUtc().isBefore(due.toUtc())) continue;
      }

      bool geofenceMatched = false;
      if (hasGeofence) {
        final dist = _distanceMeters(latitude, longitude, rLat, rLon);
        geofenceMatched = dist <= radius;
      }

      bool activityMatched = false;
      if (hasActivity && activity != null && activityTransitionTime != null) {
        final createdAt = DateTime.tryParse(r['created_at']?.toString() ?? '') ??
            DateTime.tryParse(r['updated_at']?.toString() ?? '');

        // Freshness check: The activity transition MUST occur AFTER the reminder was created
        final isFreshTransition = (createdAt == null || activityTransitionTime.isAfter(createdAt.subtract(const Duration(seconds: 10)))) &&
            DateTime.now().difference(activityTransitionTime).inMinutes < 5;

        // Support comma/pipe/slash-separated activities (e.g. 'WALKING, IN_VEHICLE')
        final expectedList = rAct.split(RegExp(r'[,/|]|(?:\bor\b)')).map((s) => s.trim().toUpperCase()).where((s) => s.isNotEmpty).toList();
        final upperActivity = activity.toUpperCase();
        final matchesActivity = expectedList.any((exp) => upperActivity.contains(exp) || exp.contains(upperActivity));

        // For walking, verify movement speed > 0.8 km/h or a fresh transition event
        final isMoving = (expectedList.contains('WALKING') && expectedList.length == 1) ? (speedKmh > 0.8 || isFreshTransition) : true;

        if (isFreshTransition && matchesActivity && isMoving) {
          activityMatched = true;
        }
      }

      // Conjunction rule: If reminder requires location, geofence MUST match!
      bool triggerMatched = false;
      if (hasLocationRequirement && hasActivity) {
        triggerMatched = geofenceMatched && activityMatched;
      } else if (hasLocationRequirement) {
        triggerMatched = geofenceMatched;
      } else if (hasActivity) {
        triggerMatched = activityMatched;
      }

      if (triggerMatched) {
        final id = r['id']?.toString() ?? '';
        final title = r['title'] ?? r['body'] ?? 'Reminder Alert';
        final loc = r['location_name'] ?? 'Saved location';

        // Post system tray notification directly to Android notification drawer
        _apiService.showSystemNotification(
          id: title.toString().trim().toLowerCase().hashCode,
          title: 'Jarvis Reminder: $title',
          content: 'Triggered near $loc (Offline Edge Match)',
        );

        // Mark as triggered in local SQLite and push to cloud sync queue
        _localDb.updateReminderStatus(id, 'TRIGGERED', markPending: true);

        // Sibling auto-completion: Also mark any other active reminders with the same title as triggered
        final normTitle = title.toString().trim().toLowerCase();
        for (final other in _reminders) {
          final otherId = other['id']?.toString() ?? '';
          final otherTitle = (other['title'] ?? other['body'] ?? '').toString().trim().toLowerCase();
          final otherStatus = (other['status'] ?? 'ACTIVE').toString().toUpperCase();
          if (otherId.isNotEmpty && otherId != id && otherTitle == normTitle && otherStatus == 'ACTIVE') {
            _localDb.updateReminderStatus(otherId, 'TRIGGERED', markPending: true);
          }
        }

        _syncService.syncNow();
      }
    }
  }

  /// Periodic evaluation of time-based reminders against local device clock
  void _evaluateTimeReminders() {
    final now = DateTime.now().toUtc();
    for (final r in _reminders) {
      final status = (r['status'] ?? 'ACTIVE').toString().toUpperCase();
      if (status != 'ACTIVE') continue;
      if ((r['activity'] ?? '').toString().trim().isNotEmpty ||
          (r['location_name'] ?? '').toString().trim().isNotEmpty ||
          r['latitude'] != null || r['longitude'] != null) {
        continue;
      }

      final dueAtRaw = r['due_at']?.toString().trim();
      if (dueAtRaw == null || dueAtRaw.isEmpty) continue;

      DateTime? dueDate = DateTime.tryParse(dueAtRaw);
      // Fallback for relative strings like "in 29 seconds" or "in 5 minutes"
      if (dueDate == null) {
        final lower = dueAtRaw.toLowerCase();
        final match = RegExp(r'(\d+)\s*(s|sec|second|min|minute|hour|hr|day)').firstMatch(lower);
        if (match != null) {
          final count = int.tryParse(match.group(1) ?? '0') ?? 0;
          final unit = match.group(2) ?? '';
          final createdAt = DateTime.tryParse(r['created_at']?.toString() ?? '') ??
              DateTime.tryParse(r['updated_at']?.toString() ?? '') ??
              DateTime.now().toUtc();
          if (unit.startsWith('s')) {
            dueDate = createdAt.add(Duration(seconds: count));
          } else if (unit.startsWith('min')) {
            dueDate = createdAt.add(Duration(minutes: count));
          } else if (unit.startsWith('hour') || unit.startsWith('hr')) {
            dueDate = createdAt.add(Duration(hours: count));
          } else if (unit.startsWith('day')) {
            dueDate = createdAt.add(Duration(days: count));
          }
        }
      }

      if (dueDate != null && (now.isAfter(dueDate) || now.isAtSameMomentAs(dueDate))) {
        final id = r['id']?.toString() ?? '';
        final title = r['title'] ?? r['body'] ?? 'Reminder Alert';

        _apiService.showSystemNotification(
          id: id.hashCode,
          title: 'Jarvis Reminder: $title',
          content: 'Time reminder — $title',
        );

        _localDb.updateReminderStatus(id, 'TRIGGERED', markPending: true);
        _syncService.syncNow();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text(
          'Reminders',
          style: TextStyle(
            fontWeight: FontWeight.bold,
            letterSpacing: 0.5,
            fontSize: 16,
          ),
        ),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: AppTheme.primary))
          : RefreshIndicator(
              onRefresh: () => _syncWithCloud(showFullLoader: false),
              backgroundColor: AppTheme.surfaceBright,
              color: AppTheme.primary,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
                children: [
                  if (_reminders.isEmpty)
                    _buildEmptyState()
                  else
                    for (final r in _reminders) ...[
                      _buildReminderTile(r),
                      const SizedBox(height: 10),
                    ],
                ],
              ),
            ),
    );
  }

  Widget _buildReminderTile(Map<String, dynamic> r) {
    final id = r['id']?.toString() ?? '';
    final title = r['title'] ?? r['body'] ?? 'Reminder';
    final loc = r['location_name'] ?? '';
    final activity = r['activity'] ?? '';
    final status = (r['status'] ?? 'ACTIVE').toString().toUpperCase();
    final syncStatus = r['sync_status'] ?? 'synced';

    final isActive = status == 'ACTIVE';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isActive ? AppTheme.border : AppTheme.border.withValues(alpha: 0.4),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: isActive
                  ? AppTheme.primary.withValues(alpha: 0.15)
                  : AppTheme.textSecondary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              isActive ? Icons.alarm_on_outlined : Icons.alarm_off_outlined,
              color: isActive ? AppTheme.primary : AppTheme.textSecondary,
              size: 18,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.bold,
                          color: isActive ? AppTheme.textPrimary : AppTheme.textSecondary,
                          decoration: isActive ? null : TextDecoration.lineThrough,
                        ),
                      ),
                    ),
                    Row(
                      children: [
                        if (syncStatus == 'pending') ...[
                          const Icon(Icons.cloud_upload_outlined, size: 12, color: AppTheme.amber),
                          const SizedBox(width: 4),
                        ],
                        Text(
                            isActive ? 'Active' : 'Completed',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                              color: isActive ? AppTheme.green : AppTheme.textSecondary,
                            ),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                if (loc.isNotEmpty)
                  Row(
                    children: [
                      const Icon(Icons.location_on_outlined, color: AppTheme.textSecondary, size: 13),
                      const SizedBox(width: 4),
                      Text(
                        loc,
                        style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                      ),
                    ],
                  ),
                if (activity.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Row(
                      children: [
                      const Icon(Icons.directions_car_outlined, color: AppTheme.textSecondary, size: 13),
                        const SizedBox(width: 4),
                        Text(
                          'Triggers on: $activity',
                          style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline, color: AppTheme.red, size: 20),
            tooltip: 'Delete Reminder',
            onPressed: () async {
              // 1. Delete locally from SQLite immediately
              await _localDb.deleteReminder(id);
              // 2. Delete remotely if online
              if (_apiService.isOnline) {
                _apiService.deleteReminder(id);
              }
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('Reminder "$title" deleted'),
                    duration: const Duration(seconds: 2),
                  ),
                );
              }
            },
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 40),
      alignment: Alignment.center,
      child: Column(
        children: [
          Icon(Icons.notifications_none,
              color: AppTheme.textSecondary.withValues(alpha: 0.5), size: 48),
          const SizedBox(height: 12),
          const Text(
            'No reminders yet',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: AppTheme.textPrimary),
          ),
          const SizedBox(height: 4),
          const Text(
            'Ask Jarvis to remind you about something,\nor pull down to refresh.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
          ),
        ],
      ),
    );
  }
}
