class ActivityObservation {
  const ActivityObservation({
    required this.timestamp,
    required this.activity,
    required this.transition,
    this.sessionId,
    this.latitude,
    this.longitude,
    this.accuracyMeters,
    this.savedPlaces = const [],
    this.contexts = const [],
    this.eventId,
    this.wifiSignals = 0,
    this.bluetoothSignals = 0,
    this.locationStatus,
    this.locationObservedAt,
    this.nearbyPlaces = const [],
    this.eventType,
  });

  final DateTime timestamp;
  final String activity;
  final String transition;
  final String? sessionId;
  final double? latitude;
  final double? longitude;
  final double? accuracyMeters;
  final List<String> savedPlaces;
  final List<String> contexts;
  final String? eventId;
  final int wifiSignals;
  final int bluetoothSignals;
  final String? locationStatus;
  final DateTime? locationObservedAt;
  final List<String> nearbyPlaces;
  final String? eventType;

  bool get hasLocation => latitude != null && longitude != null;

  static ActivityObservation? fromJson(Map<String, dynamic> json) {
    final at = DateTime.tryParse('${json['timestamp'] ?? ''}')?.toLocal();
    if (at == null) return null;
    final gps = json['gps'] is Map
        ? Map<String, dynamic>.from(json['gps'] as Map)
        : <String, dynamic>{};
    final lat = (gps['latitude'] as num?)?.toDouble();
    final lon = (gps['longitude'] as num?)?.toDouble();
    final validLocation =
        lat != null &&
        lon != null &&
        lat >= -90 &&
        lat <= 90 &&
        lon >= -180 &&
        lon <= 180;
    return ActivityObservation(
      timestamp: at,
      activity: '${json['activity'] ?? 'UNKNOWN'}',
      transition: '${json['transition'] ?? 'ENTER'}',
      sessionId: json['session_id']?.toString(),
      latitude: validLocation ? lat : null,
      longitude: validLocation ? lon : null,
      accuracyMeters: (gps['accuracy_m'] as num?)?.toDouble(),
      savedPlaces: _names(json['saved_places']),
      contexts: _names(json['contexts'], key: 'state'),
      eventId: json['event_id']?.toString(),
      wifiSignals: _radioCount(json['ambient_context'], 'wifi'),
      bluetoothSignals: _radioCount(json['ambient_context'], 'bluetooth'),
      locationStatus: json['location_status']?.toString(),
      locationObservedAt: DateTime.tryParse(
        '${gps['timestamp'] ?? ''}',
      )?.toLocal(),
      nearbyPlaces: _names(json['nearby_candidates']),
      eventType: json['event_type']?.toString(),
    );
  }
}

class ActivityEpisode {
  const ActivityEpisode({
    required this.start,
    required this.end,
    required this.activity,
    required this.transition,
    required this.samples,
    this.sessionId,
    this.savedPlaces = const [],
    this.nearbyPlaces = const [],
    this.inferredContexts = const [],
    this.eventIds = const [],
    this.isOpen = false,
    this.hasUncertainCoverage = false,
    this.uncertainSeconds = 0,
  });

  final DateTime start;
  final DateTime end;
  final String activity;
  final String transition;
  final int samples;
  final String? sessionId;
  final List<String> savedPlaces;
  final List<String> nearbyPlaces;
  final List<String> inferredContexts;
  final List<String> eventIds;
  final bool isOpen;
  final bool hasUncertainCoverage;
  final double uncertainSeconds;

  static ActivityEpisode? fromJson(Map<String, dynamic> json) {
    final start = DateTime.tryParse(
      '${json['window_start_at'] ?? json['start_at'] ?? json['first_observed_at'] ?? ''}',
    )?.toLocal();
    final end = DateTime.tryParse(
      '${json['window_end_at'] ?? json['end_at'] ?? json['last_observed_at'] ?? ''}',
    )?.toLocal();
    if (start == null || end == null) return null;
    return ActivityEpisode(
      start: start,
      end: end,
      activity: '${json['activity'] ?? 'UNKNOWN'}',
      transition: '${json['transition'] ?? 'ENTER'}',
      samples:
          (json['samples'] as num?)?.toInt() ??
          (json['observations'] as List?)?.length ??
          1,
      sessionId: json['session_id']?.toString(),
      savedPlaces: _strings(json['saved_place_matches']),
      nearbyPlaces: _strings(json['nearby_not_confirmed_visits']),
      inferredContexts: _strings(json['inferred_contexts']),
      eventIds: _strings(json['event_ids']),
      isOpen: json.containsKey('end_at') && json['end_at'] == null,
      hasUncertainCoverage: json['coverage_status'] == 'uncertain',
      uncertainSeconds:
          ((json['window_uncertain_seconds'] ?? json['uncertain_seconds'])
                  as num?)
              ?.toDouble() ??
          0,
    );
  }
}

class ActivityJourney {
  const ActivityJourney({
    required this.id,
    required this.startedAt,
    required this.lastUpdated,
    required this.status,
    required this.vehicleClass,
  });

  final String id;
  final DateTime startedAt;
  final DateTime lastUpdated;
  final String status;
  final String vehicleClass;

  static ActivityJourney? fromJson(Map<String, dynamic> json) {
    final id = '${json['session_id'] ?? ''}';
    final start = DateTime.tryParse('${json['started_at'] ?? ''}')?.toLocal();
    final end = DateTime.tryParse(
      '${json['completed_at'] ?? json['last_updated'] ?? ''}',
    )?.toLocal();
    if (id.isEmpty || start == null || end == null) return null;
    return ActivityJourney(
      id: id,
      startedAt: start,
      lastUpdated: end,
      status: '${json['status'] ?? 'UNKNOWN'}',
      vehicleClass: '${json['vehicle_class'] ?? 'UNKNOWN'}',
    );
  }
}

