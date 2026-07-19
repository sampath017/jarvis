"""Pydantic data models for the Jarvis Cloud Run API.

Covers:
- API request / response schemas
- LLM tier request / response schemas
- Session state
- Firestore document models
- Audit records
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .enums import (
    CRUDEntity,
    CRUDOperation,
    SessionStatus,
    Tier1Action,
    VehicleClass,
)


# ── API Request / Response ───────────────────────────────────────────────────

class LocationSnapshot(BaseModel):
    """Compact location snapshot included in context events."""
    latitude: float
    longitude: float
    accuracy_m: float = Field(ge=0.0)
    speed_mps: float | None = None
    bearing_deg: float | None = None
    altitude_m: float | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FeatureSummary(BaseModel):
    """Compact feature vector summary sent from the edge device."""
    dominant_freq_hz: float = 0.0
    spectral_energy: float = 0.0
    z_rms: float = 0.0
    harmonic_ratio: float = 0.0
    accel_magnitude_mean: float = 0.0
    motion_rms: float = 0.0
    gyro_rms: float = 0.0
    vehicle_class_hint: str = ""
    classification_confidence: float = 0.0


class ContextEventRequest(BaseModel):
    """POST /v1/context-events request body."""
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Client-generated UUID for idempotency",
    )
    occurred_at: datetime = Field(
        description="UTC timestamp when the event occurred on device",
    )
    activity: str = Field(
        description="Activity type: STILL, WALKING, IN_VEHICLE, etc.",
    )
    transition: str = Field(
        default="ENTER",
        description="Transition type: ENTER or EXIT",
    )
    feature_summary: FeatureSummary | None = Field(
        default=None,
        description="Compact feature vector from edge IMU processing",
    )
    location: LocationSnapshot | None = Field(
        default=None,
        description="Location snapshot, included only when relevant",
    )
    session_hint: str | None = Field(
        default=None,
        description="Client-side session ID hint for continuity",
    )


class CommandRequest(BaseModel):
    """POST /v1/commands request body."""
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Client-generated UUID for idempotency",
    )
    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Chat thread ID for conversation grouping",
    )
    text: str = Field(
        min_length=1,
        max_length=2000,
        description="User's text command",
    )
    current_context_ref: str | None = Field(
        default=None,
        description="Reference to latest context event for grounding",
    )


class APIResponse(BaseModel):
    """Standard API response envelope."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "ok"
    message: str = ""
    changed_records: list[str] = Field(default_factory=list)
    session_id: str | None = None
    error: str | None = None


# ── GPS / POI ────────────────────────────────────────────────────────────────

class GPSReading(BaseModel):
    """GPS location data."""
    latitude: float
    longitude: float
    accuracy_m: float = 10.0
    speed_mps: float = 0.0
    bearing_deg: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class POICandidate(BaseModel):
    """Point of Interest candidate near the user."""
    name: str
    category: str
    place_id: str | None = None
    latitude: float
    longitude: float
    distance_m: float = 0.0
    confidence: float = 0.0


# ── Session State ────────────────────────────────────────────────────────────

class SessionState(BaseModel):
    """Journey session maintained by the deterministic state machine."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: SessionStatus = SessionStatus.CREATED
    vehicle_class: VehicleClass = VehicleClass.UNKNOWN
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    parking_gps: GPSReading | None = None
    events: list[str] = Field(default_factory=list, description="Event IDs in this session")
    poi_visits: list[POICandidate] = Field(default_factory=list)
    classification_confidence: float = 0.0
    resume_count: int = 0


# ── Context Packet ───────────────────────────────────────────────────────────

class ContextPacket(BaseModel):
    """Normalised context packet assembled from the incoming event."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    activity: str = ""
    transition: str = "ENTER"
    gps: GPSReading | None = None
    feature_summary: FeatureSummary | None = None
    nearby_pois: list[POICandidate] = Field(default_factory=list)
    session_id: str | None = None
    classification_confidence: float = 0.0
    vehicle_class_hint: str = ""

    @model_validator(mode="after")
    def inherit_feature_classification(self) -> "ContextPacket":
        """Keep feature evidence and packet-level routing fields in sync."""
        if self.feature_summary:
            if not self.vehicle_class_hint:
                self.vehicle_class_hint = self.feature_summary.vehicle_class_hint
            if self.classification_confidence == 0.0:
                self.classification_confidence = self.feature_summary.classification_confidence
        return self


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
    thread_id: str = ""
    context_packet: ContextPacket | None = None
    session: SessionState | None = None
    tier1_response: Tier1Response | None = None
    resolved_place: str = ""
    resolved_place_category: str = ""
    resolved_address: str | None = None
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    user_tasks: list[dict[str, Any]] = Field(default_factory=list)


class Tier2Response(BaseModel):
    """Output from Tier 2 orchestrator."""
    user_response: str = ""
    function_calls: list[FunctionCall] = Field(default_factory=list)
    reasoning: str = ""
    model_id: str = "mock"
    tokens_used: int = 0
    latency_ms: float = 0.0
    all_calls_valid: bool = False


# ── Audit Log ────────────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    """Structured audit log entry for every decision."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_id: str = ""
    component: str = ""
    action: str = ""
    input_ref: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    model_id: str | None = None
    execution_result: str = ""
    error_detail: str | None = None


# ── Firestore Document Models ────────────────────────────────────────────────

class UserProfile(BaseModel):
    """users/{uid}/profile document."""
    uid: str
    timezone: str = "UTC"
    consent_given: bool = False
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserPreference(BaseModel):
    """users/{uid}/preferences/{preferenceId} document."""
    preference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    value: Any
    source: str = "user"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PlaceRecord(BaseModel):
    """users/{uid}/places/{placeId} document."""
    place_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    google_place_id: str | None = None
    name: str
    user_label: str | None = None
    category: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(BaseModel):
    """users/{uid}/chatThreads/{threadId}/messages/{messageId} document."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "user"
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    run_id: str | None = None


class AgentRunRecord(BaseModel):
    """users/{uid}/agentRuns/{runId} document."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_type: str = ""
    event_id: str | None = None
    thread_id: str | None = None
    model_tier1: str | None = None
    model_tier2: str | None = None
    tier1_tokens: int = 0
    tier2_tokens: int = 0
    tier1_latency_ms: float = 0.0
    tier2_latency_ms: float = 0.0
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
