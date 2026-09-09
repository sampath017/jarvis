import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:intl/intl.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../models/feature_vector.dart';
import '../models/recording_session.dart';
import '../models/sensor_sample.dart';
import 'api_service.dart';
import 'feature_extractor.dart';
import 'session_storage_service.dart';

/// Central service that captures IMU and GPS sensors on demand,
/// runs Android foreground service for background collection,
/// and writes high-frequency CSV logs alongside compact low-telemetry JSON metadata.
///
/// Remains completely dormant (sensors powered off) when not recording.
class SensorService extends ChangeNotifier {
  static const _channel = MethodChannel('com.jarvis/foreground_service');

  // ── Recording State ────────────────────────────────────────────────────────
  bool _isRecording = false;
  bool get isRecording => _isRecording;

  int _sampleCount = 0;
  int get sampleCount => _sampleCount;

  double _recordingDurationSec = 0.0;
  double get recordingDurationSec => _recordingDurationSec;

  DateTime? _sessionStartTime;
  String? _currentSessionId;
  String? get currentSessionId => _currentSessionId;

  // ── Stage 1 Tripwire State ──────────────────────────────────────────────────
  bool _isTripwireActive = false;
  bool get isTripwireActive => _isTripwireActive;

  String? _lastActivityTransition;
  String? get lastActivityTransition => _lastActivityTransition;
  DateTime? _lastActivityTransitionTime;
  DateTime? get lastActivityTransitionTime => _lastActivityTransitionTime;

  // File handles during active recording
  File? _currentCsvFile;
  File? _currentJsonFile;
  IOSink? _currentCsvSink;

  // ── Live Telemetry Buffers ──────────────────────────────────────────────────
  double _rawAx = 0.0, _rawAy = 0.0, _rawAz = 9.81;
  double _userAx = 0.0, _userAy = 0.0, _userAz = 0.0;
  double _gyroX = 0.0, _gyroY = 0.0, _gyroZ = 0.0;

  double _lat = 0.0, _lon = 0.0, _alt = 0.0;
  double _speedMps = 0.0, _speedKmh = 0.0;
  double _bearing = 0.0, _accuracy = 0.0;
  bool _hasGpsFix = false;

  // ── Low-Telemetry Journey GPS Metrics ──────────────────────────────────────
  double _sessionDistanceMeters = 0.0;
  double get sessionDistanceMeters => _sessionDistanceMeters;

  double _sessionMaxSpeedKmh = 0.0;
  double get sessionMaxSpeedKmh => _sessionMaxSpeedKmh;

  double _sessionSpeedSumKmh = 0.0;
  int _sessionGpsFixCount = 0;
  double get sessionAvgSpeedKmh => _sessionGpsFixCount > 0
      ? _sessionSpeedSumKmh / _sessionGpsFixCount
      : 0.0;

  double? _prevGpsLat, _prevGpsLon;
  Map<String, dynamic>? _startGpsReading;
  Map<String, dynamic>? _latestGpsReading;
  double? _minLat, _maxLat, _minLon, _maxLon;
  final List<Map<String, dynamic>> _trajectoryCheckpoints = [];
  DateTime? _lastCheckpointTime;

  // Public Getters
  double get rawAx => _rawAx;
  double get rawAy => _rawAy;
  double get rawAz => _rawAz;
  double get userAx => _userAx;
  double get userAy => _userAy;
  double get userAz => _userAz;
  double get gyroX => _gyroX;
  double get gyroY => _gyroY;
  double get gyroZ => _gyroZ;

  double get lat => _lat;
  double get lon => _lon;
  double get alt => _alt;
  double get speedMps => _speedMps;
  double get speedKmh => _speedKmh;
  double get bearing => _bearing;
  double get accuracy => _accuracy;
  bool get hasGpsFix => _hasGpsFix;

  SensorSample? _latestSample;
  SensorSample? get latestSample => _latestSample;

  FeatureVector? _latestFeature;
  FeatureVector? get latestFeature => _latestFeature;

  // Rolling buffer for live waveforms & real-time feature extraction (max 120 items)
  final List<SensorSample> _recentSamples = [];
  List<SensorSample> get recentSamples => List.unmodifiable(_recentSamples);