class ActivityGroup {
  const ActivityGroup({
    required this.key,
    required this.sessionId,
    required this.episodes,
    this.journey,
  });

  final String key;
  final String? sessionId;
  final List<ActivityEpisode> episodes;
  final ActivityJourney? journey;

  DateTime get start =>
      episodes.isNotEmpty ? episodes.first.start : journey!.startedAt;
  DateTime get end =>
      episodes.isNotEmpty ? episodes.last.end : journey!.lastUpdated;
}

class ActivityDay {
  const ActivityDay({
    required this.observations,
    required this.episodes,
    required this.journeys,
    required this.truncated,
    required this.gapCount,
  });

  final List<ActivityObservation> observations;
  final List<ActivityEpisode> episodes;
  final List<ActivityJourney> journeys;
  final bool truncated;
  final int gapCount;

  factory ActivityDay.fromJson(Map<String, dynamic> json) {
    final observations = <ActivityObservation>[];
    for (final item in json['observations'] as List? ?? const []) {
      if (item is Map) {
        final parsed = ActivityObservation.fromJson(
          Map<String, dynamic>.from(item),
        );
        if (parsed != null) observations.add(parsed);
      }
    }
    observations.sort((a, b) => a.timestamp.compareTo(b.timestamp));
    final episodes = <ActivityEpisode>[];
    for (final item
        in (json['micromoments'] ?? json['timeline']) as List? ?? const []) {
      if (item is Map) {
        final parsed = ActivityEpisode.fromJson(
          Map<String, dynamic>.from(item),
        );
        if (parsed != null) episodes.add(parsed);
      }
    }
    episodes.sort((a, b) => a.start.compareTo(b.start));
    final journeys = <ActivityJourney>[];
    for (final item
        in (json['activity_sessions'] ?? json['sessions']) as List? ??
            const []) {
      if (item is Map) {
        final parsed = ActivityJourney.fromJson(
          Map<String, dynamic>.from(item),
        );
        if (parsed != null) journeys.add(parsed);
      }
    }
    return ActivityDay(
      observations: observations,
      episodes: episodes,
      journeys: journeys,
      truncated: json['truncated'] == true,
      gapCount: (json['gap_count'] as num?)?.toInt() ?? 0,
    );
  }

  List<ActivityGroup> get groups {
    final byId = <String, List<ActivityEpisode>>{};
    final groups = <ActivityGroup>[];
    var unassigned = <ActivityEpisode>[];
    var periodIndex = 0;
    void finishPeriod() {
      if (unassigned.isEmpty) return;
      groups.add(
        ActivityGroup(
          key: 'period-${periodIndex++}',
          sessionId: null,
          episodes: unassigned,
        ),
      );
      unassigned = <ActivityEpisode>[];
    }

    for (final episode in episodes) {
      if (episode.sessionId != null) {
        finishPeriod();
        byId.putIfAbsent(episode.sessionId!, () => []).add(episode);
      } else {
        if (unassigned.isNotEmpty &&
            episode.start.difference(unassigned.last.end) >
                const Duration(minutes: 30)) {
          finishPeriod();
        }
        unassigned.add(episode);
      }
    }
    finishPeriod();
    final journeysById = {for (final journey in journeys) journey.id: journey};
    for (final journey in journeys) {
      byId.putIfAbsent(journey.id, () => []);
    }
    for (final entry in byId.entries) {
      groups.add(
        ActivityGroup(
          key: entry.key,
          sessionId: entry.key,
          episodes: entry.value,
          journey: journeysById[entry.key],
        ),
      );
    }
    groups.sort((a, b) => a.start.compareTo(b.start));
    return groups;
  }

  List<ActivityObservation> observationsForEpisode(ActivityEpisode episode) =>
      observations
          .where(
            (o) => episode.eventIds.isNotEmpty
                ? episode.eventIds.contains(o.eventId)
                : o.sessionId == episode.sessionId &&
                      o.activity == episode.activity &&
                      o.transition == episode.transition &&
                      !o.timestamp.isBefore(episode.start) &&
                      !o.timestamp.isAfter(episode.end),
          )
          .toList();

  List<ActivityObservation> observationsFor(String? groupKey) {
    if (groupKey == null) return observations;
    final matching = groups.where((group) => group.key == groupKey);
    if (matching.isEmpty) return const [];
    final group = matching.first;
    return observations.where((observation) {
      if (group.sessionId != null) {
        return observation.sessionId == group.sessionId;
      }
      return observation.sessionId == null &&
          !observation.timestamp.isBefore(group.start) &&
          !observation.timestamp.isAfter(group.end);
    }).toList();
  }
}

int _radioCount(Object? ambient, String key) {
  if (ambient is! Map || ambient[key] is! Map) return 0;
  final radio = ambient[key] as Map;
  final connected = radio['connected'];
  return (radio['nearby'] is List ? (radio['nearby'] as List).length : 0) +
      (connected is List
          ? connected.length
          : connected is Map
          ? 1
          : 0);
}

List<String> _strings(Object? value) => value is List
    ? value
          .map((item) => item.toString())
          .where((item) => item.isNotEmpty)
          .toList()
    : const [];

List<String> _names(Object? value, {String key = 'name'}) {
  if (value is! List) return const [];
  return [
    for (final item in value)
      if (item is Map && item[key] != null) item[key].toString(),
  ];
}
