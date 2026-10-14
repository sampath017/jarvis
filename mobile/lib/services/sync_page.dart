/// Validate and collapse ordered changes before touching the local cache.
class SyncPage {
  static const collections = {
    'reminders',
    'notes',
    'places',
    'chat_sessions',
    'chat_messages',
  };
  final String cursor;
  final bool hasMore;
  final bool bootstrap;
  final bool bootstrapComplete;
  final Map<String, List<Map<String, dynamic>>> records;
  final Map<String, List<String>> deleted;

  SyncPage._(
    this.cursor,
    this.hasMore,
    this.bootstrap,
    this.bootstrapComplete,
    this.records,
    this.deleted,
  );

  factory SyncPage.fromJson(Map<String, dynamic> json) {
    final cursor = json['cursor'];
    final events = json['events'];
    if (cursor is! String ||
        cursor.isEmpty ||
        events is! List ||
        events.length > 200 ||
        json['has_more'] is! bool ||
        json['bootstrap'] is! bool) {
      throw const FormatException('Invalid sync page');
    }
    final latest = <String, Map<String, Map<String, dynamic>>>{};
    for (final item in events) {
      if (item is! Map ||
          !collections.contains(item['collection']) ||
          item['id'] is! String ||
          (item['id'] as String).isEmpty ||
          item['deleted'] is! bool ||
          (item['deleted'] == false && item['data'] is! Map)) {
        throw const FormatException('Invalid sync change');
      }
      final event = Map<String, dynamic>.from(item);
      (latest[event['collection']] ??= {})[event['id']] = event;
    }
    final records = <String, List<Map<String, dynamic>>>{};
    final deleted = <String, List<String>>{};
    for (final group in latest.entries) {
      for (final event in group.value.values) {
        if (event['deleted'] == true) {
          (deleted[group.key] ??= []).add(event['id']);
        } else {
          final data = Map<String, dynamic>.from(event['data']);
          if (data['id'] != event['id']) {
            throw const FormatException('Sync identity mismatch');
          }
          (records[group.key] ??= []).add(data);
        }
      }
    }
    return SyncPage._(
      cursor,
      json['has_more'],
      json['bootstrap'],
      json['bootstrap_complete'] == true,
      records,
      deleted,
    );
  }
}
