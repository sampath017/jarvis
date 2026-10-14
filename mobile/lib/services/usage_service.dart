import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'phone_data_window.dart';

class UsageService {
  static const channel = MethodChannel('com.jarvis/usage');
  static final openReport = ValueNotifier<String?>(null);
  static final overviewDays = ValueNotifier<Map<String, Map<String, dynamic>>>(
    {},
  );
  static Future<void>? _cacheLoad;
  static Future<void>? _cacheRefresh;

  /// Hydrate all retained days once; changing dates never calls Android's event reader.
  static Future<void> loadOverviewCache() =>
      _cacheLoad ??= _loadOverviewCache();

  static Future<void> _loadOverviewCache() async {
    try {
      _replaceOverview(await channel.invokeMethod<String>('cachedDays'));
    } catch (_) {
      _cacheLoad = null;
      rethrow;
    }
  }

  static void _replaceOverview(String? payload) {
    final data = jsonDecode(payload ?? '{}') as Map<String, dynamic>;
    overviewDays.value = {
      for (final entry in data.entries)
        entry.key: Map<String, dynamic>.from(entry.value as Map),
    };
  }

  /// Native collection updates SQLite and publishes each completed day separately.
  static Future<void> refreshOverviewCache() => _cacheRefresh ??=
      _refreshOverviewCache().whenComplete(() => _cacheRefresh = null);

  static Future<void> _refreshOverviewCache() async {
    await loadOverviewCache();
    _replaceOverview(await channel.invokeMethod<String>('refreshCache'));
  }

  static Future<void> initialize() async {
    channel.setMethodCallHandler((call) async {
      if (call.method == 'openReport') {
        openReport.value = null;
        openReport.value = call.arguments as String?;
      } else if (call.method == 'usageDayUpdated') {
        final args = Map<String, dynamic>.from(call.arguments as Map);
        overviewDays.value = {
          ...overviewDays.value,
          args['day'] as String: Map<String, dynamic>.from(
            jsonDecode(args['data'] as String) as Map,
          ),
        };
      }
    });
    try {
      openReport.value = await channel.invokeMethod<String>('takeInitialDay');
    } catch (_) {}
    unawaited(refreshOverviewCache().catchError((Object _) {}));
  }

  static String duration(num ms) {
    final minutes = ms ~/ 60000;
    if (minutes == 0) return ms == 0 ? '0 min' : 'less than 1 min';
    return minutes < 60 ? '$minutes min' : '${minutes ~/ 60}h ${minutes % 60}m';
  }

  static String errorText(String? error) => switch (error) {
    'before_reset' =>
      'That period is before your fresh-data reset. Jarvis is collecting from the reset onward.',
    'usage_access_required' =>
      'Enable Usage Access for Jarvis in Settings → Screen time → Usage Access, then ask again. Android requires you to switch this on yourself.',
    'phone_locked_after_restart' =>
      'Unlock your phone once after restarting, then ask again.',
    'no_records' || 'records_unavailable' =>
      'Android has no usable activity records for that period. That does not mean your usage was zero.',
    'date_unavailable' =>
      'No saved usage is available for that date. Android only retains recent activity events.',
    _ =>
      'I could not read screen time. Check Usage Access in Jarvis Settings and try again.',
  };
  static Future<String> savedReport(String day) async {
    try {
      final data =
          jsonDecode(
                await channel.invokeMethod<String>('savedReport', day) ?? '{}',
              )
              as Map<String, dynamic>;
      return data['text']?.toString() ?? errorText(data['error']?.toString());
    } catch (_) {
      return errorText(null);
    }
  }

  /// Structured records for a model-selected read, not a prewritten answer.
  static Future<Map<String, dynamic>> readToolRecords(
    Map<String, dynamic> arguments, {
    DateTime? now,
  }) async {
    final window = PhoneDataWindow.parse(
      arguments['start_date']?.toString() ?? '',
      arguments['end_date']?.toString() ?? '',
      now: now,
    );
    final requestedLimit = arguments['max_apps'] ?? 20;
    final query = arguments['app_query']?.toString().trim().toLowerCase() ?? '';
    if (requestedLimit is! int ||
        requestedLimit < 1 ||
        requestedLimit > 100 ||
        query.length > 120) {
      throw const FormatException(
        'Use max_apps from 1 to 100 and app_query up to 120 characters.',
      );
    }
    final limit = requestedLimit.clamp(
      1,
      (300 ~/ window.days.length).clamp(1, 100),
    );
    final days = <Map<String, dynamic>>[];
    for (final day in window.days) {
      final key = PhoneDataWindow.dayKey(day);
      final data = Map<String, dynamic>.from(
        jsonDecode(await channel.invokeMethod<String>('read', key) ?? '{}')
            as Map,
      );
      if (data['error'] != null ||
          data['day'] != key ||
          data['total_ms'] is! num) {
        days.add({
          'day': key,
          'status': 'unavailable',
          'reason': data['error'] ?? 'records_unavailable',
          'message': errorText(data['error']?.toString()),
        });
        continue;
      }
      final all = List<Map<String, dynamic>>.from(data['apps'] ?? []);
      final apps =
          all
              .where(
                (app) =>
                    app['milliseconds'] is num &&
                    (app['milliseconds'] as num).isFinite &&
                    (app['milliseconds'] as num) > 0 &&
                    (query.isEmpty ||
                        '${app['name']} ${app['package']}'
                            .toLowerCase()
                            .contains(query)),
              )
              .map(
                (app) => <String, dynamic>{
                  'name': app['name']?.toString() ?? 'Unnamed app',
                  'package': app['package']?.toString() ?? '',
                  'milliseconds': app['milliseconds'],
                },
              )
              .toList()
            ..sort(
              (a, b) => (b['milliseconds'] as num).compareTo(
                a['milliseconds'] as num,
              ),
            );
      final matched = apps.fold<num>(
        0,
        (sum, app) => sum + (app['milliseconds'] as num),
      );
      final selected = apps
          .take(apps.length > limit ? limit - 1 : limit)
          .toList();
      if (selected.length < apps.length) {
        selected.add({
          'name': query.isEmpty ? 'Other apps' : 'Other matching apps',
          'is_aggregate': true,
          'milliseconds': apps
              .skip(selected.length)
              .fold<num>(0, (sum, app) => sum + (app['milliseconds'] as num)),
        });
      }
      days.add({
        'day': key,
        'status': 'ok',
        'total_ms': data['total_ms'],
        'matched_ms': matched,
        'start_ms': data['start_ms'],
        'end_ms': data['end_ms'],
        'apps': selected,
        'matching_app_count': apps.length,
        'aggregated_remainder':
            selected.length < apps.length || apps.length > limit,
      });
    }
    final good = days.where((day) => day['status'] == 'ok').length;
    return {
      'status': good == days.length
          ? 'ok'
          : good > 0
          ? 'partial'
          : 'unavailable',
      'source': 'android_app_usage',
      'timezone': 'Asia/Kolkata',
      'start_date': arguments['start_date'],
      'end_date': PhoneDataWindow.dayKey(window.end),
      'unit': 'milliseconds',
      'app_query': query,
      'max_apps_per_day': limit,
      'days': days,
      'notes':
          'Recorded foreground app time. Excludes home/lock screens and background use. Missing days are unknown, not zero. total_ms is the full day; matched_ms and apps respect the app filter. Use exact durations for chart shares.',
    };
  }
}
