"""
Stage 2: Bounded IMU Burst Capture (Simulated)

Generates synthetic 3-axis accelerometer + 3-axis gyroscope data that mimics
different vehicle and activity profiles. The Royal Enfield Hunter 350 profile
is based on known single-cylinder 350cc engine characteristics.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from ..config import (
    BURST_DURATION_SEC,
    HUNTER_350_PROFILE,
    NOISE_STD_ACCEL,
    NOISE_STD_GYRO,
    SAMPLING_RATE_HZ,
)
from ..models.enums import VehicleClass
from ..models.schemas import IMUBurst


def generate_imu_burst(
    vehicle: VehicleClass,
    sampling_rate: int = SAMPLING_RATE_HZ,
    duration: float = BURST_DURATION_SEC,
    noise_accel: float = NOISE_STD_ACCEL,
    noise_gyro: float = NOISE_STD_GYRO,
    seed: int | None = None,
) -> IMUBurst:
    """
    Generate a synthetic IMU burst for the given vehicle/activity type.

    Each profile produces characteristic vibration patterns:
    - HUNTER_350: strong ~30Hz single-cylinder vibration, high Z-axis, strong harmonics
    - CAR: smooth, low amplitude, multi-cylinder → higher freq content, less vibration
    - BUS: low-frequency body sway + diesel engine rumble, moderate amplitude
    - OTHER_MOTORCYCLE: different frequency signature (multi-cylinder or different RPM)
    - NOT_VEHICLE: walking pattern (~2Hz step cadence) or still
    """
    rng = np.random.default_rng(seed)
    n_samples = int(sampling_rate * duration)
    t = np.linspace(0, duration, n_samples, endpoint=False)

    profile = _get_vehicle_profile(vehicle)

    # Generate base signals per axis
    accel_x = _generate_axis_signal(t, profile["accel_x"], rng, noise_accel)
    accel_y = _generate_axis_signal(t, profile["accel_y"], rng, noise_accel)
    accel_z = _generate_axis_signal(t, profile["accel_z"], rng, noise_accel)
    gyro_x = _generate_axis_signal(t, profile["gyro_x"], rng, noise_gyro)
    gyro_y = _generate_axis_signal(t, profile["gyro_y"], rng, noise_gyro)
    gyro_z = _generate_axis_signal(t, profile["gyro_z"], rng, noise_gyro)

    # Add gravity offset to Z-axis accelerometer (device is roughly upright)
    accel_z += 9.81

    return IMUBurst(
        timestamp=datetime.now(),
        duration_sec=duration,
        sampling_rate_hz=sampling_rate,
        accel_x=accel_x.tolist(),
        accel_y=accel_y.tolist(),
        accel_z=accel_z.tolist(),
        gyro_x=gyro_x.tolist(),
        gyro_y=gyro_y.tolist(),
        gyro_z=gyro_z.tolist(),
    )


def _generate_axis_signal(
    t: np.ndarray,
    params: dict,
    rng: np.random.Generator,
    noise_std: float,
) -> np.ndarray:
    """Generate a signal for one axis from frequency + amplitude parameters."""
    signal = np.zeros_like(t)

    for component in params.get("components", []):
        freq = component["freq"]
        amp = component["amp"]
        phase = component.get("phase", rng.uniform(0, 2 * np.pi))
        signal += amp * np.sin(2 * np.pi * freq * t + phase)

    # Add DC offset if specified
    signal += params.get("dc_offset", 0.0)

    # Add Gaussian noise
    signal += rng.normal(0, noise_std, len(t))

    return signal


def _get_vehicle_profile(vehicle: VehicleClass) -> dict:
    """Return the synthetic signal profile for a given vehicle type."""
    h350 = HUNTER_350_PROFILE

    if vehicle == VehicleClass.HUNTER_350:
        # Single-cylinder thumper: strong fundamental at ~30Hz + harmonics
        dom_freq = h350["dominant_freq_hz"]
        amp = h350["vibration_amplitude_g"]
        return {
            "accel_x": {"components": [
                {"freq": dom_freq, "amp": amp * 0.4},
                {"freq": dom_freq * 2, "amp": amp * 0.15},  # 2nd harmonic
                {"freq": 5.0, "amp": 0.2},                  # road vibration
            ]},
            "accel_y": {"components": [
                {"freq": dom_freq, "amp": amp * 0.5},
                {"freq": dom_freq * 2, "amp": amp * 0.2},
                {"freq": 7.0, "amp": 0.15},
            ]},
            "accel_z": {"components": [
                {"freq": dom_freq, "amp": amp * 1.0},        # Strongest on Z (vertical)
                {"freq": dom_freq * 2, "amp": amp * 0.35},   # Strong 2nd harmonic
                {"freq": dom_freq * 3, "amp": amp * 0.1},    # 3rd harmonic
                {"freq": 3.0, "amp": 0.3},                   # road bumps
            ]},
            "gyro_x": {"components": [
                {"freq": dom_freq, "amp": 0.3},
                {"freq": dom_freq * 2, "amp": 0.1},
            ]},
            "gyro_y": {"components": [
                {"freq": dom_freq, "amp": 0.25},
                {"freq": 4.0, "amp": 0.08},
            ]},
            "gyro_z": {"components": [
                {"freq": dom_freq, "amp": 0.15},
                {"freq": dom_freq * 2, "amp": 0.05},
            ]},
        }

    elif vehicle == VehicleClass.CAR:
        # Multi-cylinder car: smoother, lower amplitude, higher freq content
        return {
            "accel_x": {"components": [
                {"freq": 45.0, "amp": 0.15},
                {"freq": 22.0, "amp": 0.1},
                {"freq": 3.0, "amp": 0.08},
            ]},
            "accel_y": {"components": [
                {"freq": 45.0, "amp": 0.12},
                {"freq": 20.0, "amp": 0.08},
            ]},
            "accel_z": {"components": [
                {"freq": 45.0, "amp": 0.2},
                {"freq": 22.0, "amp": 0.15},
                {"freq": 8.0, "amp": 0.1},
            ]},
            "gyro_x": {"components": [{"freq": 45.0, "amp": 0.05}]},
            "gyro_y": {"components": [{"freq": 45.0, "amp": 0.04}]},
            "gyro_z": {"components": [{"freq": 20.0, "amp": 0.03}]},
        }

    elif vehicle == VehicleClass.BUS:
        # Large diesel vehicle: low-frequency sway + engine rumble
        return {
            "accel_x": {"components": [
                {"freq": 2.0, "amp": 0.5},   # body sway
                {"freq": 15.0, "amp": 0.3},  # diesel engine
                {"freq": 30.0, "amp": 0.1},
            ]},
            "accel_y": {"components": [
                {"freq": 1.5, "amp": 0.4},
                {"freq": 15.0, "amp": 0.25},
            ]},
            "accel_z": {"components": [
                {"freq": 15.0, "amp": 0.4},
                {"freq": 3.0, "amp": 0.3},
                {"freq": 30.0, "amp": 0.15},
            ]},
            "gyro_x": {"components": [
                {"freq": 1.5, "amp": 0.2},
                {"freq": 15.0, "amp": 0.1},
            ]},
            "gyro_y": {"components": [
                {"freq": 2.0, "amp": 0.15},
            ]},
            "gyro_z": {"components": [
                {"freq": 1.0, "amp": 0.1},
            ]},
        }

    elif vehicle == VehicleClass.OTHER_MOTORCYCLE:
        # Different motorcycle — e.g. multi-cylinder with different RPM
        return {
            "accel_x": {"components": [
                {"freq": 50.0, "amp": 0.6},     # Higher freq (multi-cyl or high RPM)
                {"freq": 100.0, "amp": 0.2},
                {"freq": 5.0, "amp": 0.15},
            ]},
            "accel_y": {"components": [
                {"freq": 50.0, "amp": 0.5},
                {"freq": 100.0, "amp": 0.15},
            ]},
            "accel_z": {"components": [
                {"freq": 50.0, "amp": 0.7},
                {"freq": 100.0, "amp": 0.25},
                {"freq": 25.0, "amp": 0.1},
            ]},
            "gyro_x": {"components": [{"freq": 50.0, "amp": 0.2}]},
            "gyro_y": {"components": [{"freq": 50.0, "amp": 0.15}]},
            "gyro_z": {"components": [{"freq": 50.0, "amp": 0.1}]},
        }

    else:
        # NOT_VEHICLE / UNKNOWN: walking or still
        return {
            "accel_x": {"components": [
                {"freq": 2.0, "amp": 0.3},   # walking cadence
                {"freq": 4.0, "amp": 0.1},   # arm swing harmonic
            ]},
            "accel_y": {"components": [
                {"freq": 2.0, "amp": 0.4},
                {"freq": 4.0, "amp": 0.15},
            ]},
            "accel_z": {"components": [
                {"freq": 2.0, "amp": 0.5},   # vertical bounce from steps
                {"freq": 4.0, "amp": 0.2},
            ]},
            "gyro_x": {"components": [{"freq": 2.0, "amp": 0.1}]},
            "gyro_y": {"components": [{"freq": 2.0, "amp": 0.08}]},
            "gyro_z": {"components": [{"freq": 1.0, "amp": 0.05}]},
        }
