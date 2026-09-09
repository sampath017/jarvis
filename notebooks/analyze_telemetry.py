"""
Jarvis Context-Aware Mobile Agent: Telemetry Analysis & OpenRouter Intent Reasoning

Covers:
1. Ingesting 50 Hz multi-sensor CSV and low-telemetry JSON metadata collected from Poco X4 Pro 5G
2. Deterministic Edge Feature Extraction (BRD Stage 3): FFT Dominant Frequency, RMS, ZCR, Spectral Entropy
3. GPS Kinematics & Journey Checkpoint Tracking
4. Tier 1 Context Reasoner via OpenRouter (Vehicle & Place Resolution)
5. Tier 2 Agentic Intent Deduction via OpenRouter (Executing Reminders, Tasks, Notes)
"""

from __future__ import annotations

import glob
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy.fft import rfft, rfftfreq

# Resolve project paths
NOTEBOOKS_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = NOTEBOOKS_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = NOTEBOOKS_DIR / "data"
FIGURES_DIR = NOTEBOOKS_DIR / "figures"
FIGURES_DIR.mkdir(exist_ok=True, parents=True)

# Add backend to sys.path for importing Jarvis cloud modules
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load OpenRouter API credentials
load_dotenv(BACKEND_DIR / ".env")

from src.backend.crud_store import CRUDStore
from src.cloud.function_registry import FunctionRegistry
from src.cloud.tier1_reasoner import Tier1Reasoner
from src.cloud.tier2_orchestrator import Tier2Orchestrator
from src.models.enums import CRUDEntity
from src.models.schemas import ContextPacket, FeatureSummary, GPSReading, Tier1Request, Tier2Request


# ── 1. Telemetry Ingestion ───────────────────────────────────────────────────

def load_telemetry_files() -> tuple[pd.DataFrame, dict | None, str]:
    """Finds and loads the latest recorded session CSV and JSON from notebooks/data."""
    csv_files = sorted(glob.glob(str(DATA_DIR / "*.csv")) + glob.glob(str(DATA_DIR / "**/*.csv")))
    if not csv_files:
        raise FileNotFoundError(f"No CSV recordings found in {DATA_DIR}")

    # Select the richest session (prefer 164443 or latest)
    selected_csv = None
    for f in csv_files:
        if "164443" in f:
            selected_csv = f
            break
    if not selected_csv:
        selected_csv = csv_files[-1]

    session_id = Path(selected_csv).stem
    json_path = Path(selected_csv).parent / f"{session_id}_summary.json"
    if not json_path.exists():
        # Check in DATA_DIR
        json_path = DATA_DIR / f"{session_id}_summary.json"

    summary_json = None
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as jf:
            summary_json = json.load(jf)

    print(f"[+] Loaded Session: {session_id}")
    print(f"    CSV File: {selected_csv} ({os.path.getsize(selected_csv):,} bytes)")
    if summary_json:
        print(f"    Summary JSON: {json_path} ({os.path.getsize(json_path):,} bytes)")

    df = pd.read_csv(selected_csv)
    return df, summary_json, session_id


# ── 2. Signal Processing & Vibration Feature Extraction ──────────────────────

def compute_fft_and_spectral_features(signal: np.ndarray, sampling_rate: float = 50.0) -> dict:
    """Computes FFT frequency spectrum, dominant peak, and spectral entropy."""
    n = len(signal)
    if n < 10:
        return {"dominant_freq_hz": 0.0, "spectral_energy": 0.0, "spectral_entropy": 0.0}

    # Remove DC bias (mean centering)
    centered = signal - np.mean(signal)
    
    # Real FFT
    yf = np.abs(rfft(centered))
    xf = rfftfreq(n, 1.0 / sampling_rate)

    # Exclude near-zero drift frequencies (< 0.5 Hz)
    valid_mask = xf >= 0.5
    valid_xf = xf[valid_mask]
    valid_yf = yf[valid_mask]

    if len(valid_yf) == 0:
        return {"dominant_freq_hz": 0.0, "spectral_energy": 0.0, "spectral_entropy": 0.0, "xf": xf, "yf": yf}

    peak_idx = np.argmax(valid_yf)
    dominant_freq = float(valid_xf[peak_idx])

    # Power spectral density & energy
    psd = valid_yf ** 2
    total_energy = float(np.sum(psd) / n)

    # Spectral entropy (normalized between 0 and 1)
    psd_norm = psd / (np.sum(psd) + 1e-12)
    spectral_entropy = float(-np.sum(psd_norm * np.log2(psd_norm + 1e-12)) / np.log2(len(psd_norm)))

    return {
        "dominant_freq_hz": round(dominant_freq, 3),
        "spectral_energy": round(total_energy, 4),
        "spectral_entropy": round(spectral_entropy, 4),
        "xf": xf,
        "yf": yf,
    }


