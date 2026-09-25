import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../models/recording_session.dart';
import 'api_service.dart';
import 'session_storage_service.dart';

class RecordingBackupService {
  static final Map<String, Future<void>> _uploads = {};
  static Future<void>? _sync;
  static DateTime? _lastAttempt;
  Future<void> syncPending() async {
    if (_sync != null ||
        (_lastAttempt != null &&
            DateTime.now().difference(_lastAttempt!) <
                const Duration(minutes: 2))) {
      return;
    }
    _lastAttempt = DateTime.now();
    _sync = _syncPending();
    try {
      await _sync;
    } finally {
      _sync = null;
    }
  }

  Future<void> _syncPending() async {
    try {
      final local = await SessionStorageService.listSessions();
      if (local.isEmpty) return;
      final remote = (await list()).map((s) => s.id).toSet();
      for (final session in local) {
        if (session.csvSizeBytes > 128 * 1024 * 1024) continue;
        if (!remote.contains(session.id)) {
          try {
            await backup(session);
          } catch (_) {
            /* Retain the file and retry next cycle. */
          }
        }
      }
    } catch (_) {
      /* Offline: next sync retries. */
    }
  }

  late final _api = ApiService();
  Uri _url(String path) =>
      Uri.parse('${_api.baseUrl}/session-library/recordings$path');
  Map<String, String> get _headers => {'X-User-ID': _api.userId};
  Future<List<RecordingSession>> list() async {
    final response = await http
        .get(_url(''), headers: _headers)
        .timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception('Cloud library unavailable');
    }
    return [
      for (final item in jsonDecode(response.body)['items'])
        RecordingSession.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<void> backup(RecordingSession session) => _uploads[session.id] ??=
      _upload(session).whenComplete(() => _uploads.remove(session.id));
  Future<void> _upload(RecordingSession session) async {
    final csvLength = await File(session.csvFilePath).length();
    if (csvLength != session.csvSizeBytes) {
      throw Exception('Recording file is incomplete');
    }
    for (final kind in ['csv', 'json']) {
      final file = File(
        kind == 'csv' ? session.csvFilePath : session.jsonFilePath,
      );
      final length = await file.length();
      if (length > 128 * 1024 * 1024) {
        throw Exception('Recording exceeds the 128 MB backup limit');
      }
      final request = http.StreamedRequest(
        'PUT',
        _url('/${Uri.encodeComponent(session.id)}/files/$kind'),
      );
      request.headers.addAll(_headers);
      request.contentLength = length;
      final client = http.Client();
      try {
        final responseFuture = client
            .send(request)
            .timeout(const Duration(minutes: 8));
        await request.sink.addStream(file.openRead());
        await request.sink.close();
        final response = await responseFuture;
        await response.stream.drain<void>();
        if (response.statusCode != 200) {
          throw Exception('Recording upload failed');
        }
      } finally {
        client.close();
      }
    }
    final response = await http
        .put(
          _url(''),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode(session.toJson()),
        )
        .timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) {
      throw Exception('Could not confirm backup');
    }
  }

  Future<RecordingSession> restore(RecordingSession session) async {
    final dir = await SessionStorageService.getStorageDir();
    final safeId = base64Url
        .encode(utf8.encode(session.id))
        .replaceAll('=', '');
    final csv = File('${dir.path}/restored_$safeId.csv');
    final json = File('${dir.path}/restored_${safeId}_summary.json');
    for (final kind in ['csv', 'json']) {
      final target = kind == 'csv' ? csv : json;
      final temporary = File('${target.path}.part');
      final client = http.Client();
      try {
        final request = http.Request(
          'GET',
          _url('/${Uri.encodeComponent(session.id)}/files/$kind'),
        )..headers.addAll(_headers);
        final response = await client
            .send(request)
            .timeout(const Duration(seconds: 30));
        if (response.statusCode != 200) throw Exception('Download failed');
        await response.stream
            .timeout(const Duration(seconds: 60))
            .pipe(temporary.openWrite());
        if (kind == 'csv' && await temporary.length() != session.csvSizeBytes) {
          throw Exception('Incomplete download');
        }
        if (kind == 'json') {
          final data = Map<String, dynamic>.from(
            jsonDecode(await temporary.readAsString()),
          );
          data['csv_file_path'] = csv.path;
          data['json_file_path'] = json.path;
          await temporary.writeAsString(jsonEncode(data));
        }
        await temporary.rename(target.path);
      } finally {
        client.close();
        if (await temporary.exists()) await temporary.delete();
      }
    }
    return RecordingSession.fromJson(
      Map<String, dynamic>.from(jsonDecode(await json.readAsString())),
    );
  }
}
