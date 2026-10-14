import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/painting.dart' show Offset;

import 'api_service.dart';
import 'power_http.dart' as http;

/// A data-only map card. It cannot supply URLs, provider keys or executable code.
class SatelliteMapData {
  const SatelliteMapData({
    required this.latitude,
    required this.longitude,
    this.placeName = '',
    this.placeId = '',
    this.zoom = 19,
    this.polygon = const [],
    this.confidence,
    this.uncertaintyMetres,
  });

  final double latitude, longitude;
  final String placeName, placeId;
  final int zoom;
  final List<({double latitude, double longitude})> polygon;
  final double? confidence, uncertaintyMetres;
  String get imageKey => '$latitude,$longitude,$zoom';

  /// Resolve an existing departure reminder without rewriting its policy or
  /// choosing an arbitrary boundary when saved-place names are ambiguous.
  static SatelliteMapData? fromReminder(
    Map<String, dynamic> reminder,
    List<Map<String, dynamic>> places,
  ) {
    try {
      final raw = reminder['dynamic_policy'];
      final policy = raw is String ? jsonDecode(raw) : raw;
      if (policy is! Map ||
          policy['trigger'] != 'exit' ||
          policy['origin'] is! Map) {
        return null;
      }
      final origin = policy['origin'] as Map;
      final id = origin['place_id'];
      final name = origin['name']?.toString() ?? '';
      final matches = places
          .where(
            (place) => id != null
                ? place['id'] == id
                : name.isNotEmpty &&
                      place['name']?.toString().toLowerCase() ==
                          name.toLowerCase(),
          )
          .toList();
      Object? boundary;
      if (matches.length == 1) {
        final raw = matches.single['boundary_json'];
        try {
          boundary = raw is String ? jsonDecode(raw) : raw;
        } on FormatException {
          boundary = null;
        }
      }
      final card = <String, dynamic>{
        'latitude': origin['latitude'],
        'longitude': origin['longitude'],
        'place_name': name,
        'place_id':
            id ?? (matches.length == 1 ? matches.single['id'] : '') ?? '',
      };
      // A malformed estimate must not prevent access to the original map.
      if (boundary is Map) {
        final imagery = boundary['imagery'];
        final zoom = imagery is Map ? imagery['zoom'] : null;
        if (zoom is int && zoom >= 18 && zoom <= 21) {
          card['zoom'] = zoom;
        }
        final estimated = tryParse(jsonEncode({...card, 'boundary': boundary}));
        if (estimated != null) return estimated;
      }
      return tryParse(jsonEncode(card));
    } on FormatException {
      return null;
    }
  }

  static SatelliteMapData? tryParse(String source) {
    if (source.length > 16000) return null;
    try {
      final value = jsonDecode(source);
      if (value is! Map ||
          !_coordinate(value['latitude'], 85) ||
          !_coordinate(value['longitude'], 180)) {
        return null;
      }
      final zoom = value['zoom'] ?? 19;
      final name = value['place_name'] ?? '';
      final id = value['place_id'] ?? '';
      if (zoom is! int ||
          zoom < 18 ||
          zoom > 21 ||
          name is! String ||
          name.length > 160 ||
          id is! String ||
          id.length > 160) {
        return null;
      }
      final boundary = value['boundary'];
      if (boundary != null && boundary is! Map) return null;
      final points = boundary?['polygon'] ?? value['polygon'] ?? const [];
      if (points is! List ||
          points.length > 64 ||
          (points.isNotEmpty && points.length < 3)) {
        return null;
      }
      final polygon = <({double latitude, double longitude})>[];
      for (final point in points) {
        if (point is! Map ||
            !_coordinate(point['latitude'], 85) ||
            !_coordinate(point['longitude'], 180)) {
          return null;
        }
        polygon.add((
          latitude: (point['latitude'] as num).toDouble(),
          longitude: (point['longitude'] as num).toDouble(),
        ));
      }
      final confidence = boundary?['confidence'] ?? value['confidence'];
      final uncertainty = boundary?['uncertainty_m'] ?? value['uncertainty_m'];
      if (confidence != null &&
          (confidence is! num ||
              !confidence.isFinite ||
              confidence < 0 ||
              confidence > 1)) {
        return null;
      }
      if (uncertainty != null &&
          (uncertainty is! num ||
              !uncertainty.isFinite ||
              uncertainty < 0 ||
              uncertainty > 1000)) {
        return null;
      }
      return SatelliteMapData(
        latitude: (value['latitude'] as num).toDouble(),
        longitude: (value['longitude'] as num).toDouble(),
        placeName: name,
        placeId: id,
        zoom: zoom,
        polygon: List.unmodifiable(polygon),
        confidence: (confidence as num?)?.toDouble(),
        uncertaintyMetres: (uncertainty as num?)?.toDouble(),
      );
    } on FormatException {
      return null;
    }
  }

