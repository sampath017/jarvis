/// A single timestamped multi-sensor reading captured from the device.
class SensorSample {
  final int timestampMs; // Epoch milliseconds
  final double relativeTimeSec; // Seconds since session start

  // Raw Accelerometer (includes gravity) in m/s^2
  final double accelX;
  final double accelY;
  final double accelZ;

  // User Accelerometer (linear motion without gravity) in m/s^2
  final double userAccelX;
  final double userAccelY;
  final double userAccelZ;

  // Gyroscope in rad/s
  final double gyroX;
  final double gyroY;
  final double gyroZ;

  // GPS Location & Kinematics
  final double latitude;
  final double longitude;
  final double altitudeM;
  final double speedMps;
  final double speedKmh;
  final double bearingDeg;
  final double accuracyM;

  // Automatic Context Grounding (BRD Auto-classification)
  final String label;
  final String mountPosition;
  final String roadCondition;

  SensorSample({
    required this.timestampMs,
    required this.relativeTimeSec,
    required this.accelX,
    required this.accelY,
    required this.accelZ,
    required this.userAccelX,
    required this.userAccelY,
    required this.userAccelZ,
    required this.gyroX,
    required this.gyroY,
    required this.gyroZ,
    required this.latitude,
    required this.longitude,
    required this.altitudeM,
    required this.speedMps,
    required this.speedKmh,
    required this.bearingDeg,
    required this.accuracyM,
    this.label = 'AUTO',
    this.mountPosition = 'POCKET_OR_MOUNT',
    this.roadCondition = 'NORMAL',
  });

  /// Standard CSV header row for machine learning training datasets.
  static const String csvHeader =
      'timestamp_ms,relative_sec,accel_x,accel_y,accel_z,'
      'user_accel_x,user_accel_y,user_accel_z,gyro_x,gyro_y,gyro_z,'
      'latitude,longitude,altitude_m,speed_mps,speed_kmh,bearing_deg,accuracy_m,'
      'label,mount_position,road_condition';

  /// Serialize to a single comma-separated row.
  String toCsvRow() {
    return '$timestampMs,'
        '${relativeTimeSec.toStringAsFixed(3)},'
        '${accelX.toStringAsFixed(4)},${accelY.toStringAsFixed(4)},${accelZ.toStringAsFixed(4)},'
        '${userAccelX.toStringAsFixed(4)},${userAccelY.toStringAsFixed(4)},${userAccelZ.toStringAsFixed(4)},'
        '${gyroX.toStringAsFixed(4)},${gyroY.toStringAsFixed(4)},${gyroZ.toStringAsFixed(4)},'
        '${latitude.toStringAsFixed(6)},${longitude.toStringAsFixed(6)},${altitudeM.toStringAsFixed(2)},'
        '${speedMps.toStringAsFixed(2)},${speedKmh.toStringAsFixed(2)},${bearingDeg.toStringAsFixed(1)},${accuracyM.toStringAsFixed(1)},'
        '"$label","$mountPosition","$roadCondition"';
  }

  Map<String, dynamic> toJson() => {
        'timestamp_ms': timestampMs,
        'relative_sec': relativeTimeSec,
        'accel': {'x': accelX, 'y': accelY, 'z': accelZ},
        'user_accel': {'x': userAccelX, 'y': userAccelY, 'z': userAccelZ},
        'gyro': {'x': gyroX, 'y': gyroY, 'z': gyroZ},
        'gps': {
          'latitude': latitude,
          'longitude': longitude,
          'altitude_m': altitudeM,
          'speed_mps': speedMps,
          'speed_kmh': speedKmh,
          'bearing_deg': bearingDeg,
          'accuracy_m': accuracyM,
        },
        'metadata': {
          'label': label,
          'mount_position': mountPosition,
          'road_condition': roadCondition,
        },
      };
}
