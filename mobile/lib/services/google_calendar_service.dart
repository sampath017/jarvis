import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'calendar_executor.dart';
import 'google_connection_restore.dart';

class GoogleCalendarService extends ChangeNotifier {
  GoogleCalendarService._();
  static final GoogleCalendarService instance = GoogleCalendarService._();
  static const channel = MethodChannel('com.jarvis/google_calendar');
  bool connected = false;
  bool needsReconnect = false;
  bool restoring = false;
  final _connectionRestore = GoogleConnectionRestore();
  String email = '';
  String calendarId = 'primary';
  bool get foreground =>
      WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;

  Future<void> refresh() async {
    try {
      final data =
          await channel.invokeMapMethod<String, dynamic>('status') ?? {};
      connected = data['connected'] == true;
      needsReconnect = data['needsReconnect'] == true;
      email = data['email']?.toString() ?? '';
      calendarId = data['calendarId']?.toString() ?? 'primary';
    } catch (_) {
      connected = false;
    }
    notifyListeners();
  }

  Future<List<Map<String, dynamic>>> connect() async {
    await restoreConnection();
    final auth = await channel.invokeMapMethod<String, dynamic>('connect');
    if (auth == null) {
      throw const CalendarFailure('Google connection cancelled.');
    }
    return _acceptConnection(auth);
  }

  Future<void> restoreConnection() => _connectionRestore.run(
    channel: channel,
    preferredEmail: 'sampathkovvali@gmail.com',
    refresh: refresh,
    connected: () => connected,
    accept: (auth) async {
      await _acceptConnection(auth);
    },
    setRestoring: (value) {
      restoring = value;
      notifyListeners();
    },
  );

  Future<List<Map<String, dynamic>>> _acceptConnection(
    Map<String, dynamic> auth,
  ) async {
    final calendars = await _calendars(auth['token'].toString());
    if (calendars.isEmpty) {
      throw const CalendarFailure(
        'No calendars available for this Google account.',
      );
    }
    final selected =
        calendars
            .where((c) => c['id'] == calendarId && auth['email'] == email)
            .firstOrNull ??
        calendars.where((c) => c['primary'] == true).firstOrNull ??
        calendars.first;
    await channel.invokeMethod('saveConnection', {
      'email': auth['email'],
      'calendarId': selected['id'],
    });
    await refresh();
    return calendars;
  }

  Future<List<Map<String, dynamic>>> calendars() async =>
      _calendars(await _token());

  Future<List<Map<String, dynamic>>> _calendars(String token) async {
    final result = <Map<String, dynamic>>[];
    String? page;
    do {
      final uri = Uri.https(
        'www.googleapis.com',
        '/calendar/v3/users/me/calendarList',
        {'maxResults': '250', 'pageToken': ?page},
      );
      final response = await http
          .get(uri, headers: {'Authorization': 'Bearer $token'})
          .timeout(const Duration(seconds: 20));
      if (response.statusCode != 200) {
        if (response.statusCode == 401) {
          await channel.invokeMethod('accessRequired');
          await refresh();
        }
        throw CalendarFailure(
          'Google Calendar denied access (${response.statusCode}). Check Calendar API and Google consent configuration.',
        );
      }
      final data = jsonDecode(response.body) as Map;
      result.addAll(List<Map<String, dynamic>>.from(data['items'] ?? []));
      page = data['nextPageToken'] as String?;
    } while (page != null);
    return result;
  }

  Future<void> selectCalendar(String id) async {
    await channel.invokeMethod('selectCalendar', id);
    await refresh();
  }

  Future<void> disconnect() async {
    await channel.invokeMethod('disconnect');
    await refresh();
  }

  Future<String> _token() async {
    try {
      return (await channel.invokeMethod<String>('token'))!;
    } on PlatformException {
      await refresh();
      rethrow;
    }
  }

  Future<String?> sessionKey() async {
    try {
      return await channel.invokeMethod<String>('sessionKey');
    } catch (_) {
      return null;
    }
  }

  Future<Map<String, dynamic>?> _read(String id) async {
    final value = await channel.invokeMethod<String>('readRecord', id);
    return value == null ? null : Map<String, dynamic>.from(jsonDecode(value));
  }

  Future<void> _write(String id, Map<String, dynamic> value) async {
    await channel.invokeMethod('writeRecord', {
      'key': id,
      'value': jsonEncode(value),
    });
  }

  Future<void> bindRequest(String requestId) async =>
      _write('request_$requestId', {'email': email, 'calendarId': calendarId});

  Future<Map<String, dynamic>> execute(
    String requestId,
    Map<String, dynamic> action, {
    CalendarApproval? approve,
    required Future<bool> Function() isActive,
  }) async {
    final client = http.Client();
    try {
      await refresh();
      final binding = await _read('request_$requestId');
      if (!connected ||
          binding?['email'] != email ||
          binding?['calendarId'] != action['default_calendar_id']) {
        return {
          'status': 'not_executed',
          'message':
              'Google connection changed. Send a new request after connecting the intended account.',
        };
      }
      return await CalendarExecutor(
        client: client,
        token: _token,
        readReceipt: _read,
        writeReceipt: _write,
        isForeground: () => foreground && connected,
        isActive: () async {
          final originalEmail = binding!['email'];
          await refresh();
          return connected && email == originalEmail && await isActive();
        },
      ).execute(action, approve: approve);
    } catch (_) {
      return {
        'status': 'not_executed',
        'message':
            'Calendar authorization is unavailable. Reconnect Google Calendar in Settings.',
      };
    } finally {
      client.close();
    }
  }
}
