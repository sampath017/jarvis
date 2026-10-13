import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import '../theme.dart';

class MotionMonitoringScreen extends StatefulWidget {
  const MotionMonitoringScreen({super.key});
  @override
  State<MotionMonitoringScreen> createState() => _MotionMonitoringScreenState();
}

class _MotionMonitoringScreenState extends State<MotionMonitoringScreen> {
  static const _channel = MethodChannel('com.jarvis/foreground_service');
  Map<String, dynamic> _data = {};
  String? _error;
  String _activity = 'WALKING';
  String _placement = 'pocket';
  Map<dynamic, dynamic>? _started;
  Timer? _timer;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final raw = await _channel.invokeMethod<String>('motionDiagnostics');
      final data = jsonDecode(raw ?? '{}') as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _data = data;
          _error = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Could not read monitoring history. Try again.',
        );
      }
    }
  }

  Future<void> _label() async {
    setState(() => _busy = true);
    try {
      if (_started == null) {
        final clock = await _channel.invokeMapMethod<dynamic, dynamic>(
          'motionClock',
        );
        if (mounted && clock != null) setState(() => _started = clock);
      } else {
        await _channel.invokeMethod('labelMotion', {
          'activity': _activity,
          'placement': _placement,
          'startedAt': _started!['wallMs'],
          'startedElapsedMs': _started!['elapsedMs'],
          'bootCount': _started!['bootCount'],
        });
        if (mounted) {
          setState(() => _started = null);
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(const SnackBar(content: Text('Activity label saved')));
        }
        await _load();
      }
    } on PlatformException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message ?? 'Could not save label')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    try {
      final raw = await _channel.invokeMethod<String>('motionDiagnostics');
      await Clipboard.setData(ClipboardData(text: raw ?? '{}'));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Monitoring history copied')),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not export history')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final records = ((_data['records'] as List?) ?? [])
        .whereType<Map>()
        .toList();
    final local = records.where((r) => r['source'] == 'local_motion').toList();
    final google = records
        .where((r) => r['source'] == 'google_activity')
        .toList();
    final usable = local
        .where((r) => (r['features'] as Map?)?['usable'] == true)
        .length;
    final delays =
        google.map((r) => (r['delivery_delay_ms'] as num?) ?? 0).toList()
          ..sort();
    final labels = records.where((r) => r['source'] == 'user_label').length;
    final last = local.isEmpty
        ? null
        : DateTime.tryParse('${local.last['timestamp']}')?.toLocal();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Motion monitoring'),
        actions: [
          IconButton(
            onPressed: _load,
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Comparing phone motion with Google activity detection',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Motion results are provisional while we measure accuracy. They do not trigger reminders or change your journeys.',
            style: TextStyle(color: AppTheme.textSecondary),
          ),
          const SizedBox(height: 20),
          Text(
            _data['monitoring'] == true
                ? 'Monitoring enabled'
                : 'Monitoring is off',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: AppTheme.amber)),
          Text(
            last == null
                ? 'Waiting for the first motion observation'
                : 'Last motion observation: ${DateFormat.jm().format(last)}',
          ),
          Text(
            '${local.length} motion windows · $usable with usable sensor coverage',
          ),
          Text(
            '${google.length} Google observations · longest delivery delay: ${delays.isEmpty ? "—" : "${(delays.last / 60000).toStringAsFixed(1)} min"}',
          ),
          Text('$labels saved activity labels · history retained for 24 hours'),
          const SizedBox(height: 28),
          const Text(
            'Help measure accuracy',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Choose what you are doing and where your phone is. Start a label, then finish it when that activity ends. Label stillness only while you are stationary with your phone.',
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _activity,
            decoration: const InputDecoration(labelText: 'Activity'),
            items: const [
              DropdownMenuItem(value: 'STILL', child: Text('Stationary')),
              DropdownMenuItem(value: 'WALKING', child: Text('Walking')),
              DropdownMenuItem(value: 'RUNNING', child: Text('Running')),
              DropdownMenuItem(
                value: 'IN_VEHICLE',
                child: Text('Travelling in a vehicle'),
              ),
              DropdownMenuItem(value: 'ON_BICYCLE', child: Text('Cycling')),
            ],
            onChanged: _started != null
                ? null
                : (value) => setState(() => _activity = value!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _placement,
            decoration: const InputDecoration(labelText: 'Phone placement'),
            items: const [
              DropdownMenuItem(value: 'pocket', child: Text('Pocket')),
              DropdownMenuItem(value: 'hand', child: Text('Hand')),
              DropdownMenuItem(value: 'bag', child: Text('Bag')),
              DropdownMenuItem(value: 'mounted', child: Text('Mounted')),
              DropdownMenuItem(value: 'table', child: Text('Table')),
              DropdownMenuItem(value: 'other', child: Text('Other')),
            ],
            onChanged: _started != null
                ? null
                : (value) => setState(() => _placement = value!),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy || _data['monitoring'] != true ? null : _label,
            child: Text(
              _started == null
                  ? 'Start activity label'
                  : 'Finish and save label',
            ),
          ),
          if (_started != null)
            TextButton(
              onPressed: _busy ? null : () => setState(() => _started = null),
              child: const Text('Discard label'),
            ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: _copy,
            icon: const Icon(Icons.copy),
            label: const Text('Copy monitoring history'),
          ),
        ],
      ),
    );
  }
}
