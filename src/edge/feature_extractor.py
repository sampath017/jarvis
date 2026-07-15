"""
Stage 3: Deterministic Edge Feature Extraction

Implements ALL time-domain and frequency-domain features from BRD Section 3.1.
Processes raw IMU burst data into compact feature vectors for classification.
"""

from __future__ import annotations

import numpy as np

from ..models.schemas import (
    AxisFeatures,
    ExtractedFeatures,
    FrequencyFeatures,
    IMUBurst,
)


def extract_features(burst: IMUBurst) -> ExtractedFeatures:
    """
    Extract the full feature set from an IMU burst.

    Time-domain features (per axis):
        mean, median, min, max, variance, std, RMS, peak-to-peak, zero-crossing rate

    Frequency-domain features (per sensor group):
        dominant freq, secondary peaks, spectral energy, spectral entropy,
        band energy (low/mid/high), harmonic ratio, peak-freq stability

    Cross-axis and magnitude features:
        signal magnitude area, magnitude stats, axis correlations, jerk
    """
    ax = np.array(burst.accel_x)
    ay = np.array(burst.accel_y)
    az = np.array(burst.accel_z)
    gx = np.array(burst.gyro_x)
    gy = np.array(burst.gyro_y)
    gz = np.array(burst.gyro_z)
    fs = burst.sampling_rate_hz

    # ── Time-domain per axis ────────────────────────────────────────────
    accel_x_feat = _axis_time_features(ax)
    accel_y_feat = _axis_time_features(ay)
    accel_z_feat = _axis_time_features(az)
    gyro_x_feat = _axis_time_features(gx)
    gyro_y_feat = _axis_time_features(gy)
    gyro_z_feat = _axis_time_features(gz)

    # ── Magnitude statistics ────────────────────────────────────────────
    accel_mag = np.sqrt(ax**2 + ay**2 + az**2)
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    sma = float(np.mean(np.abs(ax)) + np.mean(np.abs(ay)) + np.mean(np.abs(az)))

    # ── Cross-axis correlations ─────────────────────────────────────────
    accel_xy_corr = _safe_correlation(ax, ay)
    accel_xz_corr = _safe_correlation(ax, az)
    accel_yz_corr = _safe_correlation(ay, az)

    # ── Jerk (rate of change of acceleration) ───────────────────────────
    dt = 1.0 / fs
    jerk = np.diff(accel_mag) / dt
    jerk_mean = float(np.mean(np.abs(jerk))) if len(jerk) > 0 else 0.0
    jerk_std = float(np.std(jerk)) if len(jerk) > 0 else 0.0

    # ── Frequency-domain ────────────────────────────────────────────────
    # Combine accel axes for overall frequency analysis
    accel_combined = accel_mag
    gyro_combined = gyro_mag
    accel_freq = _frequency_features(accel_combined, fs)
    gyro_freq = _frequency_features(gyro_combined, fs)

    # Accel/gyro dominant frequency correlation
    freq_corr = 1.0 - abs(accel_freq.dominant_freq_hz - gyro_freq.dominant_freq_hz) / (fs / 2)
    freq_corr = max(0.0, min(1.0, freq_corr))

    return ExtractedFeatures(
        accel_x_features=accel_x_feat,
        accel_y_features=accel_y_feat,
        accel_z_features=accel_z_feat,
        gyro_x_features=gyro_x_feat,
        gyro_y_features=gyro_y_feat,
        gyro_z_features=gyro_z_feat,
        accel_magnitude_mean=float(np.mean(accel_mag)),
        accel_magnitude_std=float(np.std(accel_mag)),
        gyro_magnitude_mean=float(np.mean(gyro_mag)),
        gyro_magnitude_std=float(np.std(gyro_mag)),
        signal_magnitude_area=sma,
        accel_xy_correlation=accel_xy_corr,
        accel_xz_correlation=accel_xz_corr,
        accel_yz_correlation=accel_yz_corr,
        jerk_mean=jerk_mean,
        jerk_std=jerk_std,
        accel_freq=accel_freq,
        gyro_freq=gyro_freq,
        accel_gyro_freq_correlation=freq_corr,
    )


