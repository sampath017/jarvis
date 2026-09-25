import 'package:latlong2/latlong.dart';

import 'activity_day.dart';

/// Location evidence, with repeated fixes deduplicated and gaps left intact.
class ActivityMapData {
  ActivityMapData(List<ActivityObservation> observations) {
    final ordered = [...observations]
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    final seen = <String>{};
    ActivityObservation? previous;
    var segment = <ActivityObservation>[];
    void finish() {
      if (segment.length > 1) links.add(segment);
      segment = [];
    }

    for (final point in ordered) {
      if (!point.hasLocation) {
        if (point.wifiSignals > 0) wifiWithoutCoordinates++;
        finish();
        previous = null;
        continue;
      }
      final key = fixKey(point);
      if (!seen.add(key)) {
        // A repeated location does not fill a missing interval or prove movement.
        if (previous != null && previous.activity != point.activity) {
          finish();
          previous = null;
        }
        continue;
      }
      fixes.add(point);
      if (previous == null || !canLink(previous, point)) finish();
      segment.add(point);
      previous = point;
    }
    finish();
  }

  final List<ActivityObservation> fixes = [];
  final List<List<ActivityObservation>> links = [];
  int wifiWithoutCoordinates = 0;

  static DateTime fixTime(ActivityObservation p) =>
      p.locationObservedAt ?? p.timestamp;

  static String fixKey(ActivityObservation p) =>
      '${fixTime(p).toUtc().toIso8601String()}:${p.latitude}:${p.longitude}';

  static bool isPrecise(ActivityObservation p) =>
      p.accuracyMeters != null &&
      p.accuracyMeters!.isFinite &&
      p.accuracyMeters! > 0 &&
      p.accuracyMeters! <= 100;

  static bool canLink(ActivityObservation a, ActivityObservation b) {
    if (a.sessionId == null ||
        a.sessionId != b.sessionId ||
        a.activity != b.activity ||
        !isPrecise(a) ||
        !isPrecise(b)) {
      return false;
    }
    final maxSpeed = switch (a.activity.toUpperCase()) {
      'WALKING' || 'ON_FOOT' => 8.0,
      'RUNNING' => 12.0,
      'ON_BICYCLE' || 'CYCLING' => 20.0,
      'IN_VEHICLE' => 70.0,
      _ => 0.0,
    };
    final seconds = fixTime(b).difference(fixTime(a)).inMilliseconds / 1000;
    if (maxSpeed == 0 || seconds <= 0 || seconds > 180) return false;
    final distance = const Distance().as(
      LengthUnit.Meter,
      LatLng(a.latitude!, a.longitude!),
      LatLng(b.latitude!, b.longitude!),
    );
    final uncertainty = a.accuracyMeters! + b.accuracyMeters!;
    // Avoid drawing GPS jitter as travel, and reject implausible jumps.
    return distance > uncertainty / 2 &&
        (distance - uncertainty).clamp(0, double.infinity) / seconds <=
            maxSpeed;
  }
}
