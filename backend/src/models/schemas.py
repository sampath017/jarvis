"""Pydantic data models for the Jarvis API and local execution engine.

Covers:
- API request / response schemas
- Unified GPS / Location schemas
- Session state & context packets
- LLM tier request / response schemas
- Audit records & Database models
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .enums import (
    CRUDEntity,
    CRUDOperation,
    SessionStatus,
    Tier1Action,
    VehicleClass,
)


# ── GPS / Location Data ──────────────────────────────────────────────────────
class GPSReading(BaseModel):
    """Unified GPS location schema used across API requests, backend state, and persistence."""
    latitude: float
    longitude: float
    accuracy_m: float = Field(default=10.0, ge=0.0)
    speed_mps: float = 0.0
    bearing_deg: float = 0.0
    altitude_m: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    """POST /context-events request body."""
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Client-generated UUID for idempotency",
    )
    event_type: str = Field(
        default="ACTIVITY_TRANSITION",
        description="Type of context event: BOUNDED_IMU_BURST, ACTIVITY_ENTER, TELEMETRY_PIPELINE_CHECK, etc.",
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the event occurred on device",
    )
    activity: str = Field(
        default="UNKNOWN",
        description="Activity type: STILL, WALKING, IN_VEHICLE, etc.",
    )
    transition: str = Field(
        default="ENTER",
        description="Transition type: ENTER or EXIT",
    )
    feature_summary: Any | None = Field(
        default=None,
        description="Compact feature vector from edge IMU processing",
    )
    location: GPSReading | None = Field(
        default=None,
        description="GPS location reading, included only when relevant",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID for riding/movement sessions",
    )
    session_hint: str | None = Field(
        default=None,
        description="Client-side session ID hint for continuity",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Fallback timestamp -> occurred_at
            if "occurred_at" not in data and "timestamp" in data:
                data["occurred_at"] = data["timestamp"]
            # Fallback journey_gps -> location
            if "location" not in data and "journey_gps" in data and isinstance(data["journey_gps"], dict):
                jg = data["journey_gps"]
                lat = jg.get("current_latitude") or (jg.get("end_location") or {}).get("latitude")
                lon = jg.get("current_longitude") or (jg.get("end_location") or {}).get("longitude")
                if lat is not None and lon is not None:
                    data["location"] = {"latitude": float(lat), "longitude": float(lon)}
            # Fallback activity from transitionState / transition
            if "activity" not in data or not data["activity"]:
                trans = str(data.get("transition", "")).upper()
                for act in ("IN_VEHICLE", "WALKING", "ON_BICYCLE", "RUNNING", "STILL"):
                    if act in trans:
                        data["activity"] = act
                        break
                if "activity" not in data or not data["activity"]:
                    data["activity"] = "UNKNOWN"
        return data


class CommandRequest(BaseModel):
    """POST /commands request body."""
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
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent conversation history turns for multi-turn grounding",
    )
    current_context_ref: str | None = Field(
        default=None,
        description="Reference to latest context event for grounding",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Live client GPS latitude coordinate",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Live client GPS longitude coordinate",
    )


class StructuredAgentResponse(BaseModel):
    """Structured response schema for Jarvis agent interactions."""

    message: str = Field(
        ...,
        description=(
            "Clean, direct, natural human response to the user. "
            "Plain text without raw markdown asterisks (e.g. do not use **bold** or *italic* markdown syntax), "
            "no unrendered symbols, and no raw numerical GPS coordinates. "
            "Complete, well-formed sentence(s)."
        ),
    )
    intent: str = Field(
        default="general",
        description=(
            "Recognized user intent: 'location_query', 'create_reminder', 'delete_reminder', "
            "'list_reminders', 'create_note', 'list_notes', 'save_place', 'list_places', 'greeting', 'general'"
        ),
    )
    resolved_place: str | None = Field(
        default=None,
        description=(
            "Specific human-readable place or landmark name if location was asked or referenced "
            "(e.g. 'Creations Valencia', 'Siri Campus TCS', 'Navalur')."
        ),
    )


class APIResponse(BaseModel):
    """Standard API response envelope."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "ok"
    message: str = ""
    changed_records: list[str] = Field(default_factory=list)
    session_id: str | None = None
    error: str | None = None
    intent: str | None = None
    resolved_place: str | None = None


# -- Location-aware personal automation -------------------------------------

class NoteCreateRequest(BaseModel):
    """Create a user-owned local note through the direct mobile API."""

    title: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=10_000)


class NotePatchRequest(BaseModel):
    """Partial update for a user-owned local note."""

    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=10_000)


