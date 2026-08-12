"""Data models and contract DTO representations for simulation events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class VibrationProfile:
    """Parameters used to synthesize a 10-second IMU burst."""

    dominant_hz: float
    vertical_amplitude: float
    lateral_amplitude: float
    gyro_amplitude: float
    noise: float


VIBRATION_PROFILES: dict[str, VibrationProfile] = {
    "HUNTER_350": VibrationProfile(8.0, 2.1, 0.8, 0.9, 0.12),
    "OTHER_MOTORCYCLE": VibrationProfile(7.0, 1.6, 0.7, 0.7, 0.12),
    "CAR": VibrationProfile(2.3, 0.45, 0.25, 0.18, 0.05),
    "BUS": VibrationProfile(3.1, 0.8, 0.4, 0.28, 0.08),
    "NOT_VEHICLE": VibrationProfile(1.8, 0.16, 0.12, 0.06, 0.03),
}


@dataclass(frozen=True)
class ActivityEvent:
    """One context event in a virtual scenario timeline."""

    offset: timedelta
    activity: str
    latitude: float
    longitude: float
    speed_mps: float
    accuracy_m: float = 8.0
    bearing_deg: float = 0.0
    transition: str = "ENTER"
    vehicle_class_hint: str | None = None
    classification_confidence: float = 0.0
    note: str = ""

    def to_payload(self, occurred_at: datetime, sequence: int) -> dict[str, Any]:
        """Convert an event into the exact POST /context-events request shape."""
        from src.features import extract_feature_summary, iso8601

        payload: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "occurred_at": iso8601(occurred_at + self.offset),
            "activity": self.activity,
            "transition": self.transition,
            "location": {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "accuracy_m": self.accuracy_m,
                "speed_mps": self.speed_mps,
                "bearing_deg": self.bearing_deg,
                "timestamp": iso8601(occurred_at + self.offset),
            },
        }
        if self.vehicle_class_hint:
            payload["feature_summary"] = extract_feature_summary(
                vehicle_class_hint=self.vehicle_class_hint,
                classification_confidence=self.classification_confidence,
                seed=sequence,
            )
        return payload


@dataclass(frozen=True)
class ChatTurn:
    """A natural language user message sent through POST /commands."""

    text: str
    note: str


@dataclass(frozen=True)
class HttpResult:
    """A response from the Jarvis API or a transport-level failure."""

    status_code: int | None
    body: dict[str, Any] | str
    error: str | None = None

    @property
    def successful(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300
