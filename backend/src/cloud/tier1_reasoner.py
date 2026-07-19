"""
Tier 1: Intermediate Context Reasoner

Resolves ambiguous physical context when deterministic systems cannot
produce a confident result.

Returns schema-validated JSON — never unrestricted prose.

Uses LangChain ChatOpenAI (via OpenRouter) for automatic LangSmith tracing
and structured Cloud Run logging.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER1,
    OPENROUTER_TEMPERATURE,
)
from ..models.enums import Tier1Action, VehicleClass
from ..models.schemas import Tier1Request, Tier1Response

logger = logging.getLogger(__name__)


class Tier1Reasoner:
    """
    Tier 1 Context Reasoner.

    Uses LangChain ChatOpenAI via OpenRouter for structured context resolution.
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

    def resolve(self, request: Tier1Request) -> Tier1Response:
        """Resolve ambiguous context using LLM via OpenRouter API."""
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

            response = self.llm.invoke(messages)
            content = response.content
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Extract token usage from response metadata
            usage = response.usage_metadata or {}
            tokens = usage.get("total_tokens", 0)

            parsed = json.loads(content)

            result = Tier1Response(
                resolved_vehicle=VehicleClass(
                    parsed.get("resolved_vehicle", "UNKNOWN")),
                resolved_place=parsed.get("resolved_place", ""),
                place_category=parsed.get("place_category", ""),
                recommended_action=Tier1Action(
                    parsed.get("recommended_action", "ACCEPT")),
                confidence=parsed.get("confidence", 0.5),
                uncertainty=parsed.get("uncertainty", 0.5),
                reasoning=parsed.get("reasoning", ""),
                model_id=OPENROUTER_MODEL_TIER1,
                tokens_used=tokens,
                latency_ms=round(elapsed_ms, 2),
            )

            logger.info(
                "Tier 1 invocation completed",
                extra={
                    "tier": "tier1",
                    "phase": "llm_response",
                    "event_id": request.event_id,
                    "raw_content": content,
                    "resolved_vehicle": result.resolved_vehicle.value,
                    "recommended_action": result.recommended_action.value,
                    "confidence": result.confidence,
                    "tokens_used": tokens,
                    "latency_ms": round(elapsed_ms, 2),
                    "model": OPENROUTER_MODEL_TIER1,
                },
            )

            return result

        except json.JSONDecodeError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Tier 1 JSON parse error",
                extra={
                    "tier": "tier1",
                    "phase": "error",
                    "event_id": request.event_id,
                    "error": str(e),
                    "raw_content": content if "content" in dir() else "N/A",
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            return Tier1Response(
                reasoning=f"Tier 1 failed to parse LLM response as JSON: {e}",
                model_id=OPENROUTER_MODEL_TIER1,
                latency_ms=round(elapsed_ms, 2),
            )

            logger.error(
                "Tier 1 invocation failed: %s (%s)",
                e,
                type(e).__name__,
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
You must return a JSON object with these exact fields:
{
  "resolved_vehicle": "HUNTER_350" | "CAR" | "BUS" | "OTHER_MOTORCYCLE" | "UNKNOWN" | "NOT_VEHICLE",
  "resolved_place": "string — name of the resolved place or empty",
  "place_category": "string — category of the place or empty",
  "recommended_action": "ACCEPT" | "PAUSE" | "RESUME" | "COMPLETE" | "RECLASSIFY" | "REJECT",
  "confidence": 0.0-1.0,
  "uncertainty": 0.0-1.0,
  "reasoning": "string — brief explanation of your resolution"
}

Rules:
- Always return valid JSON matching this schema.
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
