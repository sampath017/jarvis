"""
Jarvis Context-Aware Mobile Agent — Central Configuration

All tunable parameters for the simulation. Values are based on BRD specifications
with sensible defaults for the initial simulation phase.

Environment variables are loaded from .env file via python-dotenv.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ── IMU Sampling (BRD Section 3.1, Stage 2) ────────────────────────────────
SAMPLING_RATE_HZ: int = 50          # Accelerometer + gyroscope sample rate
BURST_DURATION_SEC: float = 5.0     # Bounded burst window after activity transition
NUM_AXES: int = 3                   # 3-axis accelerometer + 3-axis gyroscope

# ── Vehicle Fingerprint Profiles ────────────────────────────────────────────
# Royal Enfield Hunter 350 — single-cylinder thumper characteristics
HUNTER_350_PROFILE = {
    "dominant_freq_hz": 30.0,         # Firing frequency of single-cylinder 350cc @ ~1800 RPM
    "dominant_freq_tolerance": 4.0,   # ±Hz for matching
    "z_axis_rms_range": (2.5, 8.0),   # High Z-axis vibration (single-cyl thumper)
    "spectral_energy_range": (50.0, 300.0),
    "harmonic_ratio_min": 0.3,        # Strong harmonics from single-cylinder firing
    "vibration_amplitude_g": 1.2,     # Typical peak vibration amplitude in g
}

# ── Vehicle Classifier (BRD Section 3.1, Stage 4) ──────────────────────────
CLASSIFIER_CONFIDENCE_THRESHOLD: float = 0.75   # Min confidence to classify as Hunter 350
CLASSIFIER_UNCERTAINTY_MAX: float = 0.3          # Max acceptable uncertainty

# Feature weights for distance-based classification
FEATURE_WEIGHTS = {
    "dominant_freq": 0.30,
    "spectral_energy": 0.15,
    "z_rms": 0.20,
    "harmonic_ratio": 0.15,
    "peak_to_peak_z": 0.10,
    "spectral_entropy": 0.10,
}

# ── Session State Machine (BRD Section 3.2) ─────────────────────────────────
SESSION_TTL_SEC: int = 1800          # 30-minute Time-To-Live for paused sessions
PARKING_RADIUS_M: float = 100.0     # Max distance from parking to maintain session
MIN_DWELL_SEC: float = 60.0         # Minimum dwell time to qualify as a "stop"
MAX_SPEED_WALKING_MPS: float = 2.0  # Max speed (m/s) considered walking

# ── Conflict Resolution (BRD Section 3.3, Tier 1) ──────────────────────────
CONFLICT_CONFIDENCE_THRESHOLD: float = 0.6  # Below this → invoke Tier 1
GPS_ACCURACY_POOR_M: float = 50.0           # GPS accuracy worse than this → flag conflict

# ── LLM Configuration (BRD Section 7.1) ─────────────────────────────────────
# Tier 1 uses a small, economical model — it only resolves structured context JSON.
# Tier 2 uses a larger model — it handles agentic command interpretation.
USE_MOCK_LLM: bool = True                          # True = rule-based mock, False = OpenRouter
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_TIER1: str = os.getenv("OPENROUTER_MODEL_TIER1", "qwen/qwen-2.5-7b-instruct")
OPENROUTER_MODEL_TIER2: str = os.getenv("OPENROUTER_MODEL_TIER2", "qwen/qwen-2.5-72b-instruct")
OPENROUTER_MAX_TOKENS: int = 1024
OPENROUTER_TEMPERATURE: float = 0.1                # Low temperature for structured output

# ── Noise & Simulation ──────────────────────────────────────────────────────
NOISE_STD_ACCEL: float = 0.15       # Gaussian noise σ for accelerometer (g)
NOISE_STD_GYRO: float = 0.05        # Gaussian noise σ for gyroscope (rad/s)

# ── POI Database (simulated) ────────────────────────────────────────────────
SIMULATED_POIS = [
    {"name": "Home",                "lat": 17.385,  "lon": 78.4867, "category": "residence"},
    {"name": "Ratnadeep Supermarket", "lat": 17.390, "lon": 78.490,  "category": "grocery"},
    {"name": "Office",              "lat": 17.440,  "lon": 78.350,   "category": "workplace"},
    {"name": "Chai Point Cafe",     "lat": 17.392,  "lon": 78.491,   "category": "cafe"},
    {"name": "Shell Petrol Bunk",   "lat": 17.395,  "lon": 78.488,   "category": "fuel_station"},
    {"name": "Unknown Shop",        "lat": 17.397,  "lon": 78.493,   "category": "unknown"},
]

# ── Audit & Logging ─────────────────────────────────────────────────────────
AUDIT_LOG_FILE: str = "audit_log.jsonl"
EVAL_RESULTS_FILE: str = "eval_results.json"
EVAL_REPORT_FILE: str = "eval_report.md"
