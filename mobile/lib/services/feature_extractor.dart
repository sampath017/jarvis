import 'dart:math' as math;
import '../models/feature_vector.dart';
import '../models/sensor_sample.dart';

/// On-device edge feature extraction for IMU data per BRD Stage 3.
/// Calculates dominant vibration frequency, RMS energy, zero-crossing rate, and spectral entropy.
class FeatureExtractor {
  static const double gravityMps2 = 9.80665;

  /// Extract feature vector from a window of samples (recommended 100 to 250 samples).
  static FeatureVector extract(
    List<SensorSample> window, {
    double sampleRateHz = 50.0,
  }) {
    if (window.isEmpty) {
      return FeatureVector(
        dominantFreqHz: 0.0,
        spectralEnergy: 0.0,
        spectralEntropy: 0.0,
        zeroCrossingRate: 0.0,
        zRms: 0.0,
        harmonicRatio: 0.0,
        accelMagnitudeMean: 0.0,
        motionRms: 0.0,
        gyroRms: 0.0,
        vehicleClassHint: 'STANDBY',
        classificationConfidence: 0.0,
        speedKmh: 0.0,
        computedAt: DateTime.now(),
      );
    }

    final n = window.length;

    // 1. Z-axis without gravity (userAccelZ)
    final zSamples = window.map((s) => s.userAccelZ).toList();
    final centeredZ = _center(zSamples);

    // 2. Dominant frequency via Discrete Fourier Transform
    final dftResult = _dominantFrequencyBin(centeredZ);
    final dominantBin = dftResult.bin;
    final dominantEnergy = dftResult.energy;
    final dominantFreqHz = dominantBin * sampleRateHz / n;

    // 3. Second harmonic energy (2 * dominant frequency)
    final harmonicEnergy = _energyAtBin(centeredZ, dominantBin * 2);
    final harmonicRatio =
        dominantEnergy > 0 ? harmonicEnergy / dominantEnergy : 0.0;

    // 4. Mean acceleration magnitude (including gravity)
    final totalMagnitude = window.fold<double>(
      0.0,
      (sum, s) =>
          sum +
          math.sqrt(
            s.accelX * s.accelX + s.accelY * s.accelY + s.accelZ * s.accelZ,
          ),
    );
    final accelMagnitudeMean = totalMagnitude / n;

    // 5. Z-axis RMS & Spectral Energy
    final spectralEnergy = _meanSquare(centeredZ);
    final zRms = math.sqrt(spectralEnergy);

    // 6. Zero-Crossing Rate (ZCR)
    final zeroCrossingRate = _calculateZeroCrossingRate(centeredZ);

    // 7. Spectral Entropy
    final spectralEntropy = _calculateSpectralEntropy(centeredZ);

    // 8. Gyroscope RMS
    final gyroTotal = window.fold<double>(
      0.0,
      (sum, s) =>
          sum +
          (s.gyroX * s.gyroX + s.gyroY * s.gyroY + s.gyroZ * s.gyroZ) / 3.0,
    );
    final gyroRms = math.sqrt(gyroTotal / n);

    // 9. Motion RMS (overall linear movement)
    final motionTotal = window.fold<double>(
      0.0,
      (sum, s) =>
          sum +
          (s.userAccelX * s.userAccelX +
              s.userAccelY * s.userAccelY +
              s.userAccelZ * s.userAccelZ) /
              3.0,
    );
    final motionRms = math.sqrt(motionTotal / n);

    final avgSpeedKmh =
        window.fold<double>(0.0, (sum, s) => sum + s.speedKmh) / n;

    // 10. Vehicle classification heuristic hint
    final classification = _classifyHeuristic(
      dominantFreqHz: dominantFreqHz,
      zRms: zRms,
      gyroRms: gyroRms,
      speedKmh: avgSpeedKmh,
      spectralEntropy: spectralEntropy,
    );

    return FeatureVector(
      dominantFreqHz: dominantFreqHz,
      spectralEnergy: spectralEnergy,
      spectralEntropy: spectralEntropy,
      zeroCrossingRate: zeroCrossingRate,
      zRms: zRms,
      harmonicRatio: harmonicRatio,
      accelMagnitudeMean: accelMagnitudeMean,
      motionRms: motionRms,
      gyroRms: gyroRms,
      vehicleClassHint: classification.hint,
      classificationConfidence: classification.confidence,
      speedKmh: avgSpeedKmh,
      computedAt: DateTime.now(),
    );
  }

  static List<double> _center(List<double> values) {
    if (values.isEmpty) return [];
    final mean = values.reduce((a, b) => a + b) / values.length;
    return values.map((v) => v - mean).toList();
  }

