import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_collector/services/satellite_map.dart';
import 'package:jarvis_collector/ui/widgets/chat_message_content.dart';
import 'package:jarvis_collector/ui/widgets/satellite_map_card.dart';

const _card =
    '''{"latitude":12.83713,"longitude":80.2256,"place_name":"Home","zoom":19,
"boundary":{"polygon":[{"latitude":12.8370,"longitude":80.2254},
{"latitude":12.8373,"longitude":80.2254},{"latitude":12.8373,"longitude":80.2258}],
"confidence":0.85,"uncertainty_m":12}}''';

Uint8List _pngHeader({int dimension = 1280}) {
  final bytes = Uint8List(24);
  bytes.setAll(0, [137, 80, 78, 71, 13, 10, 26, 10]);
  ByteData.sublistView(bytes)
    ..setUint32(16, dimension)
    ..setUint32(20, dimension);
  return bytes;
}

void main() {
  test(
    'departure view uses its own saved-place estimate without changing data',
    () {
      final boundary = (jsonDecode(_card) as Map)['boundary'];
      final reminder = <String, dynamic>{
        'dynamic_policy': jsonEncode({
          'version': 2,
          'trigger': 'exit',
          'origin': {
            'place_id': 'home',
            'name': 'Home',
            'latitude': 12.83713,
            'longitude': 80.2256,
          },
        }),
      };
      final places = <Map<String, dynamic>>[
        {'id': 'other-home', 'name': 'Home', 'boundary_json': '{"polygon":[]}'},
        {'id': 'home', 'name': 'Home', 'boundary_json': jsonEncode(boundary)},
      ];
      final before = jsonEncode([reminder, places]);
      final data = SatelliteMapData.fromReminder(reminder, places)!;
      expect(data.placeId, 'home');
      expect(data.polygon.length, 3);
      expect(data.zoom, 19);
      expect(jsonEncode([reminder, places]), before);
      for (final zoom in [18, 21, 17, 22, '18']) {
        final estimated = SatelliteMapData.fromReminder(reminder, [
          {
            'id': 'home',
            'name': 'Home',
            'boundary_json': jsonEncode({
              ...boundary,
              'imagery': {'zoom': zoom},
            }),
          },
        ])!;
        expect(
          estimated.zoom,
          zoom is int && zoom >= 18 && zoom <= 21 ? zoom : 19,
        );
        expect(estimated.polygon.length, 3);
      }
      expect(
        SatelliteMapData.fromReminder({'dynamic_policy': 'broken'}, places),
        isNull,
      );
      expect(
        SatelliteMapData.fromReminder({'dynamic_policy': null}, places),
        isNull,
      );
      expect(
        SatelliteMapData.fromReminder({
          'dynamic_policy': jsonEncode({
            'trigger': 'exit',
            'origin': {
              'name': 'Home',
              'latitude': 12.83713,
              'longitude': 80.2256,
            },
          }),
        }, places)!.polygon,
        isEmpty,
      ); // Ambiguous names never select a footprint.
    },
  );

  test(
    'bounded satellite card rejects malformed or executable-shaped data',
    () {
      final data = SatelliteMapData.tryParse(_card)!;
      expect(data.placeName, 'Home');
      expect(data.polygon.length, 3);
      expect(data.confidence, 0.85);
      expect(data.uncertaintyMetres, 12);
      for (final source in [
        'not JSON',
        '{"latitude":90,"longitude":80}',
        '{"latitude":12,"longitude":181}',
        '{"latitude":12,"longitude":80,"zoom":19.2}',
        '{"latitude":12,"longitude":80,"zoom":22}',
        '{"latitude":12,"longitude":80,"boundary":{"polygon":[{}]}}',
        _card.replaceFirst('0.85', '1.5'),
        _card.replaceFirst('"uncertainty_m":12', '"uncertainty_m":-1'),
      ]) {
        expect(SatelliteMapData.tryParse(source), isNull, reason: source);
      }
    },
  );

  test('Web Mercator overlay stays aligned at centre and scale=2 output', () {
    const data = SatelliteMapData(latitude: 0, longitude: 0, zoom: 19);
    expect(data.project(0, 0, 640), const Offset(320, 320));
    // 256 * 2^19 is the logical world width at zoom 19.
    const degreesPerPixel = 360 / (256 * 524288);
    expect(
      data.project(0, degreesPerPixel * 100, 640).dx,
      closeTo(420, 0.00001),
    );
    expect(
      data.project(0, degreesPerPixel * 100, 320).dx,
      closeTo(210, 0.00001),
    );
    expect(data.project(0.0001, 0, 640).dy, lessThan(320));
    const dateline = SatelliteMapData(latitude: 0, longitude: 180, zoom: 19);
    expect(dateline.project(0, -180, 640), const Offset(320, 320));
  });

  test(
    'image request uses only configured API and never sends boundary or URLs',
    () async {
      var requests = 0;
      final client = MockClient((request) async {
        requests++;
        expect(request.method, 'POST');
        expect(
          request.url.toString(),
          'https://debug.example/mobile/satellite-map',
        );
        expect(request.headers['X-User-ID'], 'synthetic-owner');
        expect(jsonDecode(request.body), {
          'latitude': 12.83713,
          'longitude': 80.2256,
          'zoom': 19,
        });
        return http.Response.bytes(
          _pngHeader(),
          200,
          headers: {'content-type': 'image/png'},
        );
      });
      addTearDown(client.close);
      final image = await SatelliteMapService.load(
        SatelliteMapData.tryParse(_card)!,
        client: client,
        baseUrl: 'https://debug.example',
        userId: 'synthetic-owner',
      );
      expect(image.length, 24);
      expect(requests, 1);
    },
  );

  test(
    'provider errors, invalid bytes and wrong image geometry are bounded',
    () async {
      for (final response in [
        http.Response('private provider credential or request detail', 503),
        http.Response(
          '<script>bad</script>',
          200,
          headers: {'content-type': 'image/png'},
        ),
        http.Response.bytes(
          _pngHeader(dimension: 4096),
          200,
          headers: {'content-type': 'image/png'},
        ),
        http.Response.bytes(
          _pngHeader(),
          200,
          headers: {'content-type': 'text/html'},
        ),
      ]) {
        final client = MockClient((_) async => response);
        addTearDown(client.close);
        await expectLater(
          SatelliteMapService.load(
            SatelliteMapData.tryParse(_card)!,
            client: client,
            baseUrl: 'https://debug.example',
            userId: 'u',
          ),
          throwsA(
            isA<SatelliteMapException>().having(
              (e) => e.message,
              'safe explanation',
              isNot(contains('private provider')),
            ),
          ),
        );
      }
    },
  );

  testWidgets('chat renders non-editable estimated map with explicit retry', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ChatMessageContent(
              text: 'Your location\n\n```satellite-map\n$_card\n```',
              satelliteImageLoader: (_) async {
                calls++;
                throw const SatelliteMapException(
                  'Satellite image is unavailable. Try again.',
                );
              },
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.byType(SatelliteMapCard), findsOneWidget);
    expect(find.text('Home · Satellite view'), findsOneWidget);
    expect(find.textContaining('not a surveyed fence'), findsOneWidget);
    expect(find.textContaining('12 m'), findsOneWidget);
    expect(find.text('Save boundary'), findsNothing);
    expect(calls, 1);
    await tester.tap(find.text('Retry image'));
    await tester.pump();
    expect(calls, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('invalid cards stay inert and user text never loads imagery', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              ChatMessageContent(
                text: '```satellite-map\n{"url":"file:///private"}\n```',
                satelliteImageLoader: (_) async {
                  calls++;
                  return _pngHeader();
                },
              ),
              ChatMessageContent(
                text: '```satellite-map\n$_card\n```',
                isUser: true,
                satelliteImageLoader: (_) async {
                  calls++;
                  return _pngHeader();
                },
              ),
            ],
          ),
        ),
      ),
    );
    expect(calls, 0);
    expect(find.byType(SatelliteMapCard), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