  static bool _coordinate(Object? value, double limit) =>
      value is num && value.isFinite && value.abs() <= limit;

  /// Static Maps covers 640 logical pixels at scale=2, returning 1280 pixels.
  /// Both the image and its overlays are scaled together to the displayed square.
  Offset project(double latitude, double longitude, double displaySize) {
    final centre = _world(this.latitude, this.longitude);
    final point = _world(latitude, longitude);
    var dx = point.dx - centre.dx;
    if (dx > 0.5) dx -= 1;
    if (dx < -0.5) dx += 1;
    final worldPixels = 256 * math.pow(2, zoom);
    return Offset(
      (320 + dx * worldPixels) / 640 * displaySize,
      (320 + (point.dy - centre.dy) * worldPixels) / 640 * displaySize,
    );
  }

  static Offset _world(double latitude, double longitude) {
    final sine = math.sin(latitude * math.pi / 180);
    return Offset(
      (longitude + 180) / 360,
      0.5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi),
    );
  }
}

class SatelliteMapException implements Exception {
  const SatelliteMapException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Provider imagery is requested through the configured API and kept in RAM only.
class SatelliteMapService {
  static Future<Uint8List> load(
    SatelliteMapData data, {
    http.Client? client,
    String? baseUrl,
    String? userId,
  }) async {
    final endpoint = baseUrl ?? ApiService().baseUrl;
    final user = userId ?? ApiService().userId;
    final owned = client == null;
    final transport = client ?? http.powerClient();
    try {
      final response = await transport
          .post(
            Uri.parse('$endpoint/mobile/satellite-map'),
            headers: {'Content-Type': 'application/json', 'X-User-ID': user},
            body: jsonEncode({
              'latitude': data.latitude,
              'longitude': data.longitude,
              'zoom': data.zoom,
            }),
          )
          .timeout(const Duration(seconds: 25));
      if (response.statusCode != 200) {
        throw const SatelliteMapException(
          'Satellite image is unavailable. Try again.',
        );
      }
      final bytes = response.bodyBytes;
      final contentType = response.headers['content-type'] ?? '';
      const signature = [137, 80, 78, 71, 13, 10, 26, 10];
      if (!contentType.startsWith('image/png') ||
          bytes.length < 24 ||
          bytes.length > 8 * 1024 * 1024 ||
          List.generate(8, (i) => bytes[i] == signature[i]).any((v) => !v)) {
        throw const SatelliteMapException(
          'The map service returned an invalid image.',
        );
      }
      // Reject oversized or differently shaped images before decoding them.
      final header = ByteData.sublistView(bytes);
      if (header.getUint32(16) != 1280 || header.getUint32(20) != 1280) {
        throw const SatelliteMapException(
          'The map service returned an unexpected image size.',
        );
      }
      return bytes;
    } on SatelliteMapException {
      rethrow;
    } catch (_) {
      throw const SatelliteMapException(
        'Could not load the satellite image. Try again.',
      );
    } finally {
      if (owned) transport.close();
    }
  }
}
