import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/sync_page.dart';

void main() {
  Map<String, dynamic> page(List<Map<String, dynamic>> events) => {
    'cursor': 'cursor-2',
    'events': events,
    'has_more': false,
    'bootstrap': false,
  };
  test('empty changes do not imply deleting cached records', () {
    final p = SyncPage.fromJson(page([]));
    expect(p.records, isEmpty);
    expect(p.deleted, isEmpty);
  });
  test('last change wins, including delete followed by recreation', () {
    final p = SyncPage.fromJson(
      page([
        {
          'collection': 'notes',
          'id': 'n',
          'deleted': false,
          'data': {'id': 'n', 'content': 'before'},
        },
        {'collection': 'notes', 'id': 'n', 'deleted': true, 'data': null},
        {
          'collection': 'notes',
          'id': 'n',
          'deleted': false,
          'data': {'id': 'n', 'content': 'after'},
        },
      ]),
    );
    expect(p.records['notes']!.single['content'], 'after');
    expect(p.deleted, isEmpty);
  });
  test('malformed changes never become a checkpoint', () {
    expect(
      () => SyncPage.fromJson(
        page([
          {
            'collection': 'notes',
            'id': 'n',
            'deleted': false,
            'data': {'id': 'another'},
          },
        ]),
      ),
      throwsFormatException,
    );
    expect(
      () => SyncPage.fromJson(
        page([
          {'collection': 'arbitrary_sql_table', 'id': 'n', 'deleted': true},
        ]),
      ),
      throwsFormatException,
    );
  });
}
