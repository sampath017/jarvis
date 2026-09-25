import 'dart:async';

Future<List<Map<String, dynamic>>> runFileReadBatch(
  List<Map<String, dynamic>> actions,
  Future<Map<String, dynamic>> Function(Map<String, dynamic>) read,
) async {
  if (actions.length > 2 ||
      actions.any(
        (action) => !{
          'file_memory_search',
          'file_analyze',
        }.contains(action['operation']),
      )) {
    throw ArgumentError('Only two independent file reads can share a batch.');
  }
  return Future.wait(
    actions.map(
      (action) async => {
        'call_id': action['call_id'],
        'result': await read(action),
      },
    ),
  );
}
