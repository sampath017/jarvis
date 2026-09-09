import 'package:flutter/material.dart';
import '../../models/feature_vector.dart';
import '../theme.dart';

/// Live Edge Feature Analysis display card per BRD Stage 3.
/// Previews dominant vibration frequency, RMS energy, Zero-Crossing Rate,
/// Spectral Entropy, and vehicle classification signature.
class FeatureCards extends StatelessWidget {
  final FeatureVector? features;

  const FeatureCards({super.key, required this.features});

  @override
  Widget build(BuildContext context) {
    final dominantHz = features?.dominantFreqHz ?? 0.0;
    final zRms = features?.zRms ?? 0.0;
    final motionRms = features?.motionRms ?? 0.0;
    final zcr = features?.zeroCrossingRate ?? 0.0;
    final entropy = features?.spectralEntropy ?? 0.0;
    final modelHint = features?.vehicleClassHint ?? 'STANDBY';
    final confidence = (features?.classificationConfidence ?? 0.0) * 100;

    // Check if within Royal Enfield Hunter 350 typical signature (10 - 15 Hz)
    final isHunterBand = dominantHz >= 9.5 && dominantHz <= 16.0;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isHunterBand
              ? AppTheme.cyan.withValues(alpha: 0.8)
              : AppTheme.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Row(
                  children: const [
                    Icon(Icons.analytics_outlined,
                        size: 14, color: AppTheme.cyan),
                    SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        'VIBRATION SIGNATURE (BRD)',
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: AppTheme.textSecondary,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 0.8,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: (modelHint == 'HUNTER_350'
                          ? AppTheme.cyan
                          : AppTheme.surfaceBright)
                      .withValues(alpha: 0.25),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: modelHint == 'HUNTER_350'
                        ? AppTheme.cyan
                        : AppTheme.border,
                  ),
                ),
                child: Text(
                  '$modelHint (${confidence.toStringAsFixed(0)}%)',
                  style: TextStyle(
                    color: modelHint == 'HUNTER_350'
                        ? AppTheme.cyan
                        : AppTheme.textPrimary,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _FeaturePill(
                  label: 'DOMINANT HZ',
                  value: dominantHz.toStringAsFixed(1),
                  unit: isHunterBand ? 'Hz • Hunter Band' : 'Hz • Peak',
                  highlight: isHunterBand,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _FeaturePill(
                  label: 'Z-RMS',
                  value: zRms.toStringAsFixed(2),
                  unit: 'm/s² • Vertical',
                  highlight: false,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _FeaturePill(
                  label: 'MOTION RMS',
                  value: motionRms.toStringAsFixed(2),
                  unit: 'm/s² • Linear',
                  highlight: false,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _FeaturePill(
                  label: 'ZERO CROSSING',
                  value: zcr.toStringAsFixed(3),
                  unit: 'sign shifts / sec',
                  highlight: false,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _FeaturePill(
                  label: 'SPECTRAL ENTROPY',
                  value: entropy.toStringAsFixed(3),
                  unit: entropy < 0.5 && entropy > 0.0
                      ? 'Harmonic Engine'
                      : 'Noise / Irregular',
                  highlight: entropy < 0.5 && entropy > 0.0,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _FeaturePill extends StatelessWidget {
  final String label;
  final String value;
  final String unit;
  final bool highlight;

  const _FeaturePill({
    required this.label,
    required this.value,
    required this.unit,
    required this.highlight,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
      decoration: BoxDecoration(
        color: AppTheme.surfaceBright,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: highlight ? AppTheme.cyan : AppTheme.border,
          width: highlight ? 1.5 : 1.0,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 9,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 2),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              maxLines: 1,
              style: TextStyle(
                color: highlight ? AppTheme.cyan : AppTheme.textPrimary,
                fontSize: 13,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace',
              ),
            ),
          ),
          const SizedBox(height: 1),
          Text(
            unit,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: highlight ? AppTheme.cyan : AppTheme.textSecondary,
              fontSize: 8,
            ),
          ),
        ],
      ),
    );
  }
}
