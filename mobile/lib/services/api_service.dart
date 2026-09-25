import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;
import 'local_db_service.dart';

/// Client service that communicates with the Jarvis Cloud Run backend.
/// Handles sending Low-Telemetry metadata, executing agentic commands,
/// and synchronizing Reminders, Tasks, and Notes.
class ApiService extends ChangeNotifier with WidgetsBindingObserver {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal() {
    WidgetsBinding.instance.addObserver(this);
    _startNotificationPoll();
  }

  static const _channel = MethodChannel('com.jarvis/foreground_service');
  final Set<String> _dispatchedNotificationIds = {};
  final Map<String, DateTime> _recentNotificationTimestamps = {};
  Timer? _notificationPollTimer;
  bool _flushingContext = false;

  // Cloud Run Backend URL (Deployed & Active)
  String _baseUrl = 'https://jarvis-backend-898516599131.asia-south1.run.app';
  String get baseUrl => _baseUrl;

  String _userId = 'poco_x4_pro_user';
  String get userId => _userId;

  bool _isOnline = false;
  bool get isOnline => _isOnline;

  DateTime? _lastHealthCheck;
  DateTime? get lastHealthCheck => _lastHealthCheck;

  List<Map<String, dynamic>> _reminders = [];
  List<Map<String, dynamic>> get reminders => _reminders;

  List<Map<String, dynamic>> _notes = [];
  List<Map<String, dynamic>> get notes => _notes;

  List<Map<String, dynamic>> _notifications = [];
  List<Map<String, dynamic>> get notifications => _notifications;

  void _startNotificationPoll() {
    _notificationPollTimer?.cancel();
    if (WidgetsBinding.instance.lifecycleState != null &&
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed) {
      return;
    }
    _notificationPollTimer = Timer.periodic(const Duration(seconds: 25), (_) {
      fetchNotifications();
      flushContextEvents();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _startNotificationPoll();
      unawaited(fetchNotifications());
      unawaited(flushContextEvents());
    } else {
      _notificationPollTimer?.cancel();
      _notificationPollTimer = null;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _notificationPollTimer?.cancel();
    super.dispose();
  }

  void setBaseUrl(String url) {
    _baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    notifyListeners();
    checkHealth();
  }

  void setUserId(String uid) {
    _userId = uid;
    notifyListeners();
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-User-ID': _userId,
      };

  /// Ping the Cloud Run /health probe
  Future<bool> checkHealth() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/health'))
          .timeout(const Duration(seconds: 10));
      _isOnline = res.statusCode == 200;
      _lastHealthCheck = DateTime.now();
      notifyListeners();
      return _isOnline;
    } catch (e) {
      debugPrint('[ApiService] Health check error: $e');
      _isOnline = false;
      notifyListeners();
      return false;
    }
  }

  /// Transmit Context Event or Low-Telemetry JSON packet to Cloud Run (/context-events)
  Future<Map<String, dynamic>?> sendContextEvent({
    required String eventType,
    String? activity,
    String? transition,
    Map<String, dynamic>? location,
    Map<String, dynamic>? featureSummary,
    Map<String, dynamic>? journeyGps,
    String? transitionState,
  }) async {
    final nowIso = DateTime.now().toUtc().toIso8601String();
    final payload = <String, dynamic>{
      'event_id': 'evt_${DateTime.now().microsecondsSinceEpoch}',
      'event_type': eventType,
      'activity': activity ?? 'UNKNOWN',
      'transition': transition ?? (transitionState ?? 'ENTER'),
      'occurred_at': nowIso,
      'timestamp': nowIso,
      'location': ?location,
      'gps': ?location,
      'feature_summary': ?featureSummary,
      'journey_gps': ?journeyGps,
    };

    await LocalDbService().queueContextEvent(payload);
    return flushContextEvents();
  }

  Future<Map<String, dynamic>?> flushContextEvents() async {
    if (_flushingContext) return null;
    _flushingContext = true;
    Map<String, dynamic>? latest;
    try {
      for (final event in await LocalDbService().pendingContextEvents()) {
        final res = await http.post(Uri.parse('$_baseUrl/context-events'),
            headers: _headers, body: jsonEncode(event)).timeout(const Duration(seconds: 60));
        if (res.statusCode != 200 && res.statusCode != 202) break;
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        if (data['status'] != 'ok') break;
        await LocalDbService().acknowledgeContextEvent(event['event_id'].toString());
        latest = data;
      }
      if (latest != null) {
        await fetchReminders();
        await fetchNotifications();
      }
    } catch (e) {
      debugPrint('[ApiService] Context retained for retry: $e');
    } finally {
      _flushingContext = false;
    }
    return latest;
  }