def compute_zero_crossing_rate(signal: np.ndarray, sampling_rate: float = 50.0) -> float:
    """Computes Zero-Crossing Rate (ZCR) per second."""
    centered = signal - np.mean(signal)
    zero_crossings = np.nonzero(np.diff(centered > 0))[0]
    duration_sec = len(signal) / sampling_rate
    return round(float(len(zero_crossings) / max(duration_sec, 0.001)), 4)


def extract_features(df: pd.DataFrame) -> dict:
    """Extracts BRD Stage 3 edge features across Accelerometer and Gyroscope."""
    accel_z = df["accel_z"].values
    user_accel = np.sqrt(df["user_accel_x"]**2 + df["user_accel_y"]**2 + df["user_accel_z"]**2).values
    gyro_mag = np.sqrt(df["gyro_x"]**2 + df["gyro_y"]**2 + df["gyro_z"]**2).values

    z_rms = float(np.sqrt(np.mean((accel_z - 9.81)**2)))
    motion_rms = float(np.sqrt(np.mean(user_accel**2)))
    gyro_rms = float(np.sqrt(np.mean(gyro_mag**2)))
    zcr = compute_zero_crossing_rate(accel_z)
    fft_results = compute_fft_and_spectral_features(accel_z)

    # Classification heuristic based on Royal Enfield Hunter 350 engine vibration
    # Hunter 350 idle/cruise generates distinct single-cylinder low-RPM harmonics around 7-15 Hz with high Z-axis RMS
    dom_hz = fft_results["dominant_freq_hz"]
    if 6.0 <= dom_hz <= 16.0 and z_rms > 0.25:
        vehicle_hint = "HUNTER_350"
        confidence = 0.85
    elif motion_rms > 1.5 and dom_hz < 3.5:
        vehicle_hint = "WALKING"
        confidence = 0.80
    elif motion_rms < 0.05 and z_rms < 0.05:
        vehicle_hint = "STATIONARY"
        confidence = 0.95
    else:
        vehicle_hint = "IN_VEHICLE"
        confidence = 0.70

    return {
        "dominant_freq_hz": dom_hz,
        "spectral_energy": fft_results["spectral_energy"],
        "spectral_entropy": fft_results["spectral_entropy"],
        "zero_crossing_rate": zcr,
        "z_rms": round(z_rms, 4),
        "motion_rms": round(motion_rms, 4),
        "gyro_rms": round(gyro_rms, 4),
        "vehicle_class_hint": vehicle_hint,
        "classification_confidence": confidence,
        "fft_xf": fft_results["xf"],
        "fft_yf": fft_results["yf"],
    }


# ── 3. Visualizations ────────────────────────────────────────────────────────

