import 'dart:convert';
import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../theme.dart';

class ChatChartSeries {
  const ChatChartSeries(this.name, this.values);
  final String name;
  final List<double> values;
}

/// A small data contract, not a script or a browser visualization.
class ChatChartData {
  const ChatChartData({
    required this.type,
    required this.title,
    required this.unit,
    required this.labels,
    required this.series,
  });
  final String type, title, unit;
  final List<String> labels;
  final List<ChatChartSeries> series;

  static ChatChartData? tryParse(String source) {
    if (source.length > 16000) return null;
    try {
      final data = jsonDecode(source);
      if (data is! Map || !{'bar', 'line', 'pie'}.contains(data['type'])) {
        return null;
      }
      final title = data['title'];
      final unit = data['unit'] ?? '';
      final labels = data['labels'];
      final rows = data['series'];
      if (title is! String ||
          title.trim().isEmpty ||
          title.length > 120 ||
          unit is! String ||
          unit.length > 32 ||
          labels is! List ||
          labels.isEmpty ||
          labels.length > 24 ||
          labels.any((v) => v is! String || v.isEmpty || v.length > 80) ||
          rows is! List ||
          rows.isEmpty ||
          rows.length > 3) {
        return null;
      }
      final series = <ChatChartSeries>[];
      for (final row in rows) {
        if (row is! Map ||
            row['name'] is! String ||
            (row['name'] as String).length > 80 ||
            row['values'] is! List) {
          return null;
        }
        final values = row['values'] as List;
        if (values.length != labels.length ||
            values.any((v) => v is! num || !v.isFinite || v.abs() > 1e12)) {
          return null;
        }
        series.add(
          ChatChartSeries(
            row['name'],
            values.map((v) => (v as num).toDouble()).toList(),
          ),
        );
      }
      if (data['type'] == 'pie' &&
          (series.length != 1 ||
              labels.length > 12 ||
              series.single.values.any((v) => v < 0) ||
              series.single.values.every((v) => v == 0))) {
        return null;
      }
      return ChatChartData(
        type: data['type'],
        title: title.trim(),
        unit: unit,
        labels: labels.cast<String>(),
        series: series,
      );
    } on FormatException {
      return null;
    }
  }
}

class ChatChart extends StatelessWidget {
  const ChatChart({super.key, required this.data});
  final ChatChartData data;
  static const _colors = [
    AppTheme.primary,
    AppTheme.green,
    AppTheme.amber,
    AppTheme.red,
    Color(0xFFC5A5E8),
    Color(0xFF80CBC4),
  ];

  String _number(num value) => value == value.roundToDouble()
      ? NumberFormat.decimalPattern('en_IN').format(value)
      : value.toString();

