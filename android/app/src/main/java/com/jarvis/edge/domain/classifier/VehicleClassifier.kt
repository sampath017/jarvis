package com.jarvis.edge.domain.classifier

import com.jarvis.edge.data.remote.FeatureSummary
import com.jarvis.edge.models.VehicleClassification
import kotlin.math.exp

object VehicleClassifier {

    // A stationary phone still reads roughly 9.8 m/s² because of gravity.  The
    // vehicle profile below is meaningful only after an IMU burst contains real
    // motion, not merely after Activity Recognition suggests IN_VEHICLE.
    private const val MIN_MOTION_RMS = 0.25

    // expected profile characteristics (Royal Enfield Hunter 350)
    private const val REF_DOMINANT_FREQ = 30.0
    private const val REF_SPECTRAL_ENERGY = 0.15
    private const val REF_Z_RMS = 10.2
    private const val REF_HARMONIC_RATIO = 0.30

    // Normalisation ranges (denominators to scale difference 0-1)
    private const val NORM_DOMINANT_FREQ = 50.0
    private const val NORM_SPECTRAL_ENERGY = 1.0
    private const val NORM_Z_RMS = 15.0
    private const val NORM_HARMONIC_RATIO = 1.0

    // Feature Weights
    private const val WEIGHT_DOMINANT_FREQ = 0.40
    private const val WEIGHT_SPECTRAL_ENERGY = 0.20
    private const val WEIGHT_Z_RMS = 0.25
    private const val WEIGHT_HARMONIC_RATIO = 0.15

    fun classify(features: FeatureSummary): VehicleClassification {
        if (features.motionRms < MIN_MOTION_RMS && features.gyroRms < MIN_GYRO_RMS) {
            return VehicleClassification(
                vehicleClass = "NOT_VEHICLE",
                confidence = 0.0,
                isMatch = false
            )
        }

        // Calculate normalized distances
        val distFreq = Math.abs(features.dominantFreqHz - REF_DOMINANT_FREQ) / NORM_DOMINANT_FREQ
        val distEnergy = Math.abs(features.spectralEnergy - REF_SPECTRAL_ENERGY) / NORM_SPECTRAL_ENERGY
        val distZ = Math.abs(features.zRms - REF_Z_RMS) / NORM_Z_RMS
        val distHarmonic = Math.abs(features.harmonicRatio - REF_HARMONIC_RATIO) / NORM_HARMONIC_RATIO

        // Weighted distance calculation
        val weightedDist = (
            (distFreq * WEIGHT_DOMINANT_FREQ) +
            (distEnergy * WEIGHT_SPECTRAL_ENERGY) +
            (distZ * WEIGHT_Z_RMS) +
            (distHarmonic * WEIGHT_HARMONIC_RATIO)
        )

        // Convert distance to confidence using exponential decay mapping
        // distance=0 -> confidence=1.0, distance=1 -> confidence ~ 0.13
        val confidence = exp(-2.0 * weightedDist)
        val isMatch = confidence >= 0.75

        val classification = if (isMatch) {
            "HUNTER_350"
        } else {
            // Infer what it might be
            inferNonHunterClass(features, confidence)
        }

        return VehicleClassification(
            vehicleClass = classification,
            confidence = confidence,
            isMatch = isMatch
        )
    }

    private const val MIN_GYRO_RMS = 0.02

    private fun inferNonHunterClass(features: FeatureSummary, confidence: Double): String {
        // Simple heuristic fallback
        return if (features.dominantFreqHz < 5.0 && features.spectralEnergy < 0.02) {
            "NOT_VEHICLE"
        } else if (features.zRms < 9.9 && features.spectralEnergy < 0.02) {
            "CAR"
        } else if (features.zRms in 9.9..10.1 && features.spectralEnergy < 0.05) {
            "BUS"
        } else if (features.spectralEnergy > 0.03) {
            "OTHER_MOTORCYCLE"
        } else {
            "UNKNOWN"
        }
    }
}
