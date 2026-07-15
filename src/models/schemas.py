"""Pydantic data models for every data structure in the Jarvis pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    ActivityType,
    CRUDEntity,
    CRUDOperation,
    SessionStatus,
    Tier1Action,
    TransitionType,
    VehicleClass,
)


# ── IMU & Sensor Data ───────────────────────────────────────────────────────

class IMUBurst(BaseModel):
    """Raw IMU burst data captured during Stage 2."""
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_sec: float
    sampling_rate_hz: int
    accel_x: list[float] = Field(description="Accelerometer X-axis samples (g)")
    accel_y: list[float] = Field(description="Accelerometer Y-axis samples (g)")
    accel_z: list[float] = Field(description="Accelerometer Z-axis samples (g)")
    gyro_x: list[float] = Field(description="Gyroscope X-axis samples (rad/s)")
    gyro_y: list[float] = Field(description="Gyroscope Y-axis samples (rad/s)")
    gyro_z: list[float] = Field(description="Gyroscope Z-axis samples (rad/s)")

    @property
    def num_samples(self) -> int:
        return len(self.accel_x)


class AxisFeatures(BaseModel):
    """Time-domain features for a single axis."""
    mean: float = 0.0
    median: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    variance: float = 0.0
    std_dev: float = 0.0
    rms: float = 0.0
    peak_to_peak: float = 0.0
    zero_crossing_rate: float = 0.0


class FrequencyFeatures(BaseModel):
    """Frequency-domain features from FFT analysis."""
    dominant_freq_hz: float = 0.0
    secondary_freq_hz: float = 0.0
    spectral_energy: float = 0.0
    spectral_entropy: float = 0.0
    low_band_energy: float = 0.0      # 0-10 Hz
    mid_band_energy: float = 0.0      # 10-25 Hz
    high_band_energy: float = 0.0     # 25-50 Hz (Nyquist at 50Hz sampling / 2)
    harmonic_ratio: float = 0.0
    peak_freq_stability: float = 0.0


class ExtractedFeatures(BaseModel):
    """Complete feature set extracted from an IMU burst (BRD Section 3.1 Stage 3)."""
    timestamp: datetime = Field(default_factory=datetime.now)

    # Time-domain per axis
    accel_x_features: AxisFeatures = Field(default_factory=AxisFeatures)
    accel_y_features: AxisFeatures = Field(default_factory=AxisFeatures)
    accel_z_features: AxisFeatures = Field(default_factory=AxisFeatures)
    gyro_x_features: AxisFeatures = Field(default_factory=AxisFeatures)
    gyro_y_features: AxisFeatures = Field(default_factory=AxisFeatures)
    gyro_z_features: AxisFeatures = Field(default_factory=AxisFeatures)

    # Magnitude statistics
    accel_magnitude_mean: float = 0.0
    accel_magnitude_std: float = 0.0
    gyro_magnitude_mean: float = 0.0
    gyro_magnitude_std: float = 0.0
    signal_magnitude_area: float = 0.0

    # Cross-axis
    accel_xy_correlation: float = 0.0
    accel_xz_correlation: float = 0.0
    accel_yz_correlation: float = 0.0

    # Jerk
    jerk_mean: float = 0.0
    jerk_std: float = 0.0

    # Frequency-domain
    accel_freq: FrequencyFeatures = Field(default_factory=FrequencyFeatures)
    gyro_freq: FrequencyFeatures = Field(default_factory=FrequencyFeatures)
    accel_gyro_freq_correlation: float = 0.0


# ── Classification ───────────────────────────────────────────────────────────

class ClassificationResult(BaseModel):
    """Vehicle classification output from the edge classifier."""
    vehicle_class: VehicleClass = VehicleClass.UNKNOWN
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    uncertainty: float = Field(1.0, ge=0.0, le=1.0)
    feature_distances: dict[str, float] = Field(default_factory=dict)
    is_match: bool = False


# ── GPS & Location ───────────────────────────────────────────────────────────

class GPSReading(BaseModel):
    """GPS location data."""
    latitude: float
    longitude: float
    accuracy_m: float = 10.0
    speed_mps: float = 0.0
    bearing_deg: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)


class POICandidate(BaseModel):
    """Point of Interest candidate near the user."""
    name: str
    category: str
    latitude: float
    longitude: float
    distance_m: float = 0.0
    confidence: float = 0.0


# ── Activity Transition ──────────────────────────────────────────────────────

class ActivityTransition(BaseModel):
    """Android Activity Recognition transition event."""
    activity: ActivityType
    transition: TransitionType
    timestamp: datetime = Field(default_factory=datetime.now)
    confidence_pct: int = Field(100, ge=0, le=100)


# ── Context Packet (BRD Section 3.4) ─────────────────────────────────────────

class ContextPacket(BaseModel):
    """Compact context packet transmitted to backend."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    activity_transition: ActivityTransition | None = None
    gps: GPSReading | None = None
    features: ExtractedFeatures | None = None
    classification: ClassificationResult | None = None
    nearby_pois: list[POICandidate] = Field(default_factory=list)
    session_id: str | None = None
    is_offline_queued: bool = False


