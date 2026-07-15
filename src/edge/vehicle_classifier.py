"""
Stage 4: Vehicle Fingerprint Classifier

Compares extracted features against a stored Hunter 350 reference profile
using a weighted distance metric. Outputs classification with confidence score.
"""

from __future__ import annotations

import math

from ..config import (
    CLASSIFIER_CONFIDENCE_THRESHOLD,
    CLASSIFIER_UNCERTAINTY_MAX,
    FEATURE_WEIGHTS,
    HUNTER_350_PROFILE,
)
from ..models.enums import VehicleClass
from ..models.schemas import ClassificationResult, ExtractedFeatures


# ── Reference Profile ────────────────────────────────────────────────────────
# These are the "expected" feature values for a Hunter 350 IMU burst.
# In production, these would be calibrated from real data.

HUNTER_350_REFERENCE = {
    "dominant_freq": HUNTER_350_PROFILE["dominant_freq_hz"],      # ~30 Hz
    "spectral_energy": 0.15,    # Typical spectral energy for Hunter 350 signal
    "z_rms": 10.2,              # High Z-axis RMS due to gravity + vibration
    "harmonic_ratio": 0.30,     # Strong 2nd harmonic from single-cylinder
    "peak_to_peak_z": 5.0,     # Large Z-axis peak-to-peak
    "spectral_entropy": 3.5,    # Moderate entropy (concentrated energy)
}

# Normalization ranges for each feature (used to scale distances to 0-1)
FEATURE_NORMS = {
    "dominant_freq": 50.0,      # Max expected dominant freq
    "spectral_energy": 1.0,     # Max expected spectral energy
    "z_rms": 15.0,              # Max expected Z RMS
    "harmonic_ratio": 1.0,      # Ratio is 0-1
    "peak_to_peak_z": 15.0,    # Max expected peak-to-peak
    "spectral_entropy": 8.0,    # Max entropy bits
}


def classify_vehicle(features: ExtractedFeatures) -> ClassificationResult:
    """
    Classify the vehicle based on extracted features by comparing
    against the Hunter 350 reference profile.

    Returns a ClassificationResult with vehicle class, confidence,
    uncertainty, and per-feature distances.
    """
    # Extract the key features for comparison
    observed = {
        "dominant_freq": features.accel_freq.dominant_freq_hz,
        "spectral_energy": features.accel_freq.spectral_energy,
        "z_rms": features.accel_z_features.rms,
        "harmonic_ratio": features.accel_freq.harmonic_ratio,
        "peak_to_peak_z": features.accel_z_features.peak_to_peak,
        "spectral_entropy": features.accel_freq.spectral_entropy,
    }

    # Compute normalized distances per feature
    feature_distances: dict[str, float] = {}
    weighted_distance = 0.0
    total_weight = 0.0

    for feat_name, ref_val in HUNTER_350_REFERENCE.items():
        obs_val = observed.get(feat_name, 0.0)
        norm = FEATURE_NORMS.get(feat_name, 1.0)
        dist = abs(obs_val - ref_val) / max(norm, 1e-12)
        feature_distances[feat_name] = round(dist, 4)

        weight = FEATURE_WEIGHTS.get(feat_name, 0.0)
        weighted_distance += weight * dist
        total_weight += weight

    # Normalize weighted distance
    if total_weight > 0:
        weighted_distance /= total_weight

    # Convert distance to confidence (inverse sigmoid-like mapping)
    # distance=0 → confidence=1.0, distance=1 → confidence~0.27
    confidence = math.exp(-2.0 * weighted_distance)
    confidence = max(0.0, min(1.0, confidence))

    # Uncertainty is proportional to distance spread
    dist_values = list(feature_distances.values())
    if len(dist_values) > 1:
        dist_std = float(sum((d - sum(dist_values) / len(dist_values))**2
                             for d in dist_values) / len(dist_values)) ** 0.5
        uncertainty = min(1.0, dist_std + (1.0 - confidence) * 0.5)
    else:
        uncertainty = 1.0 - confidence

    # Determine vehicle class
    is_match = (confidence >= CLASSIFIER_CONFIDENCE_THRESHOLD
                and uncertainty <= CLASSIFIER_UNCERTAINTY_MAX)

    if is_match:
        vehicle_class = VehicleClass.HUNTER_350
    else:
        # Try to infer what it might be based on feature patterns
        vehicle_class = _infer_non_hunter_class(features, confidence)

    return ClassificationResult(
        vehicle_class=vehicle_class,
        confidence=round(confidence, 4),
        uncertainty=round(uncertainty, 4),
        feature_distances=feature_distances,
        is_match=is_match,
    )


def _infer_non_hunter_class(
    features: ExtractedFeatures,
    hunter_confidence: float,
) -> VehicleClass:
    """
    When the signal doesn't match Hunter 350, try to infer what it is.
    Uses Z-axis variance and spectral energy as primary discriminators:
      - Walking: very low spectral energy, ~2Hz dominant freq
      - Car: low Z-axis variance (<0.10), low spectral energy
      - Bus: moderate Z-axis variance (0.10-0.30), mid-range spectral energy
      - Other motorcycle: high Z-axis variance but different dominant freq
    """
    dom_freq = features.accel_freq.dominant_freq_hz
    z_var = features.accel_z_features.variance
    z_pp = features.accel_z_features.peak_to_peak
    spectral_energy = features.accel_freq.spectral_energy

    # Walking: dominant freq ~2Hz, very low spectral energy
    if dom_freq < 5.0 and spectral_energy < 0.02 and z_pp < 2.2:
        return VehicleClass.NOT_VEHICLE

    # Car: low Z-axis variance and low spectral energy (smooth multi-cylinder)
    if z_var < 0.10 and spectral_energy < 0.02:
        return VehicleClass.CAR

    # Bus: moderate Z-axis variance, moderate spectral energy, lower dominant freq
    if 0.10 <= z_var <= 0.30 and spectral_energy < 0.05:
        return VehicleClass.BUS

    # Other motorcycle: high variance/spectral but different frequency profile
    if z_var > 0.20 and spectral_energy > 0.03:
        return VehicleClass.OTHER_MOTORCYCLE

    # If we had some confidence it was Hunter-like, call it unknown
    if hunter_confidence > 0.3:
        return VehicleClass.UNKNOWN

    return VehicleClass.UNKNOWN


def calibrate_reference(feature_samples: list[ExtractedFeatures]) -> dict:
    """
    Build a reference profile from multiple Hunter 350 IMU burst samples.
    Averages the key features across all samples.

    This would be run during the initial calibration phase.
    """
    if not feature_samples:
        return HUNTER_350_REFERENCE.copy()

    avg = {key: 0.0 for key in HUNTER_350_REFERENCE}
    for features in feature_samples:
        avg["dominant_freq"] += features.accel_freq.dominant_freq_hz
        avg["spectral_energy"] += features.accel_freq.spectral_energy
        avg["z_rms"] += features.accel_z_features.rms
        avg["harmonic_ratio"] += features.accel_freq.harmonic_ratio
        avg["peak_to_peak_z"] += features.accel_z_features.peak_to_peak
        avg["spectral_entropy"] += features.accel_freq.spectral_entropy

    n = len(feature_samples)
    return {key: round(val / n, 4) for key, val in avg.items()}
