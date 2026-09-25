import 'dart:async';
import 'dart:convert';
import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;
import 'api_service.dart';
import 'local_db_service.dart';

/// Bidirectional Sync Service for Jarvis Mobile.
///
/// Synchronizes local mobile SQLite database (jarvis_mobile.db) with
/// Google Cloud Firestore via Cloud Run sync endpoints (/sync/push, /sync/pull).
class SyncService with WidgetsBindingObserver {
  static final SyncService _instance = SyncService._internal();
  factory SyncService() => _instance;
  SyncService._internal();

  final LocalDbService _localDb = LocalDbService();
  final ApiService _apiService = ApiService();

  Timer? _syncTimer;
  Timer? _reminderTimer;
  bool _isSyncing = false;
  bool _enabled = false;

  /// Poll only while the app is visible. Android workers handle background delivery.
  void startPeriodicSync() {
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
              WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed)) {
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

  /// Perform a full bidirectional sync: Push pending local changes, then Pull remote changes
  Future<void> syncNow() async {
    if (_isSyncing) return;
    if (!_apiService.isOnline) {
      // Fast check if server is reachable
      final online = await _apiService.checkHealth();
      if (!online) return;
    }

    _isSyncing = true;
    try {
      await _pushPendingChanges();
      await _pullRemoteChanges();
    } catch (e) {
      debugPrint('[SyncService] Sync cycle encountered error: $e');
    } finally {
      _isSyncing = false;
    }
  }

  /// Push locally created or modified records that have sync_status = 'pending'
  Future<void> _pushPendingChanges() async {
    // 1. Process pending deletions to Cloud Firestore
    try {
      final pendingDeletions = await _localDb.getPendingDeletions();
      for (final d in pendingDeletions) {
        final id = d['id'] as String;
        final type = d['record_type'] as String;
        if (type == 'chat_session') {
          final ok = await _apiService.deleteChatSession(id);
          if (ok) {
            await _localDb.removePendingDeletion(id);
            debugPrint('[SyncService] Successfully synced deletion for chat session $id');
          }
        } else if (type == 'all_chat_sessions') {
          final ok = await _apiService.deleteAllChatSessions();
          if (ok) {
            await _localDb.removePendingDeletion(id);
            debugPrint('[SyncService] Successfully synced deletion for all chat sessions');
          }
        }
      }
    } catch (e) {
      debugPrint('[SyncService] Error processing pending deletions: $e');
    }

    final pending = await _localDb.getPendingSyncRecords();
    final reminders = pending['reminders'] ?? [];
    final notes = pending['notes'] ?? [];
    final places = pending['places'] ?? [];
    final chatSessions = pending['chat_sessions'] ?? [];
    final chatMessages = pending['chat_messages'] ?? [];

    if (reminders.isEmpty &&
        notes.isEmpty &&
        places.isEmpty &&
        chatSessions.isEmpty &&
        chatMessages.isEmpty) {
      return;
    }

    final payload = {
      'reminders': reminders,
      'notes': notes,
      'places': places,
      'chat_sessions': chatSessions,
      'chat_messages': chatMessages,
    };

    final baseUrl = _apiService.baseUrl;
    final headers = {
      'Content-Type': 'application/json',
      'X-User-ID': _apiService.userId,
    };

    try {
      final res = await http
          .post(
            Uri.parse('$baseUrl/sync/push'),
            headers: headers,
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 20));

      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final synced = data['synced'] as Map<String, dynamic>? ?? {};

        final syncedReminders = List<String>.from(synced['reminders'] ?? []);
        final syncedNotes = List<String>.from(synced['notes'] ?? []);
        final syncedPlaces = List<String>.from(synced['places'] ?? []);
        final syncedSessions = List<String>.from(synced['chat_sessions'] ?? []);
        final syncedMessages = List<String>.from(synced['chat_messages'] ?? []);

        await _localDb.markRecordsSynced(
          reminderIds: syncedReminders,
          noteIds: syncedNotes,
          placeIds: syncedPlaces,
          sessionIds: syncedSessions,
          messageIds: syncedMessages,
        );
        debugPrint(
          '[SyncService] Successfully pushed pending records to Firestore: '
          '${syncedReminders.length} rems, ${syncedNotes.length} notes, '
          '${syncedSessions.length} sessions, ${syncedMessages.length} messages.',
        );
      }
    } catch (e) {
      debugPrint('[SyncService] Push pending failed: $e');
    }
  }

  /// Pull all remote records from Firestore to reconcile into local SQLite
  Future<void> _pullRemoteChanges() async {
    final baseUrl = _apiService.baseUrl;
    final headers = {
      'Content-Type': 'application/json',
      'X-User-ID': _apiService.userId,
    };

    try {
      final res = await http
          .get(
            Uri.parse('$baseUrl/sync/pull'),
            headers: headers,
          )
          .timeout(const Duration(seconds: 20));

      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final rems = List<Map<String, dynamic>>.from(data['reminders'] ?? []);
        final nts = List<Map<String, dynamic>>.from(data['notes'] ?? []);
        final plcs = List<Map<String, dynamic>>.from(data['places'] ?? []);
        final sessions = List<Map<String, dynamic>>.from(data['chat_sessions'] ?? []);
        final messages = List<Map<String, dynamic>>.from(data['chat_messages'] ?? []);

        await _localDb.reconcileRemoteRecords(
          remoteReminders: rems,
          remoteNotes: nts,
          remotePlaces: plcs,
          remoteChatSessions: sessions,
          remoteChatMessages: messages,
        );
        debugPrint(
          '[SyncService] Successfully reconciled from Firestore: '
          '${rems.length} rems, ${nts.length} notes, ${sessions.length} sessions, ${messages.length} messages.',
        );
      }
    } catch (e) {
      debugPrint('[SyncService] Pull remote failed: $e');
    }
  }

  /// Evaluate active reminders with due_at against current UTC time.
  /// Triggers system notification and marks status as TRIGGERED when due.
  Future<void> evaluateDueReminders() async {
    try {
      final reminders = await _localDb.getReminders(status: 'ACTIVE');
      final now = DateTime.now().toUtc();

      for (final r in reminders) {
        final status = (r['status'] ?? '').toString().toUpperCase();
        if (status != 'ACTIVE') continue;
        // The backend evaluates combined time and context conditions together.
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

          await _localDb.updateReminderStatus(id, 'TRIGGERED', markPending: true);
          debugPrint('[SyncService] Triggered time reminder: "$title" ($id)');
          // Push update to cloud asynchronously
          _pushPendingChanges();
        }
      }
    } catch (e) {
      debugPrint('[SyncService] evaluateDueReminders error: $e');
    }
  }
}