def plot_and_save_visualizations(df: pd.DataFrame, features: dict, session_id: str):
    """Generates and saves publication-quality analysis figures."""
    # Figure 1: Raw 50 Hz IMU Multi-Axis Time Series
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    fig.patch.set_facecolor("#0F172A")
    for ax in axes:
        ax.set_facecolor("#1E293B")
        ax.grid(True, color="#334155", linestyle="--", alpha=0.6)
        ax.tick_params(colors="#94A3B8")
        for spine in ax.spines.values():
            spine.set_color("#475569")

    t = df["relative_sec"].values
    # Plot a representative 30-second window for clarity if dataset is large
    mask = (t >= 10.0) & (t <= 40.0) if t[-1] > 40.0 else (t >= 0.0)
    t_win = t[mask]

    axes[0].plot(t_win, df.loc[mask, "accel_x"], label="Accel X", color="#38BDF8", linewidth=1.2)
    axes[0].plot(t_win, df.loc[mask, "accel_y"], label="Accel Y", color="#4ADE80", linewidth=1.2)
    axes[0].plot(t_win, df.loc[mask, "accel_z"], label="Accel Z", color="#FB923C", linewidth=1.2)
    axes[0].set_ylabel("Acceleration (m/s²)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[0].set_title(f"Jarvis 50 Hz IMU Waveform (Session: {session_id})", color="#F8FAFC", fontsize=13, fontweight="bold", pad=10)
    axes[0].legend(facecolor="#1E293B", edgecolor="#475569", labelcolor="#F8FAFC", loc="upper right")

    axes[1].plot(t_win, df.loc[mask, "gyro_x"], label="Gyro Rot X", color="#38BDF8", linewidth=1.2)
    axes[1].plot(t_win, df.loc[mask, "gyro_y"], label="Gyro Rot Y", color="#4ADE80", linewidth=1.2)
    axes[1].plot(t_win, df.loc[mask, "gyro_z"], label="Gyro Rot Z", color="#FB923C", linewidth=1.2)
    axes[1].set_xlabel("Elapsed Time (seconds)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Angular Vel (rad/s)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[1].legend(facecolor="#1E293B", edgecolor="#475569", labelcolor="#F8FAFC", loc="upper right")

    plt.tight_layout()
    fig1_path = FIGURES_DIR / "imu_timeseries.png"
    plt.savefig(fig1_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    print(f"[+] Saved IMU Waveform Figure: {fig1_path}")

    # Figure 2: FFT Power Spectrum & Hunter 350 Engine Vibration Analysis
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#0F172A")
    ax.set_facecolor("#1E293B")
    ax.grid(True, color="#334155", linestyle="--", alpha=0.6)
    ax.tick_params(colors="#94A3B8")
    for spine in ax.spines.values():
        spine.set_color("#475569")

    xf = features["fft_xf"]
    yf = features["fft_yf"]
    # Plot frequencies up to 25 Hz (Nyquist limit for 50 Hz)
    freq_mask = (xf >= 0.5) & (xf <= 25.0)
    ax.plot(xf[freq_mask], yf[freq_mask], color="#38BDF8", linewidth=1.5, label="Z-Axis FFT Magnitude")
    
    dom_hz = features["dominant_freq_hz"]
    ax.axvline(dom_hz, color="#F43F5E", linestyle="--", linewidth=1.8, label=f"Dominant Peak: {dom_hz:.1f} Hz")
    ax.axvspan(6.0, 16.0, color="#10B981", alpha=0.15, label="Hunter 350 Engine Vibration Band (6-16 Hz)")

    ax.set_title(f"Fast Fourier Transform (FFT) Vibration Spectrum - {features['vehicle_class_hint']}", color="#F8FAFC", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Frequency (Hz)", color="#F8FAFC", fontsize=11, fontweight="bold")
    ax.set_ylabel("Spectral Amplitude", color="#F8FAFC", fontsize=11, fontweight="bold")
    ax.legend(facecolor="#1E293B", edgecolor="#475569", labelcolor="#F8FAFC")

    plt.tight_layout()
    fig2_path = FIGURES_DIR / "vibration_fft_spectrum.png"
    plt.savefig(fig2_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    print(f"[+] Saved FFT Vibration Figure: {fig2_path}")

    # Figure 3: GPS Speed & Distance Trajectory
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0F172A")
    for ax in axes:
        ax.set_facecolor("#1E293B")
        ax.grid(True, color="#334155", linestyle="--", alpha=0.6)
        ax.tick_params(colors="#94A3B8")
        for spine in ax.spines.values():
            spine.set_color("#475569")

    axes[0].plot(t, df["speed_kmh"], color="#10B981", linewidth=1.4, label="Speed (km/h)")
    axes[0].set_ylabel("Speed (km/h)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[0].set_title("GPS Kinematics & Journey Velocity Profile", color="#F8FAFC", fontsize=13, fontweight="bold", pad=10)
    axes[0].legend(facecolor="#1E293B", edgecolor="#475569", labelcolor="#F8FAFC")

    axes[1].plot(t, df["accuracy_m"], color="#FBBF24", linewidth=1.2, label="GPS Accuracy (±m)")
    axes[1].set_xlabel("Elapsed Time (seconds)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Accuracy (m)", color="#F8FAFC", fontsize=11, fontweight="bold")
    axes[1].legend(facecolor="#1E293B", edgecolor="#475569", labelcolor="#F8FAFC")

    plt.tight_layout()
    fig3_path = FIGURES_DIR / "gps_trajectory_speed.png"
    plt.savefig(fig3_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    print(f"[+] Saved GPS Trajectory Figure: {fig3_path}")


# ── 4. Tier 1: Cloud Context Reasoner via OpenRouter ─────────────────────────

def run_tier1_context_reasoner(features: dict, df: pd.DataFrame, summary_json: dict | None):
    """Invokes Tier 1 OpenRouter model to resolve physical vehicle state and dwell context."""
    print("\n" + "="*70)
    print(" [TIER 1] INVOKING CLOUD CONTEXT REASONER (OpenRouter)")
    print("="*70)

    # Extract GPS info
    lat = float(df["latitude"].iloc[-1]) if "latitude" in df else 12.8371
    lon = float(df["longitude"].iloc[-1]) if "longitude" in df else 80.2255
    speed = float(df["speed_mps"].mean()) if "speed_mps" in df else 0.0

    reasoner = Tier1Reasoner()

    feature_summary = FeatureSummary(
        dominant_freq_hz=features["dominant_freq_hz"],
        spectral_energy=features["spectral_energy"],
        z_rms=features["z_rms"],
        motion_rms=features["motion_rms"],
        gyro_rms=features["gyro_rms"],
        vehicle_class_hint=features["vehicle_class_hint"],
        classification_confidence=features["classification_confidence"],
    )

    packet = ContextPacket(
        event_id=str(uuid.uuid4()),
        activity="IN_VEHICLE",
        transition="ENTER",
        feature_summary=feature_summary,
        gps=GPSReading(
            latitude=lat,
            longitude=lon,
            speed_mps=speed,
            accuracy_m=float(df["accuracy_m"].iloc[-1]) if "accuracy_m" in df else 10.0,
        ),
    )

    req = Tier1Request(
        event_id=packet.event_id,
        context_packet=packet,
        conflict_reason=(
            f"Edge IMU extracted dominant frequency {features['dominant_freq_hz']} Hz and Z-RMS {features['z_rms']} m/s^2. "
            f"Verify if physical vibration matches Royal Enfield Hunter 350 motorcycle signature."
        ),
    )

    response = reasoner.resolve(req)
    print(f" [+] Resolved Vehicle Class : {response.resolved_vehicle.value}")
    print(f" [+] Recommended State Action: {response.recommended_action.value}")
    print(f" [+] Confidence Score       : {response.confidence * 100:.1f}%")
    print(f" [+] Model Reasoning        : {response.reasoning}")
    return response


# ── 5. Tier 2: Agentic Intent Deduction & Reminders ──────────────────────────

def run_tier2_agentic_orchestrator(tier1_response, store: CRUDStore, registry: FunctionRegistry):
    """Executes natural language commands via Tier 2 OpenRouter model and triggers CRUD automations."""
    print("\n" + "="*70)
    print(" [TIER 2] AGENTIC INTENT DEDUCTION & PERSONAL AUTOMATION (OpenRouter)")
    print("="*70)

    orchestrator = Tier2Orchestrator(function_registry=registry)

    # Real-world test commands grounded in the journey context
    commands = [
        "Remind me to check tire pressure and oil level when I reach the Royal Enfield service garage",
        "Create a high priority task to order new brake pads for Hunter 350 due next Monday",
        "Note down: Odometer reading at start of journey was 4,285 km",
    ]

    for idx, cmd in enumerate(commands, 1):
        print(f"\n--- [Command {idx}]: \"{cmd}\" ---")
        req = Tier2Request(
            user_command=cmd,
            resolved_vehicle=tier1_response.resolved_vehicle.value,
            resolved_place=tier1_response.resolved_place or "Near Garage",
            activity="IN_VEHICLE",
        )

        resp = orchestrator.process_command(req)
        print(f" [+] Jarvis Assistant: {resp.user_response}")
        print(f" [+] Function Calls Emitted: {len(resp.function_calls)}")

        for fc in resp.function_calls:
            print(f"     -> Tool: {fc.function_name} | Args: {fc.arguments}")
            exec_res = registry.execute(fc)
            if exec_res.get("success"):
                record = exec_res.get("record", {})
                print(f"     -> Executed successfully! Stored Record ID: {record.get('id')}")
            else:
                print(f"     -> Execution failed: {exec_res.get('error')}")

    # Display persisted records in the CRUD store
    print("\n" + "-"*70)
    print(" [DATABASE STATE] ACTIVE REMINDERS, TASKS & NOTES")
    print("-"*70)
    reminders = store.list_all(CRUDEntity.REMINDER)
    tasks = store.list_all(CRUDEntity.TASK)
    notes = store.list_all(CRUDEntity.NOTE)

    print(f"\n[Reminders ({len(reminders)})]:")
    for r in reminders:
        print(f"  * {r.get('title')} (Location: {r.get('location_name', 'Anywhere')}) [ID: {r.get('id')[:8]}]")

    print(f"\n[Tasks ({len(tasks)})]:")
    for t in tasks:
        print(f"  * {t.get('title')} (Due: {t.get('due_date', 'None')}, Priority: {t.get('priority', 'Normal')}) [ID: {t.get('id')[:8]}]")

    print(f"\n[Notes ({len(notes)})]:")
    for n in notes:
        print(f"  * {n.get('content', n.get('title'))} [ID: {n.get('id')[:8]}]")


# ── Main Entrypoint ──────────────────────────────────────────────────────────

def main():
    print("="*70)
    print(" JARVIS CONTEXT-AWARE AGENT: TELEMETRY ANALYSIS & REASONING PIPELINE")
    print("="*70)

    # 1. Ingestion
    df, summary_json, session_id = load_telemetry_files()
    print(f"[+] Total Samples: {len(df):,} | Duration: {df['relative_sec'].max():.1f}s (~{df['relative_sec'].max()/60:.1f} min)")

    # 2. Edge Signal Processing
    features = extract_features(df)
    print("\n[+] Extracted BRD Stage 3 Vibration Features:")
    print(f"    - Dominant Frequency: {features['dominant_freq_hz']} Hz")
    print(f"    - Z-Axis RMS        : {features['z_rms']} m/s²")
    print(f"    - Motion RMS        : {features['motion_rms']} m/s²")
    print(f"    - Zero Crossing Rate: {features['zero_crossing_rate']} signs/sec")
    print(f"    - Spectral Entropy  : {features['spectral_entropy']} (0=pure tone, 1=noise)")
    print(f"    - Edge Vehicle Hint : {features['vehicle_class_hint']} ({features['classification_confidence']*100:.0f}%)")

    # 3. Plot & Save Figures
    plot_and_save_visualizations(df, features, session_id)

    # 4. Tier 1 Reasoner via OpenRouter
    tier1_resp = run_tier1_context_reasoner(features, df, summary_json)

    # 5. Tier 2 Intent Deduction via OpenRouter
    store = CRUDStore()
    registry = FunctionRegistry(crud_store=store)
    run_tier2_agentic_orchestrator(tier1_resp, store, registry)

    print("\n" + "="*70)
    print(" [DONE] Pipeline successfully executed all analysis & OpenRouter stages.")
    print("="*70)


if __name__ == "__main__":
    main()
