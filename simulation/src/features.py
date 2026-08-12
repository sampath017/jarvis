"""Synthetic IMU burst generation and compact feature summary extraction."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from typing import Any

from src.constants import DEFAULT_BURST_DURATION_SECONDS, DEFAULT_SAMPLE_RATE_HZ, GRAVITY_MPS2
from src.models import VIBRATION_PROFILES


def iso8601(value: datetime) -> str:
    """Return an API-friendly UTC timestamp with a Z suffix."""
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_feature_summary(
    vehicle_class_hint: str,
    classification_confidence: float,
    seed: int,
    duration_seconds: int = DEFAULT_BURST_DURATION_SECONDS,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> dict[str, Any]:
    """Create a synthetic IMU burst and return only the backend's feature DTO.

    The transient sample arrays emulate the mobile client's bounded capture:
    10 seconds at 50 Hz by default. They are kept in memory only within this
    function and discarded immediately after feature extraction.
    """
    try:
        profile = VIBRATION_PROFILES[vehicle_class_hint]
    except KeyError as error:
        raise ValueError(f"Unsupported vehicle class: {vehicle_class_hint}") from error

    total_samples = duration_seconds * sample_rate_hz
    rng = random.Random(seed)
    accel_x: list[float] = []
    accel_y: list[float] = []
    accel_z_without_gravity: list[float] = []
    gyro: list[float] = []

    for index in range(total_samples):
        timestamp = index / sample_rate_hz
        primary = math.sin(2.0 * math.pi * profile.dominant_hz * timestamp)
        harmonic = math.sin(4.0 * math.pi * profile.dominant_hz * timestamp)
        noise = rng.gauss(0.0, profile.noise)
        accel_x.append(profile.lateral_amplitude * primary + noise)
        accel_y.append(profile.lateral_amplitude * 0.65 * harmonic + noise)
        accel_z_without_gravity.append(
            profile.vertical_amplitude * primary + profile.vertical_amplitude * 0.16 * harmonic + noise
        )
        gyro.append(profile.gyro_amplitude * primary + rng.gauss(0.0, profile.noise / 3.0))

    centered_z = _center(accel_z_without_gravity)
    dominant_bin, dominant_energy = _dominant_frequency_bin(centered_z)
    harmonic_energy = _energy_at_bin(centered_z, dominant_bin * 2)
    acceleration_magnitudes = [
        math.sqrt(x * x + y * y + (z + GRAVITY_MPS2) * (z + GRAVITY_MPS2))
        for x, y, z in zip(accel_x, accel_y, accel_z_without_gravity, strict=True)
    ]

    return {
        "dominant_freq_hz": round(dominant_bin * sample_rate_hz / total_samples, 3),
        "spectral_energy": round(_mean_square(centered_z), 4),
        "z_rms": round(_rms(accel_z_without_gravity), 4),
        "harmonic_ratio": round(harmonic_energy / dominant_energy, 4) if dominant_energy else 0.0,
        "accel_magnitude_mean": round(sum(acceleration_magnitudes) / total_samples, 4),
        "motion_rms": round(_rms(accel_z_without_gravity), 4),
        "gyro_rms": round(_rms(gyro), 4),
        "vehicle_class_hint": vehicle_class_hint,
        "classification_confidence": classification_confidence,
    }


def _center(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    return [value - mean for value in values]


def _mean_square(values: list[float]) -> float:
    return sum(value * value for value in values) / len(values)


def _rms(values: list[float]) -> float:
    return math.sqrt(_mean_square(values))


def _energy_at_bin(samples: list[float], bin_index: int) -> float:
    """Calculate one DFT-bin energy without external numerical dependencies."""
    if not 1 <= bin_index < len(samples) // 2:
        return 0.0
    angle = -2.0 * math.pi * bin_index / len(samples)
    real = sum(value * math.cos(angle * index) for index, value in enumerate(samples))
    imaginary = sum(value * math.sin(angle * index) for index, value in enumerate(samples))
    return real * real + imaginary * imaginary


def _dominant_frequency_bin(samples: list[float]) -> tuple[int, float]:
    candidate_bins = range(1, len(samples) // 2)
    best_bin = max(candidate_bins, key=lambda bin_index: _energy_at_bin(samples, bin_index))
    return best_bin, _energy_at_bin(samples, best_bin)