class ReminderCreateRequest(BaseModel):
    """Create a time, location, or activity-triggered reminder."""

    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=10_000)
    due_at: datetime | None = None
    location_name: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float = Field(default=100.0, ge=1, le=100_000)
    activity: str | None = Field(default=None, max_length=64)
    status: Literal["ACTIVE", "PAUSED", "COMPLETED"] = "ACTIVE"
    one_shot: bool = True

    @model_validator(mode="after")
    def requires_a_trigger(self) -> "ReminderCreateRequest":
        has_location = self.latitude is not None or self.longitude is not None
        if has_location and (self.latitude is None or self.longitude is None):
            raise ValueError("location reminders require both latitude and longitude")
        if not (self.due_at or self.activity or (self.latitude is not None and self.longitude is not None)):
            raise ValueError("a reminder needs due_at, activity, or a location")
        return self


class ReminderPatchRequest(BaseModel):
    """Partial update for an existing reminder."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=10_000)
    due_at: datetime | None = None
    location_name: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float | None = Field(default=None, ge=1, le=100_000)
    activity: str | None = Field(default=None, max_length=64)
    status: Literal["ACTIVE", "PAUSED", "COMPLETED"] | None = None
    one_shot: bool | None = None


class ContextRuleCreateRequest(BaseModel):
    """Create a deterministic rule evaluated only against persisted context."""

    name: str = Field(min_length=1, max_length=500)
    trigger_type: Literal["GEOFENCE_ENTER", "ACTIVITY_ENTER", "TIME_AFTER"]
    trigger: dict[str, Any] = Field(default_factory=dict)
    action_type: Literal["NOTIFY", "APPEND_NOTE", "UPDATE_REMINDER"]
    action: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    one_shot: bool = False

    @model_validator(mode="after")
    def validates_rule_shape(self) -> "ContextRuleCreateRequest":
        if self.trigger_type == "GEOFENCE_ENTER" and (
            self.trigger.get("latitude") is None or self.trigger.get("longitude") is None
        ):
            raise ValueError("GEOFENCE_ENTER requires trigger.latitude and trigger.longitude")
        if self.trigger_type == "ACTIVITY_ENTER" and not self.trigger.get("activity"):
            raise ValueError("ACTIVITY_ENTER requires trigger.activity")
        if self.trigger_type == "TIME_AFTER" and not self.trigger.get("at"):
            raise ValueError("TIME_AFTER requires trigger.at")
        if self.action_type == "APPEND_NOTE" and not (
            self.action.get("note_id") or self.action.get("note_title")
        ):
            raise ValueError("APPEND_NOTE requires action.note_id or action.note_title")
        if self.action_type == "UPDATE_REMINDER" and not (
            self.action.get("reminder_id") or self.action.get("reminder_title")
        ):
            raise ValueError("UPDATE_REMINDER requires action.reminder_id or action.reminder_title")
        return self


class ContextRulePatchRequest(BaseModel):
    """Partial update for a deterministic context rule."""

    name: str | None = Field(default=None, min_length=1, max_length=500)
    trigger_type: Literal["GEOFENCE_ENTER", "ACTIVITY_ENTER", "TIME_AFTER"] | None = None
    trigger: dict[str, Any] | None = None
    action_type: Literal["NOTIFY", "APPEND_NOTE", "UPDATE_REMINDER"] | None = None
    action: dict[str, Any] | None = None
    enabled: bool | None = None
    one_shot: bool | None = None


# ── POI Candidate ────────────────────────────────────────────────────────────


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
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    parking_gps: GPSReading | None = None
    events: list[str] = Field(default_factory=list,
                              description="Event IDs in this session")
    poi_visits: list[POICandidate] = Field(default_factory=list)
    classification_confidence: float = 0.0
    resume_count: int = 0


# ── Context Packet ───────────────────────────────────────────────────────────

class ContextPacket(BaseModel):
    """Normalised context packet assembled from the incoming event."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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
    user_reminders: list[dict[str, Any]] = Field(default_factory=list)
    user_notes: list[dict[str, Any]] = Field(default_factory=list)


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
    """Structured audit log entry for every decision across all graph nodes."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uid: str = ""
    run_id: str = ""
    event_id: str = ""
    node_name: str = ""
    action: str = ""
    category: str = "SYSTEM"  # API, LLM, CRUD, SESSION, CONTEXT, SYSTEM
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    gps_lat: float | None = None
    gps_lon: float | None = None
    model_id: str | None = None
    confidence: float | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    execution_result: str = "success"
    error_detail: str | None = None


# ── Local Database Record Models ─────────────────────────────────────────────

class UserProfile(BaseModel):
    """Local user profile record."""
    uid: str
    timezone: str = "UTC"
    consent_given: bool = False
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserPreference(BaseModel):
    """Local user preference record."""
    preference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    value: Any
    source: str = "user"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlaceRecord(BaseModel):
    """Local place record."""
    place_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    google_place_id: str | None = None
    name: str
    user_label: str | None = None
    category: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatMessage(BaseModel):
    """Local chat message record."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "user"
    content: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str | None = None
