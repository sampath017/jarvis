import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_collector/models/activity_day.dart';
import 'package:jarvis_collector/models/activity_map_data.dart';
import 'package:jarvis_collector/ui/theme.dart';
import 'package:jarvis_collector/ui/widgets/activity_map.dart';

ActivityObservation point(
  int minute, {
  double latitude = 12.9,
  double accuracy = 15,
  bool gps = true,
  String activity = 'WALKING',
  String session = 'outing',
  DateTime? fixAt,
}) => ActivityObservation(
  timestamp: DateTime(2026, 10, 4, 17, minute),
  activity: activity,
  transition: 'ENTER',
  sessionId: session,
  latitude: gps ? latitude : null,
  longitude: gps ? 80.2 : null,
  accuracyMeters: gps ? accuracy : null,
  locationObservedAt: fixAt,
  wifiSignals: 1,
);

class OfflineTiles extends TileProvider {
  @override
  ImageProvider getImage(
    TileCoordinates coordinates,
    TileLayer options,
  ) => MemoryImage(
    base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    ),
  );
}

void main() {
  test('links preserve missing samples and reject inaccurate jumps', () {
    final data = ActivityMapData([
      point(0),
      point(1, latitude: 12.901),
      point(2, gps: false),
      point(3, latitude: 12.902),
      point(4, latitude: 12.903),
      point(5, latitude: 13.2),
      point(6, latitude: 13.201, accuracy: 200),
    ]);
    expect(data.fixes, hasLength(6));
    expect(data.links, hasLength(2));
    expect(data.links.map((s) => s.length), [2, 2]);
    expect(data.wifiWithoutCoordinates, 1);
    expect(
      ActivityMapData.canLink(point(0), point(10, latitude: 12.901)),
      false,
    );
    expect(
      ActivityMapData.canLink(
        point(0),
        point(1, latitude: 12.901, session: 'other'),
      ),
      false,
    );
    expect(
      ActivityMapData.canLink(
        point(0, activity: 'STILL'),
        point(1, activity: 'STILL'),
      ),
      false,
    );
  });

  test(
    'reused GPS fixes keep their capture time without inventing later points',
    () {
      final fixAt = DateTime(2026, 10, 4, 16, 59);
      final data = ActivityMapData([
        point(0, fixAt: fixAt),
        point(1, fixAt: fixAt),
      ]);
      expect(data.fixes, hasLength(1));
      expect(ActivityMapData.fixTime(data.fixes.single), fixAt);
      expect(data.links, isEmpty);
    },
  );

  testWidgets('map details and navigation remain readable on a narrow phone', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.darkTheme,
        home: Scaffold(
          body: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: ActivityMap(
                tileProvider: OfflineTiles(),
                observations: [
                  point(0),
                  point(1, latitude: 12.901),
                  point(2, gps: false),
                  point(3, latitude: 12.902, activity: 'STILL', accuracy: 150),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Recorded locations'), findsOneWidget);
    expect(find.text('Stationary'), findsWidgets);
    expect(find.text('Accuracy ±150 m'), findsOneWidget);
    expect(find.text('Approximate location'), findsOneWidget);
    expect(
      find.text('1 Wi-Fi observations have no coordinates to plot.'),
      findsOneWidget,
    );
    expect(find.byType(PolylineLayer), findsNothing);
    await tester.tap(find.byTooltip('Previous recorded location'));
    await tester.pumpAndSettle();
    expect(find.text('Accuracy ±15 m'), findsOneWidget);
    await tester.tap(find.text('Link close GPS fixes'));
    await tester.pumpAndSettle();
    expect(find.byType(PolylineLayer), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