  /// Dispatch an explicit text/voice command to Cloud Run (/commands)
  /// e.g. "Remind me to check tire pressure when I reach the Royal Enfield garage"
  Future<Map<String, dynamic>?> sendCommand(
    String text, {
    String? threadId,
    List<Map<String, dynamic>>? history,
    double? latitude,
    double? longitude,
    String? requestId,
  }) async {
    final payload = <String, dynamic>{
      'request_id': requestId ?? 'cmd_${DateTime.now().millisecondsSinceEpoch}',
      'thread_id': threadId ?? 'default_thread',
      'text': text,
      'latitude': ?latitude,
      'longitude': ?longitude,
      if (history != null && history.isNotEmpty) 'history': history,
      'timestamp': DateTime.now().toUtc().toIso8601String(),
    };

    try {
      final res = await http
          .post(
            Uri.parse('$_baseUrl/commands'),
            headers: _headers,
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 75));

      if (res.statusCode == 200) {
        _isOnline = true;
        notifyListeners();
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        await fetchReminders();
        await fetchNotes();
        return data;
      } else {
        try {
          final errData = jsonDecode(res.body);
          return {
            'status': 'error',
            'error': errData['detail'] ?? 'Server error ${res.statusCode}',
          };
        } catch (_) {
          return {
            'status': 'error',
            'error': 'Server returned HTTP ${res.statusCode}',
          };
        }
      }
    } catch (e) {
      debugPrint('[ApiService] Error sending command: $e');
      return {
        'status': 'error',
        'error': e.toString().contains('TimeoutException')
            ? 'Request timed out — Jarvis took longer than 75s to finish all actions.'
            : 'Network connection issue: $e',
      };
    }
  }

  /// Fetch active reminders from Cloud Run (/reminders)
  Future<List<Map<String, dynamic>>> fetchReminders() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/reminders'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        _isOnline = true;
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        _reminders = List<Map<String, dynamic>>.from(data['records'] ?? []);
        notifyListeners();
        return _reminders;
      }
    } catch (_) {}
    return _reminders;
  }

  /// Fetch saved notes from Cloud Run (/notes)
  Future<List<Map<String, dynamic>>> fetchNotes() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/notes'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        _isOnline = true;
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        _notes = List<Map<String, dynamic>>.from(data['records'] ?? []);
        notifyListeners();
        return _notes;
      }
    } catch (_) {}
    return _notes;
  }

  /// Fetch notifications from Cloud Run (/notifications) and dispatch to phone system tray
  Future<List<Map<String, dynamic>>> fetchNotifications() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/notifications'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        _notifications =
            List<Map<String, dynamic>>.from(data['records'] ?? []);

        // Deliver any pending reminder alerts directly to Android phone notification tray
        for (final n in _notifications) {
          final id = n['id']?.toString() ?? '';
          final reminderId = n['reminder_id']?.toString() ?? '';
          final status = n['status']?.toString().toUpperCase();
          if (status == 'PENDING' && !_dispatchedNotificationIds.contains(id)) {
            _dispatchedNotificationIds.add(id);
            if (reminderId.isNotEmpty) {
              _dispatchedNotificationIds.add(reminderId);
            }
            final title = n['title']?.toString() ?? 'Jarvis Reminder';
            final body = n['body']?.toString() ?? title;
            showSystemNotification(
              id: title.trim().toLowerCase().hashCode,
              title: title,
              content: body,
            );
            // Acknowledge notification on backend to mark as delivered
            acknowledgeNotification(id);
          }
        }

        notifyListeners();
        return _notifications;
      }
    } catch (_) {}
    return _notifications;
  }

  /// Dispatch a high-priority system tray notification on the Android device
  void showSystemNotification({int? id, required String title, required String content}) {
    final normTitle = title.trim().toLowerCase();
    final now = DateTime.now();
    if (_recentNotificationTimestamps.containsKey(normTitle)) {
      final last = _recentNotificationTimestamps[normTitle]!;
      if (now.difference(last).inMinutes < 5) {
        debugPrint('[ApiService] Suppressed duplicate notification within 5 min: "$title"');
        return;
      }
    }
    _recentNotificationTimestamps[normTitle] = now;

    final notificationId = id ?? normTitle.hashCode;
    try {
      _channel.invokeMethod('showSystemNotification', {
        'id': notificationId,
        'title': title,
        'content': content,
      });
    } catch (e) {
      debugPrint('[ApiService] Error showing system notification: $e');
    }
  }

  /// Acknowledge a notification on Cloud Run (/notifications/{id}/acknowledge)
  Future<bool> acknowledgeNotification(String id) async {
    try {
      final res = await http.post(
        Uri.parse('$_baseUrl/notifications/$id/acknowledge'),
        headers: _headers,
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Create a new reminder directly via Cloud Run (/reminders)
  Future<bool> createReminder({
    required String title,
    String? body,
    String? locationName,
    double? latitude,
    double? longitude,
    String? activity,
    String? dueAt,
  }) async {
    final payload = {
      'title': title,
      'body': body ?? title,
      'location_name': locationName,
      'latitude': latitude,
      'longitude': longitude,
      'activity': activity,
      'due_at': dueAt,
      'radius_m': 150.0,
      'status': 'ACTIVE',
      'one_shot': true,
    };

    try {
      final res = await http.post(
        Uri.parse('$_baseUrl/reminders'),
        headers: _headers,
        body: jsonEncode(payload),
      );
      if (res.statusCode == 201 || res.statusCode == 200) {
        await fetchReminders();
        return true;
      }
    } catch (e) {
      debugPrint('[ApiService] Error creating reminder: $e');
    }
    return false;
  }

  /// Delete a reminder from Cloud Run (/reminders/{id})
  Future<bool> deleteReminder(String id) async {
    try {
      final res = await http.delete(
        Uri.parse('$_baseUrl/reminders/$id'),
        headers: _headers,
      );
      if (res.statusCode == 204 || res.statusCode == 200) {
        await fetchReminders();
        return true;
      }
    } catch (_) {}
    return false;
  }

  /// Delete a chat session from Cloud Run / Firestore (/chat-sessions/{id})
  Future<bool> deleteChatSession(String id) async {
    try {
      final res = await http
          .delete(
            Uri.parse('$_baseUrl/chat-sessions/$id'),
            headers: _headers,
          )
          .timeout(const Duration(seconds: 12));
      return res.statusCode == 204 || res.statusCode == 200 || res.statusCode == 404;
    } catch (e) {
      debugPrint('[ApiService] Error deleting chat session $id: $e');
    }
    return false;
  }

  /// Delete all chat sessions and messages from Cloud Run / Firestore (/chat-sessions)
  Future<bool> deleteAllChatSessions() async {
    try {
      final res = await http
          .delete(
            Uri.parse('$_baseUrl/chat-sessions'),
            headers: _headers,
          )
          .timeout(const Duration(seconds: 15));
      return res.statusCode == 204 || res.statusCode == 200 || res.statusCode == 404;
    } catch (e) {
      debugPrint('[ApiService] Error deleting all chat sessions: $e');
    }
    return false;
  }

  /// Create a new note directly via Cloud Run (/notes)
  Future<bool> createNote({
    required String content,
    String? place,
  }) async {
    final payload = {
      'content': content,
      'place': place,
    };

    try {
      final res = await http.post(
        Uri.parse('$_baseUrl/notes'),
        headers: _headers,
        body: jsonEncode(payload),
      );
      if (res.statusCode == 201 || res.statusCode == 200) {
        await fetchNotes();
        return true;
      }
    } catch (e) {
      debugPrint('[ApiService] Error creating note: $e');
    }
    return false;
  }

  /// Delete a note from Cloud Run (/notes/{id})
  Future<bool> deleteNote(String id) async {
    try {
      final res = await http.delete(
        Uri.parse('$_baseUrl/notes/$id'),
        headers: _headers,
      );
      if (res.statusCode == 204 || res.statusCode == 200) {
        await fetchNotes();
        return true;
      }
    } catch (_) {}
    return false;
  }

  /// Automatically check if any active reminder needs triggering based on GPS or activity
  Future<List<String>> evaluateAndTriggerContextPipeline({
    double? latitude,
    double? longitude,
    String? activity,
  }) async {
    final res = await sendContextEvent(
      eventType: 'TELEMETRY_PIPELINE_CHECK',
      featureSummary: {
        'activity_hint': activity ?? 'UNKNOWN',
      },
      journeyGps: {
        'current_latitude': latitude,
        'current_longitude': longitude,
      },
      transitionState: activity,
    );

    final changed = List<String>.from(res?['changed_records'] ?? []);
    if (changed.isNotEmpty) {
      await fetchReminders();
      await fetchNotifications();
    }
    return changed;
  }
}