def _axis_time_features(data: np.ndarray) -> AxisFeatures:
    """Compute time-domain features for a single axis."""
    if len(data) == 0:
        return AxisFeatures()

    mean_val = float(np.mean(data))
    rms = float(np.sqrt(np.mean(data**2)))
    min_val = float(np.min(data))
    max_val = float(np.max(data))

    # Zero-crossing rate (using mean-subtracted signal)
    centered = data - mean_val
    zero_crossings = np.sum(np.abs(np.diff(np.sign(centered))) > 0)
    zcr = float(zero_crossings / len(data))

    return AxisFeatures(
        mean=mean_val,
        median=float(np.median(data)),
        min_val=min_val,
        max_val=max_val,
        variance=float(np.var(data)),
        std_dev=float(np.std(data)),
        rms=rms,
        peak_to_peak=max_val - min_val,
        zero_crossing_rate=zcr,
    )


def _frequency_features(data: np.ndarray, fs: int) -> FrequencyFeatures:
    """Compute frequency-domain features using FFT."""
    if len(data) < 4:
        return FrequencyFeatures()

    # Remove DC component
    data_centered = data - np.mean(data)

    # Apply Hanning window to reduce spectral leakage
    window = np.hanning(len(data_centered))
    windowed = data_centered * window

    # FFT
    n = len(windowed)
    fft_vals = np.fft.rfft(windowed)
    fft_mag = np.abs(fft_vals) / n
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    # Skip DC bin (index 0)
    fft_mag = fft_mag[1:]
    freqs = freqs[1:]

    if len(fft_mag) == 0:
        return FrequencyFeatures()

    # Power spectrum
    power = fft_mag**2

    # Dominant frequency
    dom_idx = int(np.argmax(fft_mag))
    dominant_freq = float(freqs[dom_idx])
    dominant_mag = float(fft_mag[dom_idx])

    # Secondary frequency (exclude ±2 bins around dominant)
    mask = np.ones(len(fft_mag), dtype=bool)
    lo = max(0, dom_idx - 2)
    hi = min(len(fft_mag), dom_idx + 3)
    mask[lo:hi] = False
    secondary_freq = 0.0
    if np.any(mask):
        sec_idx = int(np.argmax(fft_mag[mask]))
        # Map back to original index
        masked_indices = np.where(mask)[0]
        secondary_freq = float(freqs[masked_indices[sec_idx]])

    # Spectral energy
    spectral_energy = float(np.sum(power))

    # Spectral entropy
    power_norm = power / (np.sum(power) + 1e-12)
    spectral_entropy = float(-np.sum(power_norm * np.log2(power_norm + 1e-12)))

    # Frequency band energy
    nyquist = fs / 2
    low_mask = freqs <= 10.0
    mid_mask = (freqs > 10.0) & (freqs <= 25.0)
    high_mask = freqs > 25.0
    low_energy = float(np.sum(power[low_mask])) if np.any(low_mask) else 0.0
    mid_energy = float(np.sum(power[mid_mask])) if np.any(mid_mask) else 0.0
    high_energy = float(np.sum(power[high_mask])) if np.any(high_mask) else 0.0

    # Harmonic ratio: power at 2× dominant freq / power at dominant freq
    harmonic_freq = dominant_freq * 2
    harmonic_ratio = 0.0
    if harmonic_freq < nyquist and dominant_mag > 1e-12:
        harm_idx = int(np.argmin(np.abs(freqs - harmonic_freq)))
        harmonic_ratio = float(fft_mag[harm_idx] / dominant_mag)

    # Peak-frequency stability (coefficient of variation of top-5 peaks)
    top_k = min(5, len(fft_mag))
    top_indices = np.argsort(fft_mag)[-top_k:]
    top_freqs = freqs[top_indices]
    peak_stability = 0.0
    if len(top_freqs) > 1 and np.mean(top_freqs) > 1e-12:
        peak_stability = float(1.0 - np.std(top_freqs) / np.mean(top_freqs))
        peak_stability = max(0.0, peak_stability)

    return FrequencyFeatures(
        dominant_freq_hz=dominant_freq,
        secondary_freq_hz=secondary_freq,
        spectral_energy=spectral_energy,
        spectral_entropy=spectral_entropy,
        low_band_energy=low_energy,
        mid_band_energy=mid_energy,
        high_band_energy=high_energy,
        harmonic_ratio=harmonic_ratio,
        peak_freq_stability=peak_stability,
    )


def _safe_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Pearson correlation, returning 0 if undefined."""
    if len(a) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0.0
    corr_matrix = np.corrcoef(a, b)
    return float(corr_matrix[0, 1])
