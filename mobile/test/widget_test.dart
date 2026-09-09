import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/recording_session.dart';
import 'package:jarvis_collector/models/sensor_sample.dart';
import 'package:jarvis_collector/services/feature_extractor.dart';

void main() {
  group('SensorSample Model Tests', () {
    test('toCsvRow generates row matching csvHeader column count', () {
      final sample = SensorSample(
        timestampMs: 1726000000000,
        relativeTimeSec: 1.250,
        accelX: 0.1234,
        accelY: -0.5678,
        accelZ: 9.8100,
        userAccelX: 0.0500,
        userAccelY: -0.1000,
        userAccelZ: 1.2000,
        gyroX: 0.0100,
        gyroY: -0.0200,
        gyroZ: 0.0300,
        latitude: 12.837390,
        longitude: 80.225546,
        altitudeM: 14.5,
        speedMps: 11.2,
        speedKmh: 40.32,
        bearingDeg: 180.0,
        accuracyM: 4.5,
        label: 'HUNTER_350',
        mountPosition: 'HANDLEBAR',
        roadCondition: 'SMOOTH',
      );

      final headerCols = SensorSample.csvHeader.split(',');
      final rowCols = sample.toCsvRow().split(',');

      expect(rowCols.length, equals(headerCols.length));
      expect(sample.toCsvRow(), contains('HUNTER_350'));
      expect(sample.toCsvRow(), contains('HANDLEBAR'));
    });
  });

  group('FeatureExtractor Tests', () {
    test('Calculates dominant frequency and RMS for simulated vibration', () {
      final samples = <SensorSample>[];
      const n = 100;
      const sampleRateHz = 50.0;

      for (var i = 0; i < n; i++) {
        final t = i / sampleRateHz;
        // Inject 12 Hz vibration (characteristic Royal Enfield Hunter 350 band)
        final zSignal = 1.5 * (i % 4 == 0 ? 1.0 : -1.0);

        samples.add(
          SensorSample(
            timestampMs: 1000 + i * 20,
            relativeTimeSec: t,
            accelX: 0.0,
            accelY: 0.0,
            accelZ: 9.81 + zSignal,
            userAccelX: 0.0,
            userAccelY: 0.0,
            userAccelZ: zSignal,
            gyroX: 0.05,
            gyroY: 0.05,
            gyroZ: 0.05,
            latitude: 12.8,
            longitude: 80.2,
            altitudeM: 10.0,
            speedMps: 10.0,
            speedKmh: 36.0,
            bearingDeg: 90.0,
            accuracyM: 5.0,
            label: 'HUNTER_350',
            mountPosition: 'HANDLEBAR',
            roadCondition: 'SMOOTH',
          ),
        );
      }

      final feature = FeatureExtractor.extract(samples, sampleRateHz: sampleRateHz);

      expect(feature.zRms, greaterThan(0.5));
      expect(feature.gyroRms, greaterThan(0.0));
      expect(feature.dominantFreqHz, greaterThan(0.0));
      expect(feature.zeroCrossingRate, greaterThanOrEqualTo(0.0));
      expect(feature.spectralEntropy, greaterThanOrEqualTo(0.0));

      final backendPayload = feature.toBackendFeatureSummary();
      expect(backendPayload.containsKey('dominant_freq_hz'), isTrue);
      expect(backendPayload.containsKey('z_rms'), isTrue);
      expect(backendPayload.containsKey('spectral_energy'), isTrue);
      expect(backendPayload.containsKey('zero_crossing_rate'), isTrue);
      expect(backendPayload.containsKey('spectral_entropy'), isTrue);
    });
  });

  group('RecordingSession Model Tests', () {
    test('Formats file sizes and durations properly', () {
      final session = RecordingSession(
        id: 'rec_test_001',
        startTime: DateTime(2026, 9, 7, 10, 0, 0),
        endTime: DateTime(2026, 9, 7, 10, 2, 30),
        label: 'HUNTER_350',
        mountPosition: 'HANDLEBAR',
        roadCondition: 'SMOOTH',
        sampleCount: 7500,
        durationSeconds: 150.0,
        csvFilePath: '/storage/rec_test_001.csv',
        jsonFilePath: '/storage/rec_test_001_summary.json',
        csvSizeBytes: 1024 * 512, // 512 KB
      );

      expect(session.formattedDuration, equals('02:30'));
      expect(session.formattedSize, equals('512.0 KB'));
      expect(session.toJson()['label'], equals('HUNTER_350'));
    });
  });
}
