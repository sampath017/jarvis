"""
Tier 1: Intermediate Context Reasoner

Resolves ambiguous physical context when deterministic systems cannot
produce a confident result.

Uses LangChain ChatOpenAI with native structured output (.with_structured_output)
via OpenRouter for LangGraph workflow execution, LangSmith tracing, and schema guarantees.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

from ..models.enums import Tier1Action, VehicleClass
from ..models.schemas import Tier1Request, Tier1Response
from ..settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER1,
    OPENROUTER_TEMPERATURE,
)

logger = logging.getLogger(__name__)


class Tier1StructuredOutput(BaseModel):
    """Schema for Tier 1 structured output."""

    resolved_vehicle: VehicleClass = Field(
        default=VehicleClass.UNKNOWN,
        description="The resolved vehicle class: HUNTER_350, CAR, BUS, OTHER_MOTORCYCLE, UNKNOWN, NOT_VEHICLE",
    )
    resolved_place: str = Field(
        default="",
        description="Name of the resolved place or POI, or empty string",
    )
    place_category: str = Field(
        default="",
        description="Category of the resolved place, or empty string",
    )
    recommended_action: Tier1Action = Field(
        default=Tier1Action.ACCEPT,
        description="Recommended action: ACCEPT, PAUSE, RESUME, COMPLETE, RECLASSIFY, REJECT",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    uncertainty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Uncertainty score between 0.0 and 1.0",
    )
    reasoning: str = Field(
        default="",
        description="Brief reasoning behind the context resolution",
    )

    @field_validator("resolved_vehicle", mode="before")
    @classmethod
    def normalize_vehicle(cls, v: Any) -> VehicleClass:
        """Coerce strings to VehicleClass enum, case-insensitively."""
        if isinstance(v, VehicleClass):
            return v
        if isinstance(v, str):
            normalized = v.strip().upper()
            try:
                return VehicleClass(normalized)
            except ValueError:
                return VehicleClass.UNKNOWN
        return VehicleClass.UNKNOWN

    @field_validator("recommended_action", mode="before")
    @classmethod
    def normalize_action(cls, v: Any) -> Tier1Action:
        """Coerce strings to Tier1Action enum, case-insensitively."""
        if isinstance(v, Tier1Action):
            return v
        if isinstance(v, str):
            normalized = v.strip().upper()
            try:
                return Tier1Action(normalized)
            except ValueError:
                return Tier1Action.ACCEPT
        return Tier1Action.ACCEPT

    @field_validator("confidence", "uncertainty", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> float:
        """Clamp confidence and uncertainty floats to [0.0, 1.0]."""
        try:
            val = float(v)
            return max(0.0, min(1.0, val))
        except (TypeError, ValueError):
            return 0.5


class Tier1Reasoner:
    """
    Tier 1 Context Reasoner.

    Uses LangChain ChatOpenAI via OpenRouter with native structured outputs (.with_structured_output).
    All invocations are automatically traced by LangSmith when enabled.
    """

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=OPENROUTER_MODEL_TIER1,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            max_tokens=OPENROUTER_MAX_TOKENS,
            temperature=OPENROUTER_TEMPERATURE,
            max_retries=3,
            request_timeout=25.0,
            extra_body={
                "provider": {
                    "only": ["DeepInfra", "Together", "Fireworks"],
                    "ignore": ["Novita"],
                    "allow_fallbacks": True,
                },
            },
        )
        self.structured_llm = self.llm.with_structured_output(Tier1StructuredOutput)

    def resolve(self, request: Tier1Request) -> Tier1Response:
        """Resolve ambiguous context using LLM with structured output."""
        start = time.perf_counter()
        prompt = self._build_prompt(request)

        logger.info(
            "Tier 1 invocation started",
            extra={
                "tier": "tier1",
                "phase": "request",
                "event_id": request.event_id,
                "conflict_reason": request.conflict_reason,
                "prompt": prompt,
                "model": OPENROUTER_MODEL_TIER1,
            },
        )

        try:
            messages = [
                SystemMessage(content=self._system_prompt()),
                HumanMessage(content=prompt),
            ]

            parsed_raw = self.structured_llm.invoke(messages)
            if isinstance(parsed_raw, Tier1StructuredOutput):
                parsed = parsed_raw
            elif isinstance(parsed_raw, dict):
                parsed = Tier1StructuredOutput.model_validate(parsed_raw)
            else:
                parsed = Tier1StructuredOutput.model_validate(getattr(parsed_raw, "__dict__", {}))

            elapsed_ms = (time.perf_counter() - start) * 1000

            result = Tier1Response(
                resolved_vehicle=parsed.resolved_vehicle,
                resolved_place=parsed.resolved_place,
                place_category=parsed.place_category,
                recommended_action=parsed.recommended_action,
                confidence=parsed.confidence,
                uncertainty=parsed.uncertainty,
                reasoning=parsed.reasoning,
                model_id=OPENROUTER_MODEL_TIER1,
                tokens_used=0,
                latency_ms=round(elapsed_ms, 2),
            )

            logger.info(
                "Tier 1 invocation completed",
                extra={
                    "tier": "tier1",
                    "phase": "llm_response",
                    "event_id": request.event_id,
                    "resolved_vehicle": result.resolved_vehicle.value,
                    "recommended_action": result.recommended_action.value,
                    "confidence": result.confidence,
                    "latency_ms": round(elapsed_ms, 2),
                    "model": OPENROUTER_MODEL_TIER1,
                },
            )

            return result

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.critical(
                "Tier 1 invocation failed: %s (%s)",
                e,
                type(e).__name__,
                exc_info=True,
                extra={
                    "tier": "tier1",
                    "phase": "error",
                    "event_id": request.event_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            return Tier1Response(
                reasoning=f"Tier 1 failed: {e}",
                model_id=OPENROUTER_MODEL_TIER1,
                latency_ms=round(elapsed_ms, 2),
            )

    def _system_prompt(self) -> str:
        return """You are Jarvis Tier 1 Context Reasoner. Your job is to resolve ambiguous physical context.

