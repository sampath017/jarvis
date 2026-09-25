import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

import '../../models/activity_day.dart';
import '../../services/activity_history_service.dart';
import '../theme.dart';

class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key, this.history});

  final ActivityHistoryService? history;

  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen>
    with WidgetsBindingObserver {
  late final ActivityHistoryService _history =
      widget.history ?? ActivityHistoryService();
  DateTime _day = DateTime.now();
  ActivityDay? _activity;
  String? _selectedSession;
  String? _error;
  bool _loading = true;
  bool _showMap = false;
  bool _refreshing = false;
  bool _showingCache = false;
  int _loadVersion = 0;
  DateTime? _lastLoadedAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadDay();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed &&
        _sameDay(_day, DateTime.now()) &&
        (_lastLoadedAt == null ||
            DateTime.now().difference(_lastLoadedAt!) >
                const Duration(minutes: 5))) {
      _loadDay();
    }
  }

  bool _sameDay(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;

  Future<void> _loadDay({bool newDay = false}) async {
    final version = ++_loadVersion;
    final day = _day;
    if (newDay) {
      setState(() {
        _activity = null;
        _selectedSession = null;
        _error = null;
        _loading = true;
        _showingCache = false;
      });
    } else {
      setState(() => _refreshing = true);
    }
    try {
      final cached = await _history.cachedDay(day);
      if (mounted && version == _loadVersion && cached != null) {
        setState(() {
          _activity = ActivityDay.fromJson(cached);
          _loading = false;
          _showingCache = true;
        });
      }
      final fresh = await _history.fetchDay(day);
      if (!mounted || version != _loadVersion) return;
      final parsed = ActivityDay.fromJson(fresh);
      setState(() {
        _activity = parsed;
        if (_selectedSession != null &&
            !parsed.groups.any((group) => group.key == _selectedSession)) {
          _selectedSession = null;
        }
        _error = null;
        _loading = false;
        _refreshing = false;
        _showingCache = false;
        _lastLoadedAt = DateTime.now();
      });
    } catch (_) {
      if (!mounted || version != _loadVersion) return;
      setState(() {
        _error = _activity == null
            ? 'Could not load activity history. Check your connection and try again.'
            : 'Showing the last saved copy. Pull down to refresh.';
        _loading = false;
        _refreshing = false;
      });
    }
  }

  void _changeDay(int offset) {
    final candidate = DateTime(_day.year, _day.month, _day.day + offset);
    if (candidate.isAfter(DateTime.now())) return;
    setState(() => _day = candidate);
    _loadDay(newDay: true);
  }

  Future<void> _pickDay() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      helpText: 'Choose activity day',
    );
    if (picked == null || _sameDay(picked, _day)) return;
    setState(() => _day = picked);
    _loadDay(newDay: true);
  }

  @override
  Widget build(BuildContext context) {
    final data = _activity;
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Activity'),
        actions: [
          IconButton(
            tooltip: 'Refresh activity',
            icon: const Icon(Icons.refresh),
            onPressed: _refreshing ? null : _loadDay,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadDay,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
          children: [
            _datePicker(),
            if (_refreshing) const LinearProgressIndicator(minHeight: 2),
            const SizedBox(height: 16),
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(60),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (data == null)
              _messageCard(
                Icons.cloud_off_outlined,
                _error ?? 'No activity history available.',
                retry: true,
              )
            else ...[
              if (_error != null)
                _messageCard(Icons.cloud_off_outlined, _error!),
              if (_showingCache && _error == null)
                _messageCard(
                  Icons.offline_pin_outlined,
                  'Showing saved activity while the latest records load.',
                ),
              _summary(data),
              const SizedBox(height: 16),
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(
                    value: false,
                    icon: Icon(Icons.view_timeline_outlined),
                    label: Text('Timeline'),
                  ),
                  ButtonSegment(
                    value: true,
                    icon: Icon(Icons.map_outlined),
                    label: Text('Map'),
                  ),
                ],
                selected: {_showMap},
                onSelectionChanged: (selection) =>
                    setState(() => _showMap = selection.first),
              ),
              const SizedBox(height: 12),
              _sessionChips(data),
              if (_showMap) ...[
                const SizedBox(height: 12),
                _mapCard(data),
                const SizedBox(height: 8),
                const Text(
                  'Dots show recorded locations. Lines connect nearby samples, not a confirmed route.',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              ],
              if (data.truncated || data.gapCount > 0) ...[
                const SizedBox(height: 12),
                _messageCard(
                  Icons.info_outline,
                  data.truncated
                      ? 'This day has more history than one view can show. The timeline may be incomplete.'
                      : '${data.gapCount} gaps in recording. Activity between these readings is unknown.',
                ),
              ],
              const SizedBox(height: 24),
              _sessionHeader(data),
              const SizedBox(height: 12),
              if (data.groups.isEmpty)
                _messageCard(
                  Icons.route_outlined,
                  'No activities were recorded for this day.',
                )
              else
                for (var i = 0; i < data.groups.length; i++)
                  if (_selectedSession == null ||
                      _selectedSession == _groupKey(data.groups[i])) ...[
                    _groupCard(data.groups[i], i + 1),
                    const SizedBox(height: 10),
                  ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _datePicker() {
    final today = _sameDay(_day, DateTime.now());
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Previous day',
            onPressed: () => _changeDay(-1),
            icon: const Icon(Icons.chevron_left),
          ),
          Expanded(
            child: TextButton.icon(
              onPressed: _pickDay,
              icon: const Icon(Icons.calendar_month_outlined, size: 19),
              label: Text(
                today
                    ? 'Today · ${DateFormat('d MMMM yyyy').format(_day)}'
                    : DateFormat('EEEE, d MMMM yyyy').format(_day),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
          IconButton(
            tooltip: 'Next day',
            onPressed: today ? null : () => _changeDay(1),
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    );
  }

  Widget _summary(ActivityDay day) {
    final count = day.observations.length;
    final locations = day.observations.where((o) => o.hasLocation).length;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Your day at a glance',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              _metric('$count', 'Records', Icons.timeline_outlined),
              const SizedBox(width: 8),
              _metric(
                '${day.journeys.length}',
                'Journeys',
                Icons.route_outlined,
              ),
              const SizedBox(width: 8),
              _metric('$locations', 'With location', Icons.place_outlined),
            ],
          ),
          if (count > 0) ...[
            const SizedBox(height: 18),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                value: locations / count,
                minHeight: 6,
                backgroundColor: AppTheme.border,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              locations == count
                  ? 'Every record has a location'
                  : '${count - locations} records have no location',
              style: const TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 12,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _metric(String value, String label, IconData icon) => Expanded(
    child: Column(
      children: [
        Icon(icon, color: AppTheme.primary, size: 20),
        const SizedBox(height: 6),
        Text(
          value,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
        ),
        Text(
          label,
          style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
        ),
      ],
    ),
  );

  Widget _mapCard(ActivityDay day) {
    final observations = day
        .observationsFor(_selectedSession)
        .where((o) => o.hasLocation)
        .toList();
    if (observations.isEmpty) {
      return _messageCard(
        Icons.map_outlined,
        'No location points were recorded for this ${_selectedSession == null ? 'day' : 'session'}.',
      );
    }
    final coords = [
      for (final o in observations) LatLng(o.latitude!, o.longitude!),
    ];
    final step = (observations.length / 250).ceil().clamp(1, 1000000);
    final circles = <CircleMarker>[
      for (var i = 0; i < observations.length; i += step)
        CircleMarker(
          point: coords[i],
          radius: 4,
          color: AppTheme.primary,
          borderStrokeWidth: 1.5,
          borderColor: Colors.white,
        ),
    ];
    final polylines = <Polyline>[];
    var segment = <LatLng>[];
    ActivityObservation? previous;
    for (final observation in observations) {
      final canJoin =
          previous != null &&
          observation.sessionId == previous.sessionId &&
          observation.timestamp.difference(previous.timestamp) <=
              const Duration(minutes: 10);
      if (!canJoin && segment.length > 1) {
        polylines.add(
          Polyline(
            points: segment,
            color: AppTheme.primary.withValues(alpha: 0.7),
            strokeWidth: 3,
          ),
        );
      }
      segment = canJoin
          ? [...segment, LatLng(observation.latitude!, observation.longitude!)]
          : [LatLng(observation.latitude!, observation.longitude!)];
      previous = observation;
    }
    if (segment.length > 1) {
      polylines.add(
        Polyline(
          points: segment,
          color: AppTheme.primary.withValues(alpha: 0.7),
          strokeWidth: 3,
        ),
      );
    }
    final markers = <Marker>[];
    final seenPlaces = <String>{};
    for (final observation in observations) {
      if (markers.length >= 24) break;
      final place = observation.savedPlaces.isNotEmpty
          ? observation.savedPlaces.first
          : null;
      final stop = observation.contexts.any(
        (c) => c == 'PARKED' || c == 'DWELLING' || c == 'IN_SHOP',
      );
      if (place == null && !stop) continue;
      final key =
          '${place ?? 'stop'}:${observation.latitude!.toStringAsFixed(3)}:${observation.longitude!.toStringAsFixed(3)}';
      if (!seenPlaces.add(key)) continue;
      markers.add(
        Marker(
          point: LatLng(observation.latitude!, observation.longitude!),
          width: 36,
          height: 36,
          child: Tooltip(
            message: place == null ? 'Recorded stop' : 'Near $place',
            child: Container(
              decoration: BoxDecoration(
                color: AppTheme.surface,
                shape: BoxShape.circle,
                border: Border.all(color: AppTheme.primary, width: 2),
              ),
              child: Icon(
                place == null ? Icons.pause : Icons.place,
                color: AppTheme.primary,
                size: 20,
              ),
            ),
          ),
        ),
      );
    }
    return Container(
      height: 270,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.border),
      ),
      child: FlutterMap(
        key: ValueKey('${_history.dayKey(_day)}:${_selectedSession ?? 'all'}'),
        options: MapOptions(
          initialCenter: coords.first,
          initialZoom: 14,
          initialCameraFit: coords.length > 1
              ? CameraFit.coordinates(
                  coordinates: coords,
                  padding: const EdgeInsets.all(36),
                  maxZoom: 15,
                )
              : null,
          maxZoom: 19,
          backgroundColor: AppTheme.surfaceBright,
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            userAgentPackageName: 'com.jarvis.jarvis_collector',
          ),
          if (polylines.isNotEmpty) PolylineLayer(polylines: polylines),
          CircleLayer(circles: circles),
          if (markers.isNotEmpty) MarkerLayer(markers: markers),
          const SimpleAttributionWidget(
            source: Text(
              'OpenStreetMap contributors',
              style: TextStyle(fontSize: 10),
            ),
            backgroundColor: Color(0xDD1D2026),
          ),
        ],
      ),
    );
  }

  Widget _sessionHeader(ActivityDay day) => Row(
    children: [
      const Text(
        'Timeline',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
      ),
      const Spacer(),
      Text(
        '${day.groups.length}',
        style: const TextStyle(color: AppTheme.textSecondary),
      ),
    ],
  );

  String _groupKey(ActivityGroup group) => group.key;

  Widget _sessionChips(ActivityDay day) {
    if (day.groups.length <= 1) return const SizedBox.shrink();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _chip('All day', null, _selectedSession == null),
          for (var i = 0; i < day.groups.length; i++) ...[
            const SizedBox(width: 8),
            _chip(
              day.groups[i].sessionId == null
                  ? 'Period ${i + 1}'
                  : 'Journey ${i + 1}',
              _groupKey(day.groups[i]),
              _selectedSession == _groupKey(day.groups[i]),
            ),
          ],
        ],
      ),
    );
  }

  Widget _chip(String label, String? value, bool selected) => ChoiceChip(
    label: Text(label),
    selected: selected,
    onSelected: (_) => setState(() => _selectedSession = value),
    selectedColor: AppTheme.primary.withValues(alpha: 0.25),
    side: const BorderSide(color: AppTheme.border),
  );

  Widget _groupCard(ActivityGroup group, int index) {
    final journey = group.journey;
    final title = group.sessionId == null
        ? 'Activity period $index'
        : 'Journey $index';
    final vehicle = journey?.vehicleClass.toUpperCase() ?? '';
    final subtitle = [
      '${DateFormat.jm().format(group.start)} – ${DateFormat.jm().format(group.end)}',
      if (vehicle.isNotEmpty && vehicle != 'UNKNOWN')
        vehicle.replaceAll('_', ' ').toLowerCase(),
      if (journey?.status != null) journey!.status.toLowerCase(),
    ].join(' · ');
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.border),
      ),
      child: ExpansionTile(
        key: ValueKey(
          '${_history.dayKey(_day)}:${group.key}:${_selectedSession ?? "all"}',
        ),
        initiallyExpanded: _selectedSession != null || index == 1,
        shape: const Border(),
        collapsedShape: const Border(),
        leading: Icon(
          group.sessionId == null ? Icons.more_horiz : Icons.route,
          color: AppTheme.primary,
        ),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          subtitle,
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
        ),
        children: group.episodes.isEmpty
            ? [
                const ListTile(
                  title: Text('No observations saved in this session.'),
                ),
              ]
            : [
                for (final episode in group.episodes) _episodeTile(episode),
                const SizedBox(height: 8),
              ],
      ),
    );
  }

  Widget _episodeTile(ActivityEpisode episode) {
    final activityLabel = _episodeLabel(episode);
    final label = episode.transition.toUpperCase() == 'EXIT'
        ? '$activityLabel ended'
        : activityLabel;
    final points = _activity!
        .observationsForEpisode(episode)
        .where((o) => o.hasLocation)
        .toList();
    final time = episode.start == episode.end
        ? DateFormat.jm().format(episode.start)
        : '${DateFormat.jm().format(episode.start)} – ${DateFormat.jm().format(episode.end)}';
    final place = episode.savedPlaces.isNotEmpty
        ? 'Near ${episode.savedPlaces.join(', ')}'
        : episode.nearbyPlaces.isNotEmpty
        ? 'Nearby: ${episode.nearbyPlaces.take(2).join(', ')} (unconfirmed)'
        : points.isNotEmpty
        ? 'Location recorded · Tap to view'
        : 'Location unavailable';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: AppTheme.primary.withValues(alpha: 0.12),
            child: Icon(
              _activityIcon(episode.activity),
              size: 20,
              color: AppTheme.primary,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  time,
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 11,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                TextButton.icon(
                  style: TextButton.styleFrom(
                    padding: EdgeInsets.zero,
                    alignment: Alignment.centerLeft,
                  ),
                  onPressed: points.isEmpty
                      ? null
                      : () => _showRecordedLocation(points.first, label),
                  icon: Icon(
                    points.isEmpty
                        ? Icons.location_off_outlined
                        : Icons.place_outlined,
                    size: 16,
                  ),
                  label: Text(place, style: const TextStyle(fontSize: 12)),
                ),
                if (episode.samples > 1)
                  Text(
                    '${episode.samples} recorded updates',
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 11,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  IconData _activityIcon(String activity) => switch (activity.toUpperCase()) {
    'WALKING' || 'ON_FOOT' => Icons.directions_walk,
    'RUNNING' => Icons.directions_run,
    'IN_VEHICLE' => Icons.directions_car_outlined,
    'CYCLING' || 'ON_BICYCLE' => Icons.directions_bike,
    'STILL' => Icons.pause_circle_outline,
    _ => Icons.timeline,
  };

  void _showRecordedLocation(ActivityObservation point, String label) {
    final coordinate = LatLng(point.latitude!, point.longitude!);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                'Recorded at ${DateFormat.jm().format(point.timestamp)}',
                style: const TextStyle(color: AppTheme.textSecondary),
              ),
              const SizedBox(height: 12),
              SizedBox(
                height: 220,
                child: FlutterMap(
                  options: MapOptions(
                    initialCenter: coordinate,
                    initialZoom: 16,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.jarvis.jarvis_collector',
                    ),
                    MarkerLayer(
                      markers: [
                        Marker(
                          point: coordinate,
                          child: const Icon(
                            Icons.location_pin,
                            color: AppTheme.primary,
                            size: 36,
                          ),
                        ),
                      ],
                    ),
                    const SimpleAttributionWidget(
                      source: Text(
                        'OpenStreetMap contributors',
                        style: TextStyle(fontSize: 10),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${point.latitude!.toStringAsFixed(5)}, ${point.longitude!.toStringAsFixed(5)}${point.accuracyMeters == null ? "" : " · Accuracy ±${point.accuracyMeters!.round()} m"}',
                style: const TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _episodeLabel(ActivityEpisode episode) {
    if (episode.inferredContexts.contains('PARKED')) return 'Parked';
    if (episode.inferredContexts.contains('IN_SHOP')) return 'Likely at a shop';
    if (episode.inferredContexts.contains('DWELLING')) {
      return 'Stopped for a while';
    }
    switch (episode.activity.toUpperCase()) {
      case 'IN_VEHICLE':
        return 'In a vehicle';
      case 'WALKING':
      case 'ON_FOOT':
        return 'Walking';
      case 'RUNNING':
        return 'Running';
      case 'ON_BICYCLE':
      case 'CYCLING':
        return 'Cycling';
      case 'STILL':
        return 'Stationary';
      default:
        return 'Activity observed';
    }
  }

  Widget _messageCard(IconData icon, String message, {bool retry = false}) =>
      Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppTheme.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppTheme.border),
        ),
        child: Row(
          children: [
            Icon(icon, color: AppTheme.textSecondary),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                message,
                style: const TextStyle(color: AppTheme.textSecondary),
              ),
            ),
            if (retry)
              IconButton(
                tooltip: 'Retry',
                icon: const Icon(Icons.refresh),
                onPressed: _loadDay,
              ),
          ],
        ),
      );
}
