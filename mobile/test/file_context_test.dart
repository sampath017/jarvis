import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/services/google_drive_service.dart';

Map<String, dynamic> memory(String id, String name, {String caption = ''}) => {
  'id': id,
  'name': name,
  'caption': caption,
  'mimeType': 'text/plain',
  'url': 'https://drive.google.com/file/d/$id/view',
};

void main() {
  late GoogleDriveService drive;
  setUp(() => drive = GoogleDriveService());
  tearDown(() => drive.dispose());

  for (final name in ['PAN', 'CV', '照片', 'आधार', 'ఆధార్']) {
    test('short and multilingual filenames remain searchable: $name', () {
      drive.memories = [
        memory('match', '$name.pdf'),
        memory('other', 'notes.txt'),
      ];
      expect(drive.contextFor('Find my $name').map((m) => m['id']), ['match']);
    });
  }
  test('common words and bare times do not attach unrelated files', () {
    drive.memories = [memory('unrelated', 'How are you today at 12 36 PM.txt')];
    expect(drive.contextFor('Where was I at 12:36 PM?'), isEmpty);
    expect(drive.contextFor('How are you today?'), isEmpty);
    expect(drive.contextFor('   '), isEmpty);
  });
  test(
    'ties consistently prefer recent cache entries and keep the source unchanged',
    () {
      drive.memories = List.generate(100, (i) => memory('f$i', 'receipt.pdf'));
      final order = drive.memories.map((m) => m['id']).toList();
      expect(
        drive.contextFor('receipt').map((m) => m['id']),
        List.generate(12, (i) => 'f${99 - i}'),
      );
      expect(drive.memories.map((m) => m['id']), order);
    },
  );
  test('attachments survive the cap ahead of highly ranked cached files', () {
    drive.memories = [
      memory('attached', 'unrelated.txt'),
      ...List.generate(30, (i) => memory('f$i', 'receipt report.pdf')),
    ];
    final result = drive.contextFor(
      'receipt report',
      prioritizedIds: ['attached'],
    );
    expect(result.length, 12);
    expect(result.first['id'], 'attached');
    expect(
      result.skip(1).map((m) => m['id']),
      List.generate(11, (i) => 'f${29 - i}'),
    );
  });
  test('word matching is case insensitive and does not match substrings', () {
    drive.memories = [
      memory('match', 'RECEIPT.PDF'),
      memory('other', 'receipted.txt'),
    ];
    expect(drive.contextFor('receipt?').map((m) => m['id']), ['match']);
  });
  test('matching captions contribute distinct query terms to ranking', () {
    drive.memories = [
      memory('best', 'invoice.txt', caption: 'October receipt'),
      memory('recent', 'receipt.txt', caption: 'receipt receipt receipt'),
    ];
    expect(drive.contextFor('October receipt').map((m) => m['id']), [
      'best',
      'recent',
    ]);
  });
}
