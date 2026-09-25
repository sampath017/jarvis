import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

import '../../models/activity_day.dart';
import '../../services/activity_history_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import '../widgets/activity_map.dart';
import '../../services/session_preferences.dart';
import 'sessions_screen.dart';

class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key, this.history, this.preferences});

  final ActivityHistoryService? history;
  final SessionPreferences? preferences;

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
  bool _archived = false;
  Map<String, Map<String, Object?>> _preferences = {};
  late final SessionPreferences _store =
      widget.preferences ?? SessionPreferences();
  String _prefKey(ActivityGroup group) =>
      'journey:${group.sessionId ?? '${_history.dayKey(_day)}:${group.start.toUtc().toIso8601String()}'}';
  bool _isArchived(ActivityGroup group) =>
      _preferences[_prefKey(group)]?['archived'] == 1;
  String _title(ActivityGroup group) =>
      _preferences[_prefKey(group)]?['name'] as String? ??
      (group.sessionId == null
          ? 'Activity at ${DateFormat.jm().format(group.start)}'
          : 'Session at ${DateFormat.jm().format(group.start)}');

  Future<void> _loadPreferences() async {
    try {
      final result = await _store.load();
      if (mounted) setState(() => _preferences = result);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Session preferences could not be loaded.'),
          ),
        );
      }
    }
  }

  Future<void> _manage(ActivityGroup group, String action) async {
    final key = _prefKey(group);
    String? name = _preferences[key]?['name'] as String?;
    var archived = _isArchived(group);
    if (action == 'rename') {
      var editedName = name ?? _title(group);
      final result = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Name this session'),
          content: TextFormField(
            initialValue: editedName,
            onChanged: (value) => editedName = value,
            autofocus: true,
            maxLength: 60,
            decoration: const InputDecoration(labelText: 'Session name'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, editedName.trim()),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      if (result == null || !mounted) return;
      name = result.isEmpty ? null : result;
    } else {
      archived = !archived;
    }
    try {
      await _store.save(key, name, archived);
      if (!mounted) return;
      setState(() {
        _preferences[key] = {'name': name, 'archived': archived ? 1 : 0};
        _selectedSession = null;
      });
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Could not save to Firebase. Check your connection and retry.',
            ),
          ),
        );
      }
    }
  }

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
    _loadPreferences();
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
            tooltip: 'Saved recordings',
            icon: const Icon(Icons.folder_outlined),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(builder: (_) => const SessionsScreen()),
            ),
          ),
          IconButton(
            tooltip: 'Refresh activity',
            icon: const Icon(Icons.refresh),
            onPressed: _refreshing ? null : _loadDay,
          ),
        ],
      ),
      body: WorkspaceBody(
        child: RefreshIndicator(
          onRefresh: _loadDay,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 96),
            children: [
              _datePicker(),
              if (!_sameDay(_day, DateTime.now()))
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: () {
                      setState(() => _day = DateTime.now());
                      _loadDay(newDay: true);
                    },
                    child: const Text('Back to today'),
                  ),
                ),
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
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        _archived ? 'Archived sessions' : 'Your sessions',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ),
                    FilterChip(
                      label: const Text('Archive'),
                      selected: _archived,
                      onSelected: (value) => setState(() {
                        _archived = value;
                        _selectedSession = null;
                      }),
                    ),
                  ],
                ),
                const Text(
                  'Session names and archives are saved across your devices.',
                  style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                ),
                _sessionChips(data),
                if (_showMap) ...[const SizedBox(height: 12), _mapCard(data)],
                if (data.truncated || data.gapCount > 0) ...[
                  const SizedBox(height: 12),
                  _messageCard(
                    Icons.info_outline,
                    data.truncated
                        ? 'This day has more history than one view can show. The timeline may be incomplete.'
                        : '${data.gapCount} gaps between samples. Detected start and end changes connect the activity moments.',
                  ),
                ],
                const SizedBox(height: 24),
                _sessionHeader(data),
                const SizedBox(height: 12),
                if (data.groups
                    .where((g) => _isArchived(g) == _archived)
                    .isEmpty)
                  _messageCard(
                    Icons.route_outlined,
                    _archived
                        ? 'No archived sessions for this day.'
                        : 'No visible sessions for this day. Check the archive or choose another day.',
                  )
                else
                  for (var i = 0; i < data.groups.length; i++)
                    if (_isArchived(data.groups[i]) == _archived &&
                        (_selectedSession == null ||
                            _selectedSession == _groupKey(data.groups[i]))) ...[
                      _groupCard(data.groups[i], i + 1),
                      const SizedBox(height: 10),
                    ],
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _datePicker() {
    final today = _sameDay(_day, DateTime.now());
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
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
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Your day at a glance',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
          ),
          if (day.observations.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Last recorded at ${DateFormat.jm().format(day.observations.last.timestamp)}',
                style: const TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                ),
              ),
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
        Icon(icon, color: AppTheme.primaryLight, size: 18),
        const SizedBox(height: 6),
        Text(
          value,
          style: const TextStyle(
            fontSize: 26,
            fontWeight: FontWeight.w600,
            letterSpacing: -0.5,
          ),
        ),
        Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
        ),
      ],
    ),
  );

  Widget _mapCard(ActivityDay day) {
    final visible = day.groups
        .where(
          (g) =>
              _isArchived(g) == _archived &&
              (_selectedSession == null || g.key == _selectedSession),
        )
        .expand((g) => day.observationsFor(g.key))
        .toSet();
    final observations = day.observations.where(visible.contains).toList();
    if (!observations.any((o) => o.hasLocation)) {
      return _messageCard(
        Icons.map_outlined,
        'No location points were recorded for this ${_selectedSession == null ? "day" : "session"}.',
      );
    }
    return ActivityMap(
      key: ValueKey(
        '${_history.dayKey(_day)}:${_selectedSession ?? "all"}:$_archived',
      ),
      observations: observations,
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
        '${day.groups.where((g) => _isArchived(g) == _archived && (_selectedSession == null || g.key == _selectedSession)).length} sessions',
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
          for (var i = 0; i < day.groups.length; i++)
            if (_isArchived(day.groups[i]) == _archived) ...[
              const SizedBox(width: 8),
              _chip(
                _title(day.groups[i]),
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
    final title = _title(group);
    final vehicle = journey?.vehicleClass.toUpperCase() ?? '';
    final observations = _activity!.observationsFor(group.key);
    final locations = observations.where((o) => o.hasLocation).length;
    final subtitle = [
      '${DateFormat.jm().format(group.start)} – ${DateFormat.jm().format(group.end)}',
      if (vehicle.isNotEmpty && vehicle != 'UNKNOWN')
        vehicle.replaceAll('_', ' ').toLowerCase(),
      if (journey?.status != null)
        'Last status: ${journey!.status.replaceAll('_', ' ').toLowerCase()}',
    ].join(' · ');
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: AppTheme.border),
      ),
      child: ExpansionTile(
        key: ValueKey(
          '${_history.dayKey(_day)}:${group.key}:${_selectedSession ?? "all"}',
        ),
        initiallyExpanded: _selectedSession != null || index == 1,
        shape: const Border(),
        collapsedShape: const Border(),
        trailing: PopupMenuButton<String>(
          tooltip: 'Manage session',
          onSelected: (action) => _manage(group, action),
          itemBuilder: (_) => [
            const PopupMenuItem(value: 'rename', child: Text('Rename')),
            PopupMenuItem(
              value: 'archive',
              child: Text(_isArchived(group) ? 'Restore' : 'Archive'),
            ),
          ],
        ),
        leading: Icon(
          group.sessionId == null ? Icons.more_horiz : Icons.route,
          color: AppTheme.primary,
        ),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          '$subtitle\n${observations.length} records · $locations with location · Tap to expand',
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
    final evidence = _activity!.observationsForEpisode(episode);
    final hasWifi = evidence.any((o) => o.wifiSignals > 0);
    final hasBluetooth = evidence.any((o) => o.bluetoothSignals > 0);
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
                if (hasWifi || hasBluetooth)
                  Text(
                    [
                      if (hasWifi) 'Wi-Fi context recorded',
                      if (hasBluetooth) 'Bluetooth context recorded',
                    ].join(' · '),
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                if (episode.isOpen)
                  const Text(
                    'Last detected state · End not yet observed',
                    style: TextStyle(
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
    'PHONE_CALL' => Icons.phone_outlined,
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
                'Location recorded at ${DateFormat.jm().format(point.locationObservedAt ?? point.timestamp)}',
                style: const TextStyle(color: AppTheme.textSecondary),
              ),
              const SizedBox(height: 12),
              SizedBox(
                height: 220,
                child: FlutterMap(
                  options: MapOptions(
                    initialCenter: coordinate,
                    initialZoom: 17,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.jarvis.jarvis_collector',
                    ),
                    if (point.accuracyMeters != null &&
                        point.accuracyMeters!.isFinite &&
                        point.accuracyMeters! > 0)
                      CircleLayer(
                        circles: [
                          CircleMarker(
                            point: coordinate,
                            radius: point.accuracyMeters!,
                            useRadiusInMeter: true,
                            color: AppTheme.primary.withValues(alpha: .12),
                            borderColor: AppTheme.primary,
                            borderStrokeWidth: 1.5,
                          ),
                        ],
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
                point.accuracyMeters == null
                    ? 'GPS accuracy unavailable'
                    : 'GPS accuracy ±${point.accuracyMeters!.round()} m · Ring shows uncertainty',
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
      case 'PHONE_CALL':
        return 'Phone call';
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
