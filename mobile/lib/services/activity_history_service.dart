import 'dart:convert';

import 'package:http/http.dart' as http;
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
    final uri = Uri.parse('${_api.baseUrl}/activity-history').replace(
      queryParameters: {
        'start_at': start.toUtc().toIso8601String(),
        'end_at': end.toUtc().toIso8601String(),
      },
    );
    final response = await http
        .get(uri, headers: {'X-User-ID': _api.userId})
        .timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception(
        'Activity history is unavailable (${response.statusCode})',
      );
    }
    final data = Map<String, dynamic>.from(jsonDecode(response.body) as Map);
    await _db.saveActivityDay(dayKey(day), data);
    return data;
  }
}
