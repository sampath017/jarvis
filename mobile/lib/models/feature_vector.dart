/// Extracted feature vector from a time-series window of real IMU telemetry.
/// Matches the schema expected by the Jarvis context engine and BRD requirements.
class FeatureVector {
  final double dominantFreqHz;
  final double spectralEnergy;
  final double spectralEntropy;
  final double zeroCrossingRate;
  final double zRms;
  final double harmonicRatio;
  final double accelMagnitudeMean;
  final double motionRms;
  final double gyroRms;
  final String vehicleClassHint;
  final double classificationConfidence;
  final double speedKmh;
  final DateTime computedAt;

  FeatureVector({
    required this.dominantFreqHz,
    required this.spectralEnergy,
    this.spectralEntropy = 0.0,
    this.zeroCrossingRate = 0.0,
    required this.zRms,
    required this.harmonicRatio,
    required this.accelMagnitudeMean,
    required this.motionRms,
    required this.gyroRms,
    required this.vehicleClassHint,
    required this.classificationConfidence,
    required this.speedKmh,
    required this.computedAt,
  });

  /// Feature vector matching Jarvis backend FeatureSummary model and BRD Section 7.2.
  Map<String, dynamic> toBackendFeatureSummary() => {
        'dominant_freq_hz': double.parse(dominantFreqHz.toStringAsFixed(3)),
        'spectral_energy': double.parse(spectralEnergy.toStringAsFixed(4)),
        'spectral_entropy': double.parse(spectralEntropy.toStringAsFixed(4)),
        'zero_crossing_rate': double.parse(zeroCrossingRate.toStringAsFixed(4)),
        'z_rms': double.parse(zRms.toStringAsFixed(4)),
        'harmonic_ratio': double.parse(harmonicRatio.toStringAsFixed(4)),
        'accel_magnitude_mean':
            double.parse(accelMagnitudeMean.toStringAsFixed(4)),
        'motion_rms': double.parse(motionRms.toStringAsFixed(4)),
        'gyro_rms': double.parse(gyroRms.toStringAsFixed(4)),
        'vehicle_class_hint': vehicleClassHint,
        'classification_confidence':
            double.parse(classificationConfidence.toStringAsFixed(2)),
      };

  Map<String, dynamic> toJson() => {
        ...toBackendFeatureSummary(),
        'speed_kmh': double.parse(speedKmh.toStringAsFixed(2)),
        'computed_at': computedAt.toIso8601String(),
      };
}
