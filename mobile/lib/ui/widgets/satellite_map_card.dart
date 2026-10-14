import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../services/satellite_map.dart';
import '../theme.dart';

typedef SatelliteImageLoader =
    Future<Uint8List> Function(SatelliteMapData data);

/// Satellite imagery with a clearly labelled, non-editable estimated footprint.
class SatelliteMapCard extends StatefulWidget {
  const SatelliteMapCard({super.key, required this.data, this.loadImage});
  final SatelliteMapData data;
  final SatelliteImageLoader? loadImage;

  @override
  State<SatelliteMapCard> createState() => _SatelliteMapCardState();
}

class _SatelliteMapCardState extends State<SatelliteMapCard> {
  late Future<Uint8List> _image;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(SatelliteMapCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.data.imageKey != widget.data.imageKey) _load();
  }

  void _load() {
    _image = Future<Uint8List>.sync(
      () => (widget.loadImage ?? SatelliteMapService.load)(widget.data),
    );
    // A retry can fail before the next frame attaches FutureBuilder. Consume
    // that error immediately as well; FutureBuilder still displays its result.
    _image.ignore();
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    final details = <String>[
      if (data.confidence != null)
        '${(data.confidence! * 100).round()}% image interpretation confidence',
      if (data.uncertaintyMetres != null)
        'Boundary uncertainty about ${data.uncertaintyMetres!.round()} m',
    ];
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        border: Border.all(color: AppTheme.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              data.placeName.isEmpty
                  ? 'Google Maps satellite view'
                  : '${data.placeName} · Satellite view',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          FutureBuilder<Uint8List>(
            future: _image,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const SizedBox(
                  height: 180,
                  child: Center(
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              }
              if (snapshot.hasError) {
                return Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: [
                      Text(
                        snapshot.error is SatelliteMapException
                            ? (snapshot.error! as SatelliteMapException).message
                            : 'Could not load the satellite image.',
                      ),
                      TextButton.icon(
                        onPressed: () => setState(_load),
                        icon: const Icon(Icons.refresh),
                        label: const Text('Retry image'),
                      ),
                    ],
                  ),
                );
              }
              if (!snapshot.hasData) {
                return const SizedBox(
                  height: 180,
                  child: Center(
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              }
              return _SatelliteImage(data: data, bytes: snapshot.data!);
            },
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              data.polygon.isEmpty
                  ? 'Satellite imagery. No boundary estimate is available.'
                  : 'Estimated boundary shown in amber. This is one piece of departure evidence, '
                        'not a surveyed fence.${details.isEmpty ? '' : '\n${details.join(' · ')}'}',
              style: const TextStyle(
                fontSize: 12,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SatelliteImage extends StatelessWidget {
  const _SatelliteImage({required this.data, required this.bytes});
  final SatelliteMapData data;
  final Uint8List bytes;

  @override
  Widget build(BuildContext context) => AspectRatio(
    aspectRatio: 1,
    child: LayoutBuilder(
      builder: (context, constraints) => Stack(
        fit: StackFit.expand,
        children: [
          // Keep the entire provider image, including its native attribution.
          Image.memory(
            bytes,
            fit: BoxFit.contain,
            gaplessPlayback: true,
            semanticLabel: 'Google Maps satellite image of ${data.placeName}',
            errorBuilder: (_, _, _) => const Center(
              child: Text('Could not decode the satellite image.'),
            ),
          ),
          if (data.polygon.isNotEmpty)
            IgnorePointer(child: CustomPaint(painter: _BoundaryPainter(data))),
        ],
      ),
    ),
  );
}

class _BoundaryPainter extends CustomPainter {
  const _BoundaryPainter(this.data);
  final SatelliteMapData data;

  @override
  void paint(Canvas canvas, Size size) {
    // Never draw over the provider's attribution strip at the image bottom.
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, size.width, size.height * 0.94));
    final points = data.polygon
        .map((p) => data.project(p.latitude, p.longitude, size.width))
        .toList();
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    path.close();
    canvas.drawPath(
      path,
      Paint()..color = AppTheme.amber.withValues(alpha: 0.16),
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = AppTheme.amber
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_BoundaryPainter oldDelegate) => data != oldDelegate.data;
}