# ── Session State (BRD Section 3.2) ──────────────────────────────────────────

class SessionState(BaseModel):
    """Journey session maintained by the state machine."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: SessionStatus = SessionStatus.CREATED
    vehicle_class: VehicleClass = VehicleClass.UNKNOWN
    started_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    parking_gps: GPSReading | None = None
    events: list[str] = Field(default_factory=list, description="Event IDs in this session")
    poi_visits: list[POICandidate] = Field(default_factory=list)
    classification_confidence: float = 0.0
    resume_count: int = 0


# ── Tier 1: Context Resolution ───────────────────────────────────────────────

class Tier1Request(BaseModel):
    """Input to Tier 1 reasoner when deterministic resolution fails."""
    event_id: str
    context_packet: ContextPacket
    session: SessionState | None = None
    conflict_reason: str = ""
    classification_confidence: float = 0.0
    gps_accuracy_m: float = 0.0


class Tier1Response(BaseModel):
    """Structured output from Tier 1 reasoner."""
    resolved_vehicle: VehicleClass = VehicleClass.UNKNOWN
    resolved_place: str = ""
    place_category: str = ""
    recommended_action: Tier1Action = Tier1Action.ACCEPT
    confidence: float = 0.0
    uncertainty: float = 1.0
    reasoning: str = ""
    model_id: str = "mock"
    tokens_used: int = 0
    latency_ms: float = 0.0


# ── Tier 2: Agentic Orchestration ────────────────────────────────────────────

class FunctionCall(BaseModel):
    """Allow-listed function call emitted by Tier 2."""
    function_name: str
    entity: CRUDEntity
    operation: CRUDOperation
    arguments: dict[str, Any] = Field(default_factory=dict)
    is_valid: bool = False
    validation_error: str | None = None


class Tier2Request(BaseModel):
    """Input to Tier 2 orchestrator for user command processing."""
    user_command: str
    context_packet: ContextPacket
    session: SessionState | None = None
    tier1_response: Tier1Response | None = None
    resolved_place: str = ""
    resolved_place_category: str = ""


class Tier2Response(BaseModel):
    """Output from Tier 2 orchestrator."""
    user_response: str = ""
    function_calls: list[FunctionCall] = Field(default_factory=list)
    reasoning: str = ""
    model_id: str = "mock"
    tokens_used: int = 0
    latency_ms: float = 0.0
    all_calls_valid: bool = False


# ── Audit Log (FR-13) ────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    """Structured audit log entry for every decision."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    event_id: str = ""
    component: str = ""          # "classifier", "session_manager", "tier1", "tier2", "function_registry"
    action: str = ""             # What happened
    input_ref: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    model_id: str | None = None
    execution_result: str = ""   # "success", "rejected", "error"
    error_detail: str | None = None


# ── Pipeline Result ──────────────────────────────────────────────────────────

class PipelineResult(BaseModel):
    """Complete result from one pass through the end-to-end pipeline."""
    event_id: str = ""
    context_packet: ContextPacket | None = None
    classification: ClassificationResult | None = None
    session: SessionState | None = None
    tier1_invoked: bool = False
    tier1_response: Tier1Response | None = None
    tier2_invoked: bool = False
    tier2_response: Tier2Response | None = None
    audit_entries: list[AuditEntry] = Field(default_factory=list)
    total_latency_ms: float = 0.0


# ── Evaluation ───────────────────────────────────────────────────────────────

class ScenarioExpectation(BaseModel):
    """Expected outcomes for an evaluation scenario."""
    expected_vehicle: VehicleClass | None = None
    expected_is_match: bool | None = None
    expected_session_status: SessionStatus | None = None
    expected_tier1_invoked: bool | None = None
    expected_tier2_invoked: bool | None = None
    expected_function_valid: bool | None = None
    expected_crud_entity: CRUDEntity | None = None
    min_confidence: float | None = None


class ScenarioResult(BaseModel):
    """Result of running one evaluation scenario."""
    scenario_id: int
    scenario_name: str
    passed: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    details: dict[str, str] = Field(default_factory=dict)
    pipeline_result: PipelineResult | None = None
