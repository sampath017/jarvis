"""Bounded telemetry for comparing detectors, separate from activity evidence."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TelemetryTiming(BaseModel):
    boot_count: int = Field(ge=-1)
    observed_elapsed_ms: int = Field(ge=0)
    received_elapsed_ms: int = Field(ge=0)
    delivery_delay_ms: int | None = Field(default=None, ge=0)
    upload_elapsed_ms: int | None = Field(default=None, ge=0)
    upload_delay_ms: int | None = Field(default=None, ge=0)


class MotionFeatures(BaseModel):
    accel_magnitude_std: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    samples: int | None = Field(default=None, ge=0)
    span_ms: int | None = Field(default=None, ge=0)
    max_gap_ms: int | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    usable: bool | None = None
    requested_hz: int | None = Field(default=None, ge=1, le=100)
    gyro_rms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    accepted_activity: str | None = Field(default=None, max_length=32)
    event_type: str | None = Field(default=None, max_length=64)
    confidence: int | None = Field(default=None, ge=0, le=100)


class MotionDiagnostic(TelemetryTiming):
    id: str = Field(pattern=r"^(motion_|evt_)[a-zA-Z0-9-]{1,80}$")
    timestamp: datetime
    source: Literal['local_motion', 'google_activity', 'user_label']
    candidate: Literal['UNKNOWN', 'STILL', 'ON_FOOT', 'WALKING', 'RUNNING', 'IN_VEHICLE', 'ON_BICYCLE']
    provisional: Literal[True] = True
    model_version: str = Field(max_length=64)
    features: MotionFeatures = Field(default_factory=MotionFeatures)
    label_end_at: datetime | None = None
    placement: Literal['pocket', 'hand', 'bag', 'mounted', 'table', 'other'] | None = None

    @field_validator('timestamp')
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError('Include a timezone offset')
        return value

    @model_validator(mode='after')
    def label_window(self):
        if self.source == 'user_label':
            if self.label_end_at is None or self.label_end_at.tzinfo is None:
                raise ValueError('Labels require a timezone-aware end')
            if not 0 < (self.label_end_at-self.timestamp).total_seconds() <= 7200:
                raise ValueError('Label between 1 second and two hours')
        return self


class MotionDiagnosticBatch(BaseModel):
    records: list[MotionDiagnostic] = Field(min_length=1, max_length=48)
