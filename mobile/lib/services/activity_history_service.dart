import 'mobile_store.dart';
import 'dart:convert';

import 'power_http.dart' as http;
import 'package:intl/intl.dart';

import 'api_service.dart';
import 'local_db_service.dart';

class ActivityHistoryService {
  ActivityHistoryService({ApiService? api, LocalDbService? db})
    : _api = api ?? ApiService(),
      _db = db ?? LocalDbService();

  final ApiService _api;
  final LocalDbService _db;

  String dayKey(DateTime day) => DateFormat('yyyy-MM-dd').format(day);

  Future<Map<String, dynamic>?> cachedDay(DateTime day) =>
      _db.loadActivityDay(dayKey(day));

  Future<Map<String, dynamic>> fetchDay(DateTime day) async {
    final start = DateTime(day.year, day.month, day.day);
    final end = DateTime(day.year, day.month, day.day + 1);
    final response = await http
        .post(
          Uri.parse('${_api.baseUrl}/mobile/activity-history'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'start_at': start.toUtc().toIso8601String(),
            'end_at': end.toUtc().toIso8601String(),
            '_mobile_state': await MobileStore.instance.historyContext(
              start,
              end,
            ),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception(
        'Activity history is unavailable (${response.statusCode})',
      );
    }
    final data = mergeActivityHistory(
      await cachedDay(day),
      Map<String, dynamic>.from(jsonDecode(response.body) as Map),
    );
    await _db.saveActivityDay(dayKey(day), data);
    return data;
  }
}

/// A partial API cache after restart cannot replace observations kept on-device.
Map<String, dynamic> mergeActivityHistory(
  Map<String, dynamic>? saved,
  Map<String, dynamic> incoming,
) {
  if (saved == null) return incoming;
  final result = <String, dynamic>{...saved, ...incoming};
  for (final field in [
    'observations',
    'micromoments',
    'timeline',
    'activity_sessions',
    'sessions',
  ]) {
    final records = <String, Map<String, dynamic>>{};
    for (final item in [
      ...saved[field] as List? ?? [],
      ...incoming[field] as List? ?? [],
    ]) {
      if (item is! Map) continue;
      final value = Map<String, dynamic>.from(item);
      final key =
          (field == 'observations'
              ? value['event_id']
              : field == 'sessions' || field == 'activity_sessions'
              ? value['session_id'] ?? value['id']
              : value['moment_id'] ?? value['id']) ??
          jsonEncode([
            value['timestamp'] ??
                value['start_at'] ??
                value['first_observed_at'] ??
                value['started_at'],
            value['activity'],
            value['transition'],
          ]);
      records[key.toString()] = value;
    }
    if (saved[field] is List || incoming[field] is List) {
      result[field] = records.values.toList();
    }
  }
  return result;
}
