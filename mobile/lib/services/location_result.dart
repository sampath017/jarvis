/// A device-reported failure, kept separate from AI/provider limits.
class LocationReadFailure implements Exception {
  const LocationReadFailure(this.code, this.message);
  final String code;
  final String message;
}

Future<Map<String, dynamic>> readLocationResult(
  Future<Map<String, double>?> Function()? reader,
) async {
  try {
    if (reader == null) {
      return {
        'status': 'unavailable',
        'reason': 'reader_unavailable',
        'message':
            'The phone location reader is not ready. Reopen Jarvis and try again.',
      };
    }
    final gps = await reader();
    if (gps == null) {
      return {
        'status': 'unavailable',
        'reason': 'no_fix',
        'message':
            'The phone could not obtain a recent location fix. This does not establish that GPS is off.',
      };
    }
    final timestamp = gps['timestamp_ms'];
    return {
      'status': 'ok',
      'gps': {...gps}..remove('timestamp_ms'),
      'observed_at':
          (timestamp == null
                  ? DateTime.now()
                  : DateTime.fromMillisecondsSinceEpoch(timestamp.round()))
              .toUtc()
              .toIso8601String(),
    };
  } on LocationReadFailure catch (error) {
    return {
      'status': 'unavailable',
      'reason': error.code,
      'message': error.message,
    };
  } catch (_) {
    return {
      'status': 'unavailable',
      'reason': 'read_failed',
      'message':
          'The phone location request failed. Try again; the cause could not be confirmed.',
    };
  }
}
