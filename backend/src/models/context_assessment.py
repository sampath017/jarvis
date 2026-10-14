"""Validated output contract for an independent background agent invocation."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import ContextAssessmentAction, VehicleClass


class ContextAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    resolved_vehicle: VehicleClass = VehicleClass.UNKNOWN
    resolved_place: str = ""
    place_category: str = ""
    recommended_action: ContextAssessmentAction = ContextAssessmentAction.REJECT
    confidence: float = Field(default=0.0, ge=0, le=1)
    uncertainty: float = Field(default=1.0, ge=0, le=1)
    reasoning: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recommended_action")
    @classmethod
    def assessment_actions_only(cls, action):
        if action not in {ContextAssessmentAction.ACCEPT, ContextAssessmentAction.REJECT}:
            raise ValueError("Session lifecycle actions belong to deterministic reducers")
        return action
