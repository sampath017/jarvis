import 'dart:convert';
import 'package:http/http.dart' as http;

typedef CalendarApproval = Future<bool> Function(Map<String, dynamic> preview);

/// All Google mutations pass through this device-side approval gate.
class CalendarExecutor {
  CalendarExecutor({
    required this.client,
    required this.token,
    required this.readReceipt,
    required this.writeReceipt,
    required this.isActive,
    required this.isForeground,
  });
  final http.Client client;
  final Future<String> Function() token;
  final Future<Map<String, dynamic>?> Function(String) readReceipt;
  final Future<void> Function(String, Map<String, dynamic>) writeReceipt;
  final Future<bool> Function() isActive;
  final bool Function() isForeground;
  static const _fields = {
    'summary',
    'description',
    'location',
    'start',
    'end',
    'attendees',
    'recurrence',
  };

  Future<Map<String, dynamic>> _request(
    String method,
    List<String> path, {
    Map<String, String> query = const {},
    Map<String, dynamic>? body,
    String? etag,
  }) async {
    final uri = Uri(
      scheme: 'https',
      host: 'www.googleapis.com',
      pathSegments: ['calendar', 'v3', ...path],
      queryParameters: query.isEmpty ? null : query,
    );
    final request = http.Request(method, uri)
      ..headers.addAll({
        'Authorization': 'Bearer ${await token()}',
        'Content-Type': 'application/json',
        'If-Match': ?etag,
      });
    if (body != null) request.body = jsonEncode(body);
    final response = await http.Response.fromStream(
      await client.send(request).timeout(const Duration(seconds: 25)),
    ).timeout(const Duration(seconds: 25));
    if (response.statusCode == 412) {
      throw const CalendarFailure(
        'Event changed elsewhere. Read it again and review a new proposal.',
      );
    }
    if (response.statusCode == 401) {
      throw const CalendarFailure(
        'Google permission expired. Reconnect Google Calendar in Settings.',
      );
    }
    if (response.statusCode == 403) {
      throw const CalendarFailure(
        'Google denied access. Check account permission and Calendar API configuration.',
      );
    }
    if (response.statusCode == 404 || response.statusCode == 410) {
      throw const CalendarFailure(
        'Calendar or event no longer exists. Search again.',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      if (response.statusCode >= 500) {
        throw const CalendarFailure(
          'Google could not confirm the operation. Check your calendar before trying again.',
          uncertain: true,
        );
      }
      throw CalendarFailure(
        'Google Calendar rejected the operation (${response.statusCode}).',
      );
    }
    return response.body.isEmpty
        ? {}
        : Map<String, dynamic>.from(jsonDecode(response.body) as Map);
  }

  Map<String, dynamic> _compact(
    Map<String, dynamic> event, {
    bool preview = false,
  }) {
    final compact = <String, dynamic>{
      for (final key in {
        ..._fields,
        'id',
        'etag',
        'status',
        'htmlLink',
        'recurringEventId',
        'originalStartTime',
        'organizer',
      })
        if (event.containsKey(key)) key: event[key],
    };
    if (!preview) {
      for (final key in ['summary', 'location', 'description']) {
        final value = compact[key];
        if (value is String && value.length > 1000) {
          compact[key] = value.substring(0, 1000);
          compact['${key}_truncated'] = true;
        }
      }
      final guests = compact['attendees'];
      if (guests is List) {
        compact['attendees'] = [
          for (final a in guests.take(20))
            {
              for (final k in ['email', 'responseStatus'])
                if ((a as Map).containsKey(k)) k: a[k],
            },
        ];
        if (guests.length > 20) compact['attendees_truncated'] = true;
      }
    }
    return compact;
  }

  void _validateEvent(Map<String, dynamic> event) {
    for (final key in ['summary', 'description', 'location']) {
      if (event[key] != null &&
          (event[key] is! String || (event[key] as String).length > 10000)) {
        throw CalendarFailure('Invalid $key.');
      }
    }
    if (event['summary'] is! String ||
        (event['summary'] as String).trim().isEmpty) {
      throw const CalendarFailure('An event title is required.');
    }
    DateTime boundary(dynamic raw) {
      if (raw is! Map) {
        throw const CalendarFailure('Start and end are required.');
      }
      if (raw.keys.any((k) => !{'date', 'dateTime', 'timeZone'}.contains(k))) {
        throw const CalendarFailure('Invalid event time fields.');
      }
      final date = raw['date'];
      final time = raw['dateTime'];
      if ((date == null) == (time == null)) {
        throw const CalendarFailure('Choose timed or all-day boundaries.');
      }
      final value = (date ?? time).toString();
      if (date != null && !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
        throw const CalendarFailure('All-day dates must use YYYY-MM-DD.');
      }
      if (time != null && !RegExp(r'T.*(Z|[+-]\d{2}:\d{2})$').hasMatch(value)) {
        throw const CalendarFailure('Event times require a timezone offset.');
      }
      final parsed = DateTime.tryParse(value);
      if (parsed == null ||
          (date != null &&
              parsed.toIso8601String().substring(0, 10) != value)) {
        throw const CalendarFailure('Invalid event date.');
      }
      return parsed;
    }

    final start = boundary(event['start']);
    final end = boundary(event['end']);
    if ((event['start'] as Map).containsKey('date') !=
            (event['end'] as Map).containsKey('date') ||
        !end.isAfter(start)) {
      throw const CalendarFailure(
        'End must be after start, using the same event type.',
      );
    }
    if (event.containsKey('attendees')) {
      final attendees = event['attendees'];
      if (attendees is! List || attendees.length > 50) {
        throw const CalendarFailure('Use at most 50 guests.');
      }
      for (final attendee in attendees) {
        if (attendee is! Map ||
            attendee['email'] is! String ||
            !RegExp(
              r'^[^\s@]+@[^\s@]+\.[^\s@]+$',
            ).hasMatch(attendee['email'])) {
          throw const CalendarFailure(
            'Every guest requires a valid email address.',
          );
        }
      }
    }
    if (event.containsKey('recurrence') &&
        (event['recurrence'] is! List ||
            (event['recurrence'] as List).any(
              (r) =>
                  r is! String ||
                  !RegExp(r'^(RRULE|RDATE|EXDATE):').hasMatch(r),
            ))) {
      throw const CalendarFailure('Invalid recurrence rule.');
    }
  }

  Future<Map<String, dynamic>> execute(
    Map<String, dynamic> action, {
    CalendarApproval? approve,
  }) async {
    final id = action['action_id']?.toString() ?? '';
    final fingerprint = jsonEncode(action);
    var sent = false;
    try {
      if (!RegExp(r'^[0-9a-f]{32}$').hasMatch(id)) {
        throw const CalendarFailure('Invalid calendar proposal.');
      }
      final receipt = await readReceipt(id);
      if (receipt != null) {
        if (receipt['fingerprint'] != fingerprint) {
          throw const CalendarFailure(
            'Proposal changed. Ask Jarvis to prepare it again.',
          );
        }
        if (receipt['result'] is Map) {
          return Map<String, dynamic>.from(receipt['result']);
        }
        return {
          'status': 'uncertain',
          'message':
              'This approved operation may already have executed. Check Google Calendar; it will not be repeated automatically.',
        };
      }
      if (!isForeground() || !await isActive()) {
        throw const CalendarFailure(
          'Keep Jarvis open. This request is no longer active.',
        );
      }
      final operation = action['operation'];
      final calendar = (action['calendar_id']?.toString().isNotEmpty ?? false)
          ? action['calendar_id'].toString()
          : action['default_calendar_id']?.toString() ?? 'primary';
      final events = ['calendars', calendar, 'events'];
      Map<String, dynamic> result;
      if (operation == 'calendars') {
        final data = await _request(
          'GET',
          ['users', 'me', 'calendarList'],
          query: {'maxResults': '250'},
        );
        result = {
          'status': 'ok',
          'calendars': [
            for (final c in (data['items'] as List? ?? []))
              {
                for (final k in [
                  'id',
                  'summary',
                  'primary',
                  'accessRole',
                  'timeZone',
                ])
                  if ((c as Map).containsKey(k)) k: c[k],
              },
          ],
          if (data['nextPageToken'] != null)
            'nextPageToken': data['nextPageToken'],
        };
      } else if (operation == 'list') {
        final start = DateTime.tryParse(action['start_at']?.toString() ?? '');
        final end = DateTime.tryParse(action['end_at']?.toString() ?? '');
        if (start == null ||
            end == null ||
            !end.isAfter(start) ||
            end.difference(start).inDays > 366) {
          throw const CalendarFailure(
            'Specify a valid calendar window of at most one year.',
          );
        }
        final data = await _request(
          'GET',
          events,
          query: {
            'timeMin': start.toUtc().toIso8601String(),
            'timeMax': end.toUtc().toIso8601String(),
            'singleEvents': 'true',
            'orderBy': 'startTime',
            'maxResults': '20',
            if (action['query']?.toString().isNotEmpty ?? false)
              'q': action['query'].toString(),
            if (action['page_token']?.toString().isNotEmpty ?? false)
              'pageToken': action['page_token'].toString(),
          },
        );
        result = {
          'status': 'ok',
          'events': [
            for (final e in (data['items'] as List? ?? []))
              _compact(Map<String, dynamic>.from(e)),
          ],
          'timeZone': data['timeZone'],
          if (data['nextPageToken'] != null)
            'nextPageToken': data['nextPageToken'],
        };
      } else if (operation == 'get') {
        result = {
          'status': 'ok',
          'event': _compact(
            await _request('GET', [...events, _eventId(action)]),
          ),
        };
      } else if (['create', 'update', 'delete'].contains(operation)) {
        final old = operation == 'create'
            ? <String, dynamic>{}
            : await _request('GET', [...events, _eventId(action)]);
        if (old['recurrence'] != null && action['whole_series'] != true) {
          throw const CalendarFailure(
            'This ID refers to a whole recurring series. Ask for an occurrence or explicitly request the series.',
          );
        }
        final changes = Map<String, dynamic>.from(
          action['event'] as Map? ?? {},
        );
        if (changes.keys.any((k) => !_fields.contains(k))) {
          throw const CalendarFailure('Unsupported calendar change.');
        }
        // Guest permission flags and RSVP responses cannot be smuggled into a proposal.
        if (changes['attendees'] is List) {
          changes['attendees'] = [
            for (final a in changes['attendees'])
              {'email': (a as Map)['email']},
          ];
        }
        final after = {...old, ...changes};
        if (operation != 'delete') _validateEvent(after);
        if (operation == 'update' && changes.isEmpty) {
          throw const CalendarFailure('No changes were proposed.');
        }
        final details = await _request('GET', [
          'users',
          'me',
          'calendarList',
          calendar,
        ]);
        if (!['owner', 'writer'].contains(details['accessRole'])) {
          throw const CalendarFailure('This Google calendar is read-only.');
        }
        final guests = <String>{
          for (final a in [
            ...(old['attendees'] as List? ?? []),
            ...(after['attendees'] as List? ?? []),
          ])
            if (a is Map && a['email'] != null) a['email'].toString(),
        }.toList();
        final preview = {
          'operation': operation,
          'calendar': details['summary'] ?? calendar,
          'before': _compact(old, preview: true),
          'after': operation == 'delete'
              ? null
              : _compact(after, preview: true),
          'guests': guests,
          'whole_series': old['recurrence'] != null,
          'changed_fields': changes.keys.toList(),
          'calendar_id': calendar,
        };
        if (approve == null || !isForeground() || !await approve(preview)) {
          result = {
            'status': 'declined',
            'message':
                'You did not approve this calendar change. Nothing was changed.',
          };
        } else {
          if (!isForeground() || !await isActive()) {
            throw const CalendarFailure(
              'Approval expired or request was stopped. Nothing was changed.',
            );
          }
          final etag = old['etag']?.toString();
          if (operation != 'create' && (etag == null || etag.isEmpty)) {
            throw const CalendarFailure(
              'Cannot safely change an event without its version.',
            );
          }
          // Persist before sending. If the app dies or response is lost, never replay a mutation.
          await writeReceipt(id, {
            'fingerprint': fingerprint,
            'started_at': DateTime.now().toUtc().toIso8601String(),
          });
          sent = true;
          final saved = await _request(
            operation == 'create'
                ? 'POST'
                : operation == 'update'
                ? 'PATCH'
                : 'DELETE',
            operation == 'create' ? events : [...events, _eventId(action)],
            body: operation == 'delete'
                ? null
                : {...changes, if (operation == 'create') 'id': id},
            etag: etag,
            query: {'sendUpdates': 'all'},
          );
          result = {
            'status': 'ok',
            'operation': operation,
            'event': operation == 'delete'
                ? {'id': action['event_id'], 'summary': old['summary']}
                : _compact(saved),
          };
        }
      } else {
        throw const CalendarFailure('Unsupported Google Calendar operation.');
      }
      await writeReceipt(id, {
        'fingerprint': fingerprint,
        'result': result,
        'saved_at': DateTime.now().toUtc().toIso8601String(),
      });
      return result;
    } catch (error) {
      final result = {
        'status': sent && (error is! CalendarFailure || error.uncertain)
            ? 'uncertain'
            : 'not_executed',
        'message': error is CalendarFailure
            ? error.message
            : sent
            ? 'Google response was interrupted. Check your calendar before trying again; this operation will not be repeated automatically.'
            : 'Calendar connection or device storage is unavailable. Reconnect Google Calendar in Settings.',
      };
      if (id.isNotEmpty) {
        try {
          await writeReceipt(id, {
            'fingerprint': fingerprint,
            'result': result,
          });
        } catch (_) {}
      }
      return result;
    }
  }

  String _eventId(Map<String, dynamic> action) {
    final id = action['event_id']?.toString() ?? '';
    if (id.isEmpty || id.length > 1024) {
      throw const CalendarFailure(
        'A specific event ID from Google is required.',
      );
    }
    return id;
  }
}

class CalendarFailure implements Exception {
  const CalendarFailure(this.message, {this.uncertain = false});
  final String message;
  final bool uncertain;
}
