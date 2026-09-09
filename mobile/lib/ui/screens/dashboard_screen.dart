import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';
import '../widgets/feature_cards.dart';
import 'agent_screen.dart';
import 'sessions_screen.dart';

/// Clean Sensor Logger style Dashboard:
/// Features on-demand hardware sensor activation (dormant when idle),
/// dual 3-axis waveform graphs for Accelerometer & Gyroscope,
/// low-telemetry GPS status, and a direct button to route to saved files.
class DashboardScreen extends StatefulWidget {
  final SensorService sensorService;

  const DashboardScreen({super.key, required this.sensorService});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  SensorService get _service => widget.sensorService;

  @override
  void initState() {
    super.initState();
    _service.addListener(_onServiceUpdate);
  }

  @override
  void dispose() {
    _service.removeListener(_onServiceUpdate);
    super.dispose();
  }

  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  Future<void> _handleToggleRecording() async {
    if (_service.isRecording) {
      await _service.stopRecording();
      // No popup snackbar per user request! Saved files are accessible via the UI button.
    } else {
      await _service.startRecording();
    }
  }

  @override
  Widget build(BuildContext context) {
    final isRecording = _service.isRecording;
    final durationSec = _service.recordingDurationSec;
    final mins = (durationSec ~/ 60).toString().padLeft(2, '0');
    final secs = (durationSec.toInt() % 60).toString().padLeft(2, '0');
    final tenths = ((durationSec * 10).toInt() % 10).toString();

    // Approximate size: ~110 bytes per sample
    final approxKb = (_service.sampleCount * 110 / 1024).round();

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              width: 9,
              height: 9,
              decoration: BoxDecoration(
                color: isRecording ? AppTheme.red : AppTheme.textSecondary,
                shape: BoxShape.circle,
                boxShadow: isRecording
                    ? [
                        BoxShadow(
                          color: AppTheme.red.withValues(alpha: 0.8),
                          blurRadius: 8,
                          spreadRadius: 2,
                        ),
                      ]
                    : null,
              ),
            ),
            const SizedBox(width: 8),
            const Flexible(
              child: Text(
                'JARVIS SENSOR LOGGER',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 16),
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Jarvis Agent HUD',
            icon: const Icon(Icons.psychology, color: AppTheme.primary),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => AgentScreen(sensorService: widget.sensorService),
                ),
              );
            },
          ),
          IconButton(
            tooltip: 'View Saved Files',
            icon: const Icon(Icons.folder_outlined, color: AppTheme.cyan),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const SessionsScreen(),
                ),
              );
            },
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // ── HERO START / STOP RECORDING BAR ──────────────────────────────
              _buildRecordingController(
                isRecording: isRecording,
                timeStr: '$mins:$secs.$tenths',
                sampleCount: _service.sampleCount,
                sizeKb: approxKb,
                onPressed: _handleToggleRecording,
              ),

              const SizedBox(height: 10),

              // ── ROUTE TO SAVED FILES BUTTON ──────────────────────────────────
              _buildSavedFilesButton(),

              const SizedBox(height: 8),

              // ── ROUTE TO AGENT HUD BUTTON ────────────────────────────────────
              _buildAgentHudButton(),

              // ── STAGE 1 GAR TRIPWIRE STATUS ──────────────────────────────────
              _buildTripwireStatusCard(),

              const SizedBox(height: 12),

              // ── LOW-TELEMETRY GPS & TELEMETRY STATUS ──────────────────────────
              _buildGpsTelemetryCard(isRecording: isRecording),

              const SizedBox(height: 12),

              // ── BRD STAGE 3 VIBRATION & FEATURE EXTRACTION ───────────────────
              FeatureCards(
                features: _service.latestFeature,
              ),

              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildRecordingController({
    required bool isRecording,
    required String timeStr,
    required int sampleCount,
    required int sizeKb,
    required VoidCallback onPressed,
  }) {
    final bgColor = isRecording ? AppTheme.red : AppTheme.cyan;
    final fgColor = isRecording ? Colors.white : Colors.black;

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: bgColor.withValues(alpha: isRecording ? 0.45 : 0.25),
            blurRadius: 16,
            spreadRadius: 2,
          ),
        ],
      ),
      child: Material(
        color: bgColor,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onPressed,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 18),
            child: Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: fgColor.withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    isRecording
                        ? Icons.stop_rounded
                        : Icons.fiber_manual_record_rounded,
                    size: 28,
                    color: fgColor,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        isRecording
                            ? 'STOP & SAVE RECORDING'
                            : 'START RECORDING',
                        style: TextStyle(
                          color: fgColor,
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 1.0,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        isRecording
                            ? 'REC: $timeStr • $sampleCount samples ($sizeKb KB)'
                            : 'Sensors Dormant • Tap to Record High & Low Telemetry',
                        style: TextStyle(
                          color: fgColor.withValues(alpha: 0.85),
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          fontFamily: isRecording ? 'monospace' : null,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(
                  Icons.arrow_forward_ios_rounded,
                  size: 16,
                  color: fgColor.withValues(alpha: 0.7),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSavedFilesButton() {
    return Material(
      color: AppTheme.surface,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => const SessionsScreen(),
            ),
          );
        },
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.border),
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppTheme.cyan.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.folder_open_rounded,
                  color: AppTheme.cyan,
                  size: 18,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Text(
                      'SAVED RECORDING SESSIONS',
                      style: TextStyle(
                        color: AppTheme.textPrimary,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.6,
                      ),
                    ),
                    SizedBox(height: 1),
                    Text(
                      'Browse CSV logs & JSON cloud metadata',
                      style: TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 10,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppTheme.surfaceBright,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AppTheme.border),
                ),
                child: const Text(
                  'VIEW FILES',
                  style: TextStyle(
                    color: AppTheme.cyan,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAgentHudButton() {
    return Material(
      color: AppTheme.surface,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => AgentScreen(sensorService: widget.sensorService),
            ),
          );
        },
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.primary.withAlpha(80)),
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppTheme.primary.withAlpha(40),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.psychology,
                  color: AppTheme.primary,
                  size: 18,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Text(
                      'JARVIS AGENT HUD & AUTOMATIONS',
                      style: TextStyle(
                        color: AppTheme.primary,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.6,
                      ),
                    ),
                    SizedBox(height: 1),
                    Text(
                      'Cloud Run Reasoner, Reminders & Tasks',
                      style: TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 10,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppTheme.surfaceBright,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AppTheme.primary.withAlpha(80)),
                ),
                child: const Text(
                  'OPEN HUD',
                  style: TextStyle(
                    color: AppTheme.primary,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTripwireStatusCard() {
    final tripwireActive = _service.isTripwireActive;
    final lastTransition = _service.lastActivityTransition ?? 'DORMANT (Awaiting Vehicle Motion)';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Icon(Icons.sensors, color: tripwireActive ? AppTheme.green : AppTheme.textSecondary, size: 18),
                  const SizedBox(width: 8),
                  const Text(
                    'STAGE 1: GAR TRIPWIRE',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.8,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
              Switch(
                value: tripwireActive,
                activeThumbColor: AppTheme.primary,
                onChanged: (val) async {
                  if (val) {
                    await _service.startTripwire();
                  } else {
                    await _service.stopTripwire();
                  }
                  setState(() {});
                },
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Hardware state: $lastTransition',
            style: const TextStyle(
              fontSize: 11,
              fontFamily: 'monospace',
              color: AppTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            tripwireActive
                ? 'ARMED: Automatically wakes 10s burst & triggers pipeline upon IN_VEHICLE'
                : 'DISARMED: App remains completely dormant to save battery',
            style: TextStyle(
              fontSize: 10,
              color: tripwireActive ? AppTheme.green : AppTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGpsTelemetryCard({required bool isRecording}) {
    final hasFix = _service.hasGpsFix;
    final speed = _service.speedKmh.toStringAsFixed(1);
    final accuracy = _service.accuracy.toStringAsFixed(1);
    final latStr = hasFix ? _service.lat.toStringAsFixed(4) : '--';
    final lonStr = hasFix ? _service.lon.toStringAsFixed(4) : '--';

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: isRecording
                          ? (hasFix ? AppTheme.green : AppTheme.amber)
                          : AppTheme.textSecondary,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Text(
                    'LOCATION & TELEMETRY MODES',
                    style: TextStyle(
                      color: AppTheme.textPrimary,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.8,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.surfaceBright,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Text(
                  isRecording
                      ? (hasFix ? 'GPS ACTIVE' : 'ACQUIRING...')
                      : 'STANDBY',
                  style: TextStyle(
                    color: isRecording
                        ? (hasFix ? AppTheme.green : AppTheme.amber)
                        : AppTheme.textSecondary,
                    fontSize: 9,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: _buildTelemetryMetric(
                  label: 'SPEED',
                  value: isRecording ? '$speed km/h' : '--',
                  highlight: isRecording && _service.speedKmh > 1.0,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildTelemetryMetric(
                  label: 'DISTANCE',
                  value: isRecording
                      ? (_service.sessionDistanceMeters < 1000
                          ? '${_service.sessionDistanceMeters.toStringAsFixed(0)} m'
                          : '${(_service.sessionDistanceMeters / 1000).toStringAsFixed(2)} km')
                      : '--',
                  highlight: isRecording && _service.sessionDistanceMeters > 5.0,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildTelemetryMetric(
                  label: 'ACCURACY',
                  value: isRecording && hasFix ? '±$accuracy m' : '--',
                  highlight: false,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildTelemetryMetric(
                  label: 'COORDINATES',
                  value: isRecording && hasFix ? '$latStr, $lonStr' : '--',
                  highlight: false,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: AppTheme.surfaceBright,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: isRecording
                    ? AppTheme.cyan.withValues(alpha: 0.3)
                    : AppTheme.border,
              ),
            ),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.circle,
                          size: 7,
                          color: isRecording ? AppTheme.cyan : AppTheme.textSecondary,
                        ),
                        const SizedBox(width: 5),
                        const Text(
                          'HIGH TELEMETRY',
                          style: TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 9,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ],
                    ),
                    Text(
                      isRecording
                          ? '50Hz Raw CSV + 1m GNSS'
                          : 'Dormant (Off when idle)',
                      style: TextStyle(
                        color: isRecording ? AppTheme.cyan : AppTheme.textSecondary,
                        fontSize: 9,
                        fontFamily: 'monospace',
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.circle,
                          size: 7,
                          color: isRecording ? AppTheme.green : AppTheme.textSecondary,
                        ),
                        const SizedBox(width: 5),
                        const Text(
                          'LOW TELEMETRY',
                          style: TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 9,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ],
                    ),
                    Text(
                      isRecording
                          ? 'Edge FFT + Trajectory JSON'
                          : 'Dormant (Extract on record)',
                      style: TextStyle(
                        color: isRecording ? AppTheme.green : AppTheme.textSecondary,
                        fontSize: 9,
                        fontFamily: 'monospace',
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTelemetryMetric({
    required String label,
    required String value,
    required bool highlight,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: AppTheme.surfaceBright,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 8,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 2),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              maxLines: 1,
              style: TextStyle(
                color: highlight ? AppTheme.cyan : AppTheme.textPrimary,
                fontSize: 11,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace',
              ),
            ),
          ),
        ],
      ),
    );
  }
}
