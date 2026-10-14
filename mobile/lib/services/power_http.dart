import 'dart:convert';
import 'package:http/http.dart' as http;
import 'power_state.dart';
export 'package:http/http.dart'
    hide get, post, put, patch, delete, head, read, readBytes;

/// Every application HTTP connection uses this gate. Power controls alone bypass it.
http.Client powerClient() => _PowerClient();

class MobileSaveException implements Exception {
  final String message;
  const MobileSaveException(this.message);
  @override
  String toString() => message;
}

Future<void> Function(Map<String, dynamic>)? mobileChangesWriter;
Future<void> acceptMobileChanges(Map<String, dynamic> value) async {
  if (value['_mobile_changes'] is Map && mobileChangesWriter != null) {
    await mobileChangesWriter!(
      Map<String, dynamic>.from(value['_mobile_changes']),
    );
  }
}

class _PowerClient extends http.BaseClient {
  final http.Client _inner = http.Client();
  bool _closed = false;
  _PowerClient() {
    PowerState.track(close);
  }
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    if (_closed || !PowerState.enabled.value) {
      throw http.ClientException('Jarvis is powered off.', request.url);
    }
    return _inner.send(request);
  }

  @override
  void close() {
    if (_closed) return;
    _closed = true;
    PowerState.untrack(close);
    _inner.close();
  }
}

Future<http.Response> _request(
  String method,
  Uri url, {
  Map<String, String>? headers,
  Object? body,
  Encoding? encoding,
}) async {
  final client = powerClient();
  try {
    final request = http.Request(method, url)..headers.addAll(headers ?? {});
    if (encoding != null) request.encoding = encoding;
    if (body is String) {
      request.body = body;
    } else if (body is List<int>) {
      request.bodyBytes = body;
    } else if (body is Map) {
      request.bodyFields = body.cast<String, String>();
    } else if (body != null) {
      throw ArgumentError('Unsupported HTTP body');
    }
    final response = await http.Response.fromStream(await client.send(request));
    if (response.statusCode >= 200 &&
        response.statusCode < 300 &&
        response.headers['content-type']?.contains('application/json') ==
            true) {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic>) await acceptMobileChanges(decoded);
    }
    return response;
  } finally {
    client.close();
  }
}

Future<http.Response> get(Uri url, {Map<String, String>? headers}) =>
    _request('GET', url, headers: headers);
Future<http.Response> head(Uri url, {Map<String, String>? headers}) =>
    _request('HEAD', url, headers: headers);
Future<http.Response> post(
  Uri url, {
  Map<String, String>? headers,
  Object? body,
  Encoding? encoding,
}) => _request('POST', url, headers: headers, body: body, encoding: encoding);
Future<http.Response> put(
  Uri url, {
  Map<String, String>? headers,
  Object? body,
  Encoding? encoding,
}) => _request('PUT', url, headers: headers, body: body, encoding: encoding);
Future<http.Response> patch(
  Uri url, {
  Map<String, String>? headers,
  Object? body,
  Encoding? encoding,
}) => _request('PATCH', url, headers: headers, body: body, encoding: encoding);
Future<http.Response> delete(
  Uri url, {
  Map<String, String>? headers,
  Object? body,
  Encoding? encoding,
}) => _request('DELETE', url, headers: headers, body: body, encoding: encoding);