  @override
  Widget build(BuildContext context) {
    final values = data.series.expand((s) => s.values).toList();
    final minValue = values.reduce(math.min);
    final maxValue = values.reduce(math.max);
    final lower = math.min(0.0, minValue);
    final upper = math.max(0.0, maxValue);
    final targetStep = upper == lower
        ? 1.0
        : math.max((upper - lower) / 4, 1e-12);
    final magnitude = math
        .pow(10, (math.log(targetStep) / math.ln10).floor())
        .toDouble();
    final ratio = targetStep / magnitude;
    final step =
        magnitude *
        (ratio <= 1
            ? 1
            : ratio <= 2
            ? 2
            : ratio <= 5
            ? 5
            : 10);
    final minY = (lower / step).floor() * step;
    final maxY = math.max(minY + step, (upper / step).ceil() * step);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.fromLTRB(16, 16, 12, 4),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        border: Border.all(color: AppTheme.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            data.title,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          if (data.unit.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                data.unit,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppTheme.textSecondary,
                ),
              ),
            ),
          const SizedBox(height: 20),
          Semantics(
            label: '${data.title}. Chart. Expand View data for exact values.',
            child: ExcludeSemantics(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final width = data.type == 'pie'
                      ? constraints.maxWidth
                      : math.max(
                          constraints.maxWidth,
                          data.labels.length * 64.0,
                        );
                  return SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SizedBox(
                      width: width,
                      height: 230,
                      child: data.type == 'pie'
                          ? _pie()
                          : data.type == 'line'
                          ? _line(minY, maxY, step)
                          : _bar(minY, maxY, step),
                    ),
                  );
                },
              ),
            ),
          ),
          if (data.type != 'pie')
            Wrap(
              spacing: 16,
              runSpacing: 6,
              children: [
                for (var i = 0; i < data.series.length; i++)
                  _legend(data.series[i].name, _colors[i]),
              ],
            )
          else
            Wrap(
              spacing: 14,
              runSpacing: 6,
              children: [
                for (var i = 0; i < data.labels.length; i++)
                  _legend(data.labels[i], _colors[i % _colors.length]),
              ],
            ),
          Material(
            color: Colors.transparent,
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 12),
              title: const Text(
                'View data',
                style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
              ),
              children: [
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columnSpacing: 24,
                    columns: [
                      const DataColumn(label: Text('Label')),
                      for (final s in data.series)
                        DataColumn(
                          label: Text(s.name.isEmpty ? 'Value' : s.name),
                          numeric: true,
                        ),
                    ],
                    rows: [
                      for (var i = 0; i < data.labels.length; i++)
                        DataRow(
                          cells: [
                            DataCell(SelectableText(data.labels[i])),
                            for (final s in data.series)
                              DataCell(SelectableText(_number(s.values[i]))),
                          ],
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _legend(String label, Color color) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 6),
      Flexible(
        child: Text(
          label,
          style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
        ),
      ),
    ],
  );

  FlTitlesData _titles(double interval) => FlTitlesData(
    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
    leftTitles: AxisTitles(
      sideTitles: SideTitles(
        showTitles: true,
        reservedSize: 46,
        interval: interval,
        getTitlesWidget: (value, meta) => Text(
          NumberFormat.compact().format(value),
          style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary),
        ),
      ),
    ),
    bottomTitles: AxisTitles(
      sideTitles: SideTitles(
        showTitles: true,
        reservedSize: 38,
        interval: 1,
        getTitlesWidget: (value, meta) {
          final index = value.round();
          if (index < 0 ||
              index >= data.labels.length ||
              (value - index).abs() > .01) {
            return const SizedBox.shrink();
          }
          return Padding(
            padding: const EdgeInsets.only(top: 8),
            child: SizedBox(
              width: 60,
              child: Text(
                data.labels[index],
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 10,
                  color: AppTheme.textSecondary,
                ),
              ),
            ),
          );
        },
      ),
    ),
  );

  FlGridData _grid(double interval) => FlGridData(
    show: true,
    drawVerticalLine: false,
    horizontalInterval: interval,
    getDrawingHorizontalLine: (_) =>
        const FlLine(color: AppTheme.border, strokeWidth: .5),
  );

  Widget _bar(double minY, double maxY, double step) => BarChart(
    BarChartData(
      minY: minY,
      maxY: maxY,
      titlesData: _titles(step),
      gridData: _grid(step),
      borderData: FlBorderData(show: false),
      barGroups: [
        for (var i = 0; i < data.labels.length; i++)
          BarChartGroupData(
            x: i,
            barRods: [
              for (var s = 0; s < data.series.length; s++)
                BarChartRodData(
                  toY: data.series[s].values[i],
                  color: _colors[s],
                  width: data.series.length == 1 ? 22 : 12,
                  borderRadius: BorderRadius.circular(4),
                ),
            ],
          ),
      ],
    ),
    duration: Duration.zero,
  );

  Widget _line(double minY, double maxY, double step) => LineChart(
    LineChartData(
      minX: 0,
      maxX: math.max(1, data.labels.length - 1).toDouble(),
      minY: minY,
      maxY: maxY,
      titlesData: _titles(step),
      gridData: _grid(step),
      borderData: FlBorderData(show: false),
      lineBarsData: [
        for (var s = 0; s < data.series.length; s++)
          LineChartBarData(
            spots: [
              for (var i = 0; i < data.labels.length; i++)
                FlSpot(i.toDouble(), data.series[s].values[i]),
            ],
            color: _colors[s],
            barWidth: 3,
            isCurved: false,
            dotData: const FlDotData(show: true),
          ),
      ],
    ),
    duration: Duration.zero,
  );

  Widget _pie() {
    final total = data.series.single.values.reduce((a, b) => a + b);
    return PieChart(
      PieChartData(
        centerSpaceRadius: 35,
        sectionsSpace: 3,
        sections: [
          for (var i = 0; i < data.labels.length; i++)
            PieChartSectionData(
              value: data.series.single.values[i],
              color: _colors[i % _colors.length],
              radius: 65,
              title: '${(data.series.single.values[i] / total * 100).round()}%',
              titleStyle: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppTheme.sidebar,
              ),
            ),
        ],
      ),
      duration: Duration.zero,
    );
  }
}