  // Stream Subscriptions & Timers
  StreamSubscription<AccelerometerEvent>? _accelSub;
  StreamSubscription<UserAccelerometerEvent>? _userAccelSub;
  StreamSubscription<GyroscopeEvent>? _gyroSub;
  StreamSubscription<Position>? _gpsSub;
  Timer? _durationTimer;
  Timer? _featureTimer;
  Timer? _liveUiTicker;

  // ── Lifecycle & Initialization ─────────────────────────────────────────────
  Future<void> initialize() async {
    // Register native method channel callbacks (e.g. Activity Recognition transitions)
    _channel.setMethodCallHandler(_handleNativeCall);
    // Only check permissions on launch.
    // Sensors remain completely DORMANT to prevent battery drain when not recording.
    await _requestPermissions();
  }

  Future<void> _handleNativeCall(MethodCall call) async {
    if (call.method == 'onActivityTransition') {
      final args = Map<String, dynamic>.from(call.arguments ?? {});
      final activity = args['activity']?.toString() ?? 'UNKNOWN';
      final transition = args['transition']?.toString() ?? 'UNKNOWN';
      _lastActivityTransition = '$activity ($transition)';
      _lastActivityTransitionTime = DateTime.now();
      notifyListeners();

      if (activity == 'IN_VEHICLE' && transition == 'ENTER') {
        debugPrint('[SensorService] Stage 1 Tripwire Fired: IN_VEHICLE ENTER! Kicking off 10s Stage 2 burst.');
        executeStage2Burst();
      }
    }
  }

  Future<void> startTripwire() async {
    try {
      await _channel.invokeMethod('startTripwire');
      _isTripwireActive = true;
      notifyListeners();
    } catch (e) {
      debugPrint('Error starting tripwire: $e');
    }
  }

  Future<void> stopTripwire() async {
    try {
      await _channel.invokeMethod('stopTripwire');
      _isTripwireActive = false;
      notifyListeners();
    } catch (e) {
      debugPrint('Error stopping tripwire: $e');
    }
  }

  /// Executes Stage 2 Bounded 10s IMU Burst and offloads Low Telemetry to Cloud Run.
  Future<RecordingSession?> executeStage2Burst() async {
    if (_isRecording) return null;
    debugPrint('[SensorService] Starting Stage 2 Bounded 10s IMU Burst...');
    await startRecording();
    await Future.delayed(const Duration(seconds: 10));
    final session = await stopRecording();
    debugPrint('[SensorService] Stage 2 Bounded Burst complete: ${session?.sampleCount} samples.');

    // Stage 3 & 4: Automatically transmit Low Telemetry to Cloud Run
    if (session != null && _latestFeature != null) {
      final api = ApiService();
      final journey = {
        'total_distance_meters': _sessionDistanceMeters,
        'max_speed_kmh': _sessionMaxSpeedKmh,
        'avg_speed_kmh': sessionAvgSpeedKmh,
        'has_gps_fix': _hasGpsFix,
        'start_location': _startGpsReading,
        'end_location': _latestGpsReading,
      };
      debugPrint('[SensorService] Offloading Low Telemetry to Cloud Run...');
      await api.sendContextEvent(
        eventType: 'BOUNDED_IMU_BURST',
        featureSummary: _latestFeature!.toBackendFeatureSummary(),
        journeyGps: journey,
        transitionState: _lastActivityTransition ?? 'IN_VEHICLE_ENTER',
      );
    }
    return session;
  }

  Future<void> _requestPermissions() async {
    try {
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
    } catch (e) {
      debugPrint('Error requesting location permission: $e');
    }
  }