You receive a context packet with sensor data, GPS, activity transitions, and classification results.
You must return structured data resolving the vehicle class, place, action, and confidence.

Schema:
- resolved_vehicle: HUNTER_350, CAR, BUS, OTHER_MOTORCYCLE, UNKNOWN, NOT_VEHICLE
- resolved_place: Name of the resolved place or POI, or empty string
- place_category: Category of the resolved place, or empty string
- recommended_action: ACCEPT, PAUSE, RESUME, COMPLETE, RECLASSIFY, REJECT
- confidence: float between 0.0 and 1.0
- uncertainty: float between 0.0 and 1.0
- reasoning: brief explanation of context resolution

Rules:
- confidence + uncertainty should roughly sum to 1.0.
- Be conservative: prefer PAUSE over COMPLETE when unsure.
- Never fabricate POI names — use only provided candidates.
"""

    def _build_prompt(self, request: Tier1Request) -> str:
        packet = request.context_packet
        sections = [f"Conflict: {request.conflict_reason}"]

        if packet.activity:
            sections.append(
                f"Activity: {packet.activity} "
                f"(transition: {packet.transition})"
            )
        if packet.feature_summary:
            sections.append(
                f"Classification: {packet.feature_summary.vehicle_class_hint} "
                f"(confidence: {packet.feature_summary.classification_confidence:.2f})"
            )
        if packet.gps:
            sections.append(
                f"GPS: lat={packet.gps.latitude:.4f}, lon={packet.gps.longitude:.4f}, "
                f"accuracy={packet.gps.accuracy_m:.1f}m, speed={packet.gps.speed_mps:.1f}m/s"
            )
        if packet.nearby_pois:
            poi_strs = [f"{p.name} ({p.category}, {p.distance_m:.0f}m, conf={p.confidence:.2f})"
                        for p in packet.nearby_pois]
            sections.append(f"Nearby POIs: {', '.join(poi_strs)}")
        if request.session:
            sections.append(
                f"Session: {request.session.status.value}, "
                f"vehicle: {request.session.vehicle_class.value}"
            )

        return "\n".join(sections)
