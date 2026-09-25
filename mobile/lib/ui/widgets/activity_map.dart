import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

import '../../models/activity_day.dart';
import '../../models/activity_map_data.dart';
import '../theme.dart';

class ActivityMap extends StatefulWidget {
  const ActivityMap({super.key, required this.observations, this.tileProvider});

  final List<ActivityObservation> observations;
  final TileProvider? tileProvider;

  @override
  State<ActivityMap> createState() => _ActivityMapState();
}

class _ActivityMapState extends State<ActivityMap> {
  final _controller = MapController();
  late ActivityMapData _data = ActivityMapData(widget.observations);
  late int _selected = _data.fixes.length - 1;
  bool _showLinks = false;

  @override
  void didUpdateWidget(ActivityMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    final key = _data.fixes.isEmpty
        ? null
        : ActivityMapData.fixKey(_data.fixes[_selected]);
    _data = ActivityMapData(widget.observations);
    _selected = _data.fixes.indexWhere((p) => ActivityMapData.fixKey(p) == key);
    if (_selected < 0) _selected = _data.fixes.length - 1;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  LatLng _coordinate(ActivityObservation p) =>
      LatLng(p.latitude!, p.longitude!);
  String _time(ActivityObservation p) =>
      DateFormat.jm().format(ActivityMapData.fixTime(p));
  String _label(ActivityObservation p) => switch (p.activity.toUpperCase()) {
    'WALKING' || 'ON_FOOT' => 'Walking',
    'STILL' => 'Stationary',
    'RUNNING' => 'Running',
    'ON_BICYCLE' || 'CYCLING' => 'Cycling',
    'IN_VEHICLE' => 'In a vehicle',
    _ => 'Activity unknown',
  };
  Color _color(ActivityObservation p) => switch (p.activity.toUpperCase()) {
    'STILL' => const Color(0xFFC98623),
    'IN_VEHICLE' || 'ON_BICYCLE' || 'CYCLING' => const Color(0xFF8861C5),
    'WALKING' || 'ON_FOOT' || 'RUNNING' => AppTheme.primary,
    _ => const Color(0xFF697480),
  };
  IconData _icon(ActivityObservation p) => switch (p.activity.toUpperCase()) {
    'STILL' => Icons.pause_rounded,
    'IN_VEHICLE' => Icons.directions_car_outlined,
    'ON_BICYCLE' || 'CYCLING' => Icons.directions_bike,
    'WALKING' || 'ON_FOOT' || 'RUNNING' => Icons.directions_walk,
    _ => Icons.location_on_outlined,
  };

  void _select(int index) {
    setState(() => _selected = index);
    _controller.move(_coordinate(_data.fixes[index]), 17);
  }

  void _fit() => _controller.fitCamera(
    CameraFit.coordinates(
      coordinates: _data.fixes.map(_coordinate).toList(),
      padding: const EdgeInsets.all(48),
      maxZoom: 17,
    ),
  );

  Widget _control(String label, IconData icon, VoidCallback onTap) => Material(
    color: AppTheme.surface,
    borderRadius: BorderRadius.circular(12),
    elevation: 3,
    child: IconButton(
      tooltip: label,
      onPressed: onTap,
      icon: Icon(icon, size: 20),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (_data.fixes.isEmpty) return const SizedBox.shrink();
    final point = _data.fixes[_selected];
    final accuracy = point.accuracyMeters;
    final validAccuracy = accuracy != null && accuracy.isFinite && accuracy > 0;
    final precise = _data.fixes.where(ActivityMapData.isPrecise).length;
    final places = point.savedPlaces.isNotEmpty
        ? point.savedPlaces
        : point.nearbyPlaces;
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Recorded locations',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Text(
                  '${_data.fixes.length} GPS fixes · $precise within 100 m',
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          SizedBox(
            height: 340,
            child: Stack(
              children: [
                FlutterMap(
                  mapController: _controller,
                  options: MapOptions(
                    initialCenter: _coordinate(point),
                    initialZoom: 17,
                    initialCameraFit: CameraFit.coordinates(
                      coordinates: _data.fixes.map(_coordinate).toList(),
                      padding: const EdgeInsets.all(48),
                      maxZoom: 17,
                    ),
                    minZoom: 3,
                    maxZoom: 19,
                    backgroundColor: AppTheme.surfaceBright,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.jarvis.jarvis_collector',
                      tileProvider: widget.tileProvider,
                    ),
                    if (_showLinks)
                      PolylineLayer(
                        polylines: [
                          for (final segment in _data.links)
                            Polyline(
                              points: segment.map(_coordinate).toList(),
                              color: _color(
                                segment.first,
                              ).withValues(alpha: .65),
                              strokeWidth: 2.5,
                            ),
                        ],
                      ),
                    if (validAccuracy)
                      CircleLayer(
                        circles: [
                          CircleMarker(
                            point: _coordinate(point),
                            radius: accuracy,
                            useRadiusInMeter: true,
                            color: _color(point).withValues(alpha: .12),
                            borderColor: _color(point).withValues(alpha: .65),
                            borderStrokeWidth: 1.5,
                          ),
                        ],
                      ),
                    MarkerLayer(
                      markers: [
                        for (var i = 0; i < _data.fixes.length; i++)
                          if (i != _selected) _marker(i),
                        _marker(_selected),
                      ],
                    ),
                    const Align(
                      alignment: Alignment.bottomRight,
                      child: ColoredBox(
                        color: Color(0xDD1D2026),
                        child: Padding(
                          padding: EdgeInsets.all(4),
                          child: Text(
                            '© OpenStreetMap contributors',
                            style: TextStyle(fontSize: 10),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                Positioned(
                  right: 10,
                  top: 10,
                  child: Column(
                    children: [
                      _control('Fit all locations', Icons.fit_screen, _fit),
                      const SizedBox(height: 6),
                      _control(
                        'Zoom in',
                        Icons.add,
                        () => _controller.move(
                          _controller.camera.center,
                          (_controller.camera.zoom + 1).clamp(3, 19).toDouble(),
                        ),
                      ),
                      const SizedBox(height: 6),
                      _control(
                        'Zoom out',
                        Icons.remove,
                        () => _controller.move(
                          _controller.camera.center,
                          (_controller.camera.zoom - 1).clamp(3, 19).toDouble(),
                        ),
                      ),
                    ],
                  ),
                ),
                Positioned(
                  left: 12,
                  top: 12,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    decoration: BoxDecoration(
                      color: AppTheme.surface,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      _time(point),
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(_icon(point), color: _color(point)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _label(point),
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          Text(
                            'GPS captured at ${_time(point)}',
                            style: const TextStyle(
                              color: AppTheme.textSecondary,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Text(
                      '${_selected + 1} / ${_data.fixes.length}',
                      style: const TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                if (places.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      'Near ${places.first}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    _badge(
                      Icons.gps_fixed,
                      validAccuracy
                          ? 'Accuracy ±${accuracy.round()} m'
                          : 'Accuracy unknown',
                    ),
                    if (point.wifiSignals > 0)
                      _badge(Icons.wifi, 'Wi-Fi context'),
                    if (point.eventType?.startsWith('CALL_') == true)
                      _badge(Icons.phone_outlined, 'Phone call'),
                    if (validAccuracy && accuracy > 100)
                      _badge(Icons.blur_on, 'Approximate location'),
                  ],
                ),
                if (point.locationObservedAt != null &&
                    point.timestamp
                            .difference(point.locationObservedAt!)
                            .abs()
                            .inSeconds >
                        30)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      'Activity reported at ${DateFormat.jm().format(point.timestamp)}',
                      style: const TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 12,
                      ),
                    ),
                  ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    IconButton(
                      tooltip: 'Previous recorded location',
                      onPressed: _selected > 0
                          ? () => _select(_selected - 1)
                          : null,
                      icon: const Icon(Icons.chevron_left),
                    ),
                    Expanded(
                      child: Text(
                        'Browse recorded points',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: AppTheme.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Next recorded location',
                      onPressed: _selected < _data.fixes.length - 1
                          ? () => _select(_selected + 1)
                          : null,
                      icon: const Icon(Icons.chevron_right),
                    ),
                  ],
                ),
                Wrap(
                  spacing: 14,
                  runSpacing: 6,
                  children: [
                    _legend(AppTheme.primary, 'Walking / running'),
                    _legend(const Color(0xFFC98623), 'Stationary'),
                    _legend(const Color(0xFF8861C5), 'Vehicle / cycle'),
                  ],
                ),
                if (_data.links.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: FilterChip(
                      label: const Text('Link close GPS fixes'),
                      selected: _showLinks,
                      onSelected: (value) => setState(() => _showLinks = value),
                    ),
                  ),
                const SizedBox(height: 10),
                const Text(
                  'The ring shows GPS uncertainty. Separated points leave the route between them unknown.',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
                if (_data.wifiWithoutCoordinates > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${_data.wifiWithoutCoordinates} Wi-Fi observations have no coordinates to plot.',
                      style: const TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 12,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Marker _marker(int index) {
    final point = _data.fixes[index];
    final selected = index == _selected;
    final prominent =
        selected ||
        index == 0 ||
        index == _data.fixes.length - 1 ||
        (point.activity == 'STILL' &&
            (index == 0 || _data.fixes[index - 1].activity != 'STILL'));
    return Marker(
      point: _coordinate(point),
      width: 40,
      height: 40,
      child: Semantics(
        label: '${_label(point)}, ${_time(point)}',
        button: true,
        child: GestureDetector(
          onTap: () => _select(index),
          behavior: HitTestBehavior.opaque,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              width: prominent ? 30 : 12,
              height: prominent ? 30 : 12,
              decoration: BoxDecoration(
                color: _color(point),
                shape: BoxShape.circle,
                border: Border.all(
                  color: Colors.white,
                  width: selected ? 3 : 2,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: .25),
                    blurRadius: 4,
                  ),
                ],
              ),
              child: prominent
                  ? Center(
                      child: Text(
                        '${index + 1}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    )
                  : null,
            ),
          ),
        ),
      ),
    );
  }

  Widget _badge(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
    decoration: BoxDecoration(
      color: AppTheme.surfaceBright,
      borderRadius: BorderRadius.circular(9),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: AppTheme.textSecondary),
        const SizedBox(width: 5),
        Text(label, style: const TextStyle(fontSize: 12)),
      ],
    ),
  );
  Widget _legend(Color color, String label) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 5),
      Text(
        label,
        style: const TextStyle(color: AppTheme.textSecondary, fontSize: 11),
      ),
    ],
  );
}