  static double _meanSquare(List<double> values) {
    if (values.isEmpty) return 0.0;
    return values.fold<double>(0.0, (sum, v) => sum + v * v) / values.length;
  }

  static double _calculateZeroCrossingRate(List<double> centeredSamples) {
    if (centeredSamples.length < 2) return 0.0;
    var crossings = 0;
    for (var i = 1; i < centeredSamples.length; i++) {
      if ((centeredSamples[i] >= 0 && centeredSamples[i - 1] < 0) ||
          (centeredSamples[i] < 0 && centeredSamples[i - 1] >= 0)) {
        crossings++;
      }
    }
    return crossings / (centeredSamples.length - 1);
  }

  static double _calculateSpectralEntropy(List<double> centeredSamples) {
    final n = centeredSamples.length;
    final maxBin = n ~/ 2;
    if (maxBin < 2) return 0.0;

    final energies = <double>[];
    var totalEnergy = 0.0;

    for (var bin = 1; bin < maxBin; bin++) {
      final e = _energyAtBin(centeredSamples, bin);
      energies.add(e);
      totalEnergy += e;
    }

    if (totalEnergy <= 1e-9) return 0.0;

    var entropy = 0.0;
    for (final e in energies) {
      if (e > 0.0) {
        final p = e / totalEnergy;
        if (p > 1e-12) {
          entropy -= p * (math.log(p) / math.ln2);
        }
      }
    }

    final maxEntropy = math.log(energies.length) / math.ln2;
    return maxEntropy > 0 ? (entropy / maxEntropy).clamp(0.0, 1.0) : 0.0;
  }

  static double _energyAtBin(List<double> samples, int binIndex) {
    final n = samples.length;
    if (binIndex < 1 || binIndex >= n ~/ 2) return 0.0;

    final angle = -2.0 * math.pi * binIndex / n;
    var real = 0.0;
    var imag = 0.0;

    for (var i = 0; i < n; i++) {
      final a = angle * i;
      real += samples[i] * math.cos(a);
      imag += samples[i] * math.sin(a);
    }

    return real * real + imag * imag;
  }

  static ({int bin, double energy}) _dominantFrequencyBin(
      List<double> samples) {
    final n = samples.length;
    if (n < 4) return (bin: 0, energy: 0.0);

    var maxBin = 0;
    var maxEnergy = 0.0;

    // Scan frequencies between 1 Hz and 25 Hz (assuming 50 Hz sampling)
    final maxSearchBin = n ~/ 2;
    for (var bin = 1; bin < maxSearchBin; bin++) {
      final energy = _energyAtBin(samples, bin);
      if (energy > maxEnergy) {
        maxEnergy = energy;
        maxBin = bin;
      }
    }

    return (bin: maxBin, energy: maxEnergy);
  }

  static ({String hint, double confidence}) _classifyHeuristic({
    required double dominantFreqHz,
    required double zRms,
    required double gyroRms,
    required double speedKmh,
    required double spectralEntropy,
  }) {
    // Stationary / Desk
    if (speedKmh < 1.5 && zRms < 0.15 && gyroRms < 0.1) {
      return (hint: 'STATIONARY', confidence: 0.95);
    }

    // Walking / Running (1.5 - 3.2 Hz cadence)
    if (speedKmh < 8.0 &&
        dominantFreqHz >= 1.4 &&
        dominantFreqHz <= 3.2 &&
        zRms > 0.4) {
      return (hint: 'WALKING', confidence: 0.88);
    }

    // Royal Enfield Hunter 350 characteristic single-cylinder idle/cruise: 10 - 15 Hz with high Z-RMS
    if (dominantFreqHz >= 9.5 && dominantFreqHz <= 16.0 && zRms > 0.6) {
      final confidence = (zRms > 1.0) ? 0.95 : 0.85;
      return (hint: 'HUNTER_350', confidence: confidence);
    }

    // Car / Taxi: Smoother vibration, lower frequency or low RMS
    if (speedKmh > 15.0 && zRms < 0.55 && dominantFreqHz < 9.0) {
      return (hint: 'CAR', confidence: 0.80);
    }

    // Bus / Heavy vehicle: Low frequency rumble (4-8 Hz) with moderate RMS
    if (speedKmh > 10.0 && dominantFreqHz >= 4.0 && dominantFreqHz <= 8.5) {
      return (hint: 'BUS', confidence: 0.75);
    }

    // Generic vehicle in motion
    if (speedKmh > 10.0) {
      return (hint: 'IN_VEHICLE', confidence: 0.65);
    }

    return (hint: 'UNKNOWN', confidence: 0.40);
  }
}