  /// Retrieves the device's current GPS location on demand.
  /// Checks whether location services are enabled and permissions are granted.
  /// Employs fast last-known position fallback followed by a high-accuracy fix (3s timeout).
  Future<Map<String, double>?> getCurrentLocation({bool requestIfNeeded = true}) async {
    try {
      bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        debugPrint('[SensorService] Location services are disabled.');
        return null;
      }

      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied && requestIfNeeded) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
        debugPrint('[SensorService] Location permissions are denied: $permission');
        return null;
      }

      // Try quick cached last known position first
      Position? position = await Geolocator.getLastKnownPosition();
      if (position != null) {
        _lat = position.latitude;
        _lon = position.longitude;
        _alt = position.altitude;
        _accuracy = position.accuracy;
        _hasGpsFix = true;
      }

      // Fetch fresh high-accuracy position with 3-second timeout
      try {
        final freshPos = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            timeLimit: Duration(seconds: 3),
          ),
        );
        _lat = freshPos.latitude;
        _lon = freshPos.longitude;
        _alt = freshPos.altitude;
        _speedMps = freshPos.speed;
        _speedKmh = freshPos.speed * 3.6;
        _bearing = freshPos.heading;
        _accuracy = freshPos.accuracy;
        _hasGpsFix = true;
        position = freshPos;
      } catch (e) {
        debugPrint('[SensorService] High-accuracy GPS timeout/error, using last known: $e');
      }

      if (position != null) {
        notifyListeners();
        return {
          'latitude': position.latitude,
          'longitude': position.longitude,
          'accuracy': position.accuracy,
        };
      }
    } catch (e) {
      debugPrint('[SensorService] Error retrieving current location: $e');
    }
    return null;
  }


  void _startSensorStreams() {
    // 1. Raw Accelerometer (~50 Hz / Game interval)
    _accelSub = accelerometerEventStream(
      samplingPeriod: SensorInterval.gameInterval,
    ).listen((event) {
      _rawAx = event.x;
      _rawAy = event.y;
      _rawAz = event.z;
      _onImuTick();
    });

    // 2. User Accelerometer (without gravity)
    _userAccelSub = userAccelerometerEventStream(
      samplingPeriod: SensorInterval.gameInterval,
    ).listen((event) {
      _userAx = event.x;
      _userAy = event.y;
      _userAz = event.z;
    });

    // 3. Gyroscope (~50 Hz)
    _gyroSub = gyroscopeEventStream(
      samplingPeriod: SensorInterval.gameInterval,
    ).listen((event) {
      _gyroX = event.x;
      _gyroY = event.y;
      _gyroZ = event.z;
    });
  }

  void _startGpsStream() {
    // High Telemetry GPS: Continuous 1-meter precision tracking with 1 Hz polling
    final locationSettings = defaultTargetPlatform == TargetPlatform.android
        ? AndroidSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 1, // High Telemetry: 1-meter tracking
            forceLocationManager: false,
            intervalDuration: const Duration(milliseconds: 1000), // 1 Hz polling
          )
        : const LocationSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 1,
          );

    _gpsSub = Geolocator.getPositionStream(
      locationSettings: locationSettings,
    ).listen(
      (pos) {
        _lat = pos.latitude;
        _lon = pos.longitude;
        _alt = pos.altitude;
        _speedMps = pos.speed < 0 ? 0.0 : pos.speed;
        _speedKmh = _speedMps * 3.6;
        _bearing = pos.heading;
        _accuracy = pos.accuracy;
        _hasGpsFix = true;

        if (_isRecording) {
          final now = DateTime.now();
          final reading = {
            'latitude': _lat,
            'longitude': _lon,
            'altitude_m': _alt,
            'speed_mps': _speedMps,
            'speed_kmh': _speedKmh,
            'bearing_deg': _bearing,
            'accuracy_m': _accuracy,
            'timestamp': now.toIso8601String(),
          };

          _startGpsReading ??= reading;
          _latestGpsReading = reading;

          if (_prevGpsLat != null && _prevGpsLon != null) {
            final d = Geolocator.distanceBetween(
              _prevGpsLat!,
              _prevGpsLon!,
              _lat,
              _lon,
            );
            // Ignore sub-meter stationary GPS drift and reject anomalies (> 200 m/s)
            if (d >= 0.8 && d < 200.0) {
              _sessionDistanceMeters += d;
            }
          }
          _prevGpsLat = _lat;
          _prevGpsLon = _lon;

          if (_speedKmh > _sessionMaxSpeedKmh) {
            _sessionMaxSpeedKmh = _speedKmh;
          }
          _sessionSpeedSumKmh += _speedKmh;
          _sessionGpsFixCount++;

          // Bounding box for trajectory
          _minLat = _minLat == null ? _lat : (_lat < _minLat! ? _lat : _minLat);
          _maxLat = _maxLat == null ? _lat : (_lat > _maxLat! ? _lat : _maxLat);
          _minLon = _minLon == null ? _lon : (_lon < _minLon! ? _lon : _minLon);
          _maxLon = _maxLon == null ? _lon : (_lon > _maxLon! ? _lon : _maxLon);

          // Low-telemetry periodic checkpoints (every 10s or 50m, capped at 50 points)
          if (_lastCheckpointTime == null ||
              now.difference(_lastCheckpointTime!).inSeconds >= 10) {
            if (_trajectoryCheckpoints.length < 50) {
              _trajectoryCheckpoints.add({
                'relative_sec': _sessionStartTime != null
                    ? (now.difference(_sessionStartTime!).inMilliseconds / 1000.0)
                    : 0.0,
                'lat': _lat,
                'lon': _lon,
                'speed_kmh': double.parse(_speedKmh.toStringAsFixed(1)),
                'accuracy_m': double.parse(_accuracy.toStringAsFixed(1)),
              });
              _lastCheckpointTime = now;
            }
          }
        }
      },
      onError: (err) {
        debugPrint('GPS stream error: $err');
      },
    );
  }

  void _startLiveMonitors() {
    // 20 FPS refresh for live waveform animation
    _liveUiTicker?.cancel();
    _liveUiTicker = Timer.periodic(const Duration(milliseconds: 50), (_) {
      if (_recentSamples.isNotEmpty) {
        notifyListeners();
      }
    });

    // 1 Hz edge feature extraction for low-telemetry metadata
    _featureTimer?.cancel();
    _featureTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_recentSamples.length >= 20) {
        _latestFeature = FeatureExtractor.extract(_recentSamples);
        notifyListeners();
      }
    });
  }

  void _stopSensorStreams() {
    _accelSub?.cancel();
    _accelSub = null;
    _userAccelSub?.cancel();
    _userAccelSub = null;
    _gyroSub?.cancel();
    _gyroSub = null;
    _gpsSub?.cancel();
    _gpsSub = null;
    _durationTimer?.cancel();
    _durationTimer = null;
    _featureTimer?.cancel();
    _featureTimer = null;
    _liveUiTicker?.cancel();
    _liveUiTicker = null;
  }

  /// Process incoming high-frequency IMU sample
  void _onImuTick() {
    final now = DateTime.now();
    final epochMs = now.millisecondsSinceEpoch;
    final relSec = _sessionStartTime != null
        ? now.difference(_sessionStartTime!).inMilliseconds / 1000.0
        : 0.0;

    final sample = SensorSample(
      timestampMs: epochMs,
      relativeTimeSec: relSec,
      accelX: _rawAx,
      accelY: _rawAy,
      accelZ: _rawAz,
      userAccelX: _userAx,
      userAccelY: _userAy,
      userAccelZ: _userAz,
      gyroX: _gyroX,
      gyroY: _gyroY,
      gyroZ: _gyroZ,
      latitude: _lat,
      longitude: _lon,
      altitudeM: _alt,
      speedMps: _speedMps,
      speedKmh: _speedKmh,
      bearingDeg: _bearing,
      accuracyM: _accuracy,
    );

    _latestSample = sample;

    // Buffer for live waveform & real-time FFT feature calculation
    _recentSamples.add(sample);
    if (_recentSamples.length > 120) {
      _recentSamples.removeAt(0);
    }

    // High Telemetry: Write 50 Hz raw sample row to CSV
    if (_isRecording && _currentCsvSink != null) {
      _currentCsvSink!.writeln(sample.toCsvRow());
      _sampleCount++;
    }
  }

  // ── Recording Controls (Start / Stop) ──────────────────────────────────────
  Future<void> toggleRecording() async {
    if (_isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  }

  Future<void> startRecording() async {
    if (_isRecording) return;

    final now = DateTime.now();
    _sessionStartTime = now;
    _sampleCount = 0;
    _recordingDurationSec = 0.0;
    _recentSamples.clear();
    _latestFeature = null;

    // Reset Low-Telemetry journey tracking metrics
    _sessionDistanceMeters = 0.0;
    _sessionMaxSpeedKmh = 0.0;
    _sessionSpeedSumKmh = 0.0;
    _sessionGpsFixCount = 0;
    _prevGpsLat = null;
    _prevGpsLon = null;
    _startGpsReading = null;
    _latestGpsReading = null;
    _minLat = null;
    _maxLat = null;
    _minLon = null;
    _maxLon = null;
    _trajectoryCheckpoints.clear();
    _lastCheckpointTime = null;

    final timestampStr = DateFormat('yyyyMMdd_HHmmss').format(now);
    _currentSessionId = 'jarvis_telemetry_$timestampStr';

    // 1. Android Foreground Service for background recording
    try {
      await _channel.invokeMethod('startService', {
        'title': 'Jarvis',
        'content': 'Active in background',
      });
    } catch (e) {
      debugPrint('Foreground service error: $e');
    }

    // 2. Prevent screen sleep while recording
    try {
      await WakelockPlus.enable();
    } catch (_) {}

    // 3. Initialize High-Telemetry CSV and Low-Telemetry JSON files
    final handles =
        await SessionStorageService.createSessionFiles(_currentSessionId!);
    _currentCsvFile = handles.csvFile;
    _currentJsonFile = handles.jsonFile;
    _currentCsvSink = handles.csvSink;

    _isRecording = true;

    // 4. Activate hardware sensor streams and live monitors
    _startSensorStreams();
    _startGpsStream();
    _startLiveMonitors();

    // 5. Timer for elapsed duration ticker
    _durationTimer?.cancel();
    _durationTimer = Timer.periodic(const Duration(milliseconds: 200), (t) {
      if (_sessionStartTime != null) {
        _recordingDurationSec =
            DateTime.now().difference(_sessionStartTime!).inMilliseconds /
                1000.0;
        notifyListeners();
      }
    });

    notifyListeners();
  }

  Future<RecordingSession?> stopRecording() async {
    if (!_isRecording) return null;

    final stopTime = DateTime.now();
    _isRecording = false;

    // 1. Immediately power down hardware sensors to return to dormant state
    _stopSensorStreams();

    // 2. Stop Android Foreground Service & release wakelock
    try {
      await _channel.invokeMethod('stopService');
    } catch (e) {
      debugPrint('Foreground service stop error: $e');
    }
    try {
      await WakelockPlus.disable();
    } catch (_) {}

    // 3. Low Telemetry: Compute overall session summary features & journey GPS
    final summaryFeatures = _recentSamples.isNotEmpty
        ? FeatureExtractor.extract(_recentSamples)
        : null;

    final avgSpeedKmh = _sessionGpsFixCount > 0
        ? _sessionSpeedSumKmh / _sessionGpsFixCount
        : 0.0;

    final journeyGps = {
      'has_gps_fix': _hasGpsFix,
      'total_distance_meters':
          double.parse(_sessionDistanceMeters.toStringAsFixed(1)),
      'max_speed_kmh': double.parse(_sessionMaxSpeedKmh.toStringAsFixed(1)),
      'avg_speed_kmh': double.parse(avgSpeedKmh.toStringAsFixed(1)),
      'start_location': _startGpsReading,
      'end_location': _latestGpsReading,
      'bounding_box': (_minLat != null)
          ? {
              'min_lat': _minLat,
              'max_lat': _maxLat,
              'min_lon': _minLon,
              'max_lon': _maxLon,
            }
          : null,
      'checkpoints_count': _trajectoryCheckpoints.length,
      'checkpoints': _trajectoryCheckpoints,
    };

    // 4. Finalize session files on disk
    RecordingSession? session;
    if (_currentCsvFile != null &&
        _currentJsonFile != null &&
        _currentCsvSink != null &&
        _currentSessionId != null &&
        _sessionStartTime != null) {
      session = await SessionStorageService.finalizeSession(
        sessionId: _currentSessionId!,
        startTime: _sessionStartTime!,
        endTime: stopTime,
        label: summaryFeatures?.vehicleClassHint ?? 'AUTO',
        mountPosition: 'POCKET_OR_MOUNT',
        roadCondition: 'NORMAL',
        sampleCount: _sampleCount,
        csvFile: _currentCsvFile!,
        jsonFile: _currentJsonFile!,
        csvSink: _currentCsvSink!,
        summaryFeatures: summaryFeatures,
        journeyGps: journeyGps,
      );
    }

    _currentCsvFile = null;
    _currentJsonFile = null;
    _currentCsvSink = null;
    _currentSessionId = null;

    notifyListeners();
    return session;
  }

  @override
  void dispose() {
    _stopSensorStreams();
    WakelockPlus.disable();
    super.dispose();
  }
}
