"""
Tier 1: Intermediate Context Reasoner

Resolves ambiguous physical context when deterministic systems cannot
produce a confident result. Supports mock mode (rule-based) and live
mode (OpenRouter API).

Returns schema-validated JSON — never unrestricted prose.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER1,
    OPENROUTER_TEMPERATURE,
    USE_MOCK_LLM,
)
from ..models.enums import ActivityType, Tier1Action, VehicleClass
from ..models.schemas import Tier1Request, Tier1Response


class Tier1Reasoner:
    """
    Tier 1 Context Reasoner.

    Mock mode: deterministic rule-based resolution.
    Live mode: sends structured prompt to OpenRouter, parses JSON response.
    """

    def __init__(self, use_mock: bool | None = None) -> None:
        self.use_mock = use_mock if use_mock is not None else USE_MOCK_LLM
        self.api_key = os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)

    def resolve(self, request: Tier1Request) -> Tier1Response:
        """Resolve ambiguous context using mock or live LLM."""
        if self.use_mock:
            return self._mock_resolve(request)
        return self._live_resolve(request)

    # ── Mock Mode ────────────────────────────────────────────────────────

    def _mock_resolve(self, request: Tier1Request) -> Tier1Response:
        """Rule-based mock resolution for testing without API calls."""
        start = time.perf_counter()

        packet = request.context_packet
        activity = packet.activity_transition
        classification = packet.classification
        gps = packet.gps
        pois = packet.nearby_pois
        session = request.session
        conflict = request.conflict_reason

        # Default response
        resolved_vehicle = VehicleClass.UNKNOWN
        resolved_place = ""
        place_category = ""
        action = Tier1Action.ACCEPT
        confidence = 0.5
        uncertainty = 0.5
        reasoning_parts: list[str] = []

        # ── Rule 1: GPS says stationary but IMU says vehicle ────────────
        if "GPS shows stationary" in conflict:
            reasoning_parts.append("GPS indicates no movement but vehicle detected.")
            if classification and classification.confidence > 0.6:
                resolved_vehicle = classification.vehicle_class
                action = Tier1Action.ACCEPT
                confidence = 0.7
                uncertainty = 0.3
                reasoning_parts.append(
                    "Classification confidence is moderate; likely traffic stop or engine idling."
                )
            else:
                action = Tier1Action.PAUSE
                confidence = 0.5
                uncertainty = 0.5
                reasoning_parts.append("Low confidence — recommend pausing session.")

        # ── Rule 2: Poor GPS accuracy ───────────────────────────────────
        if "GPS accuracy poor" in conflict:
            reasoning_parts.append(
                f"GPS accuracy is {request.gps_accuracy_m:.0f}m — too imprecise for POI resolution."
            )
            if classification and classification.is_match:
                resolved_vehicle = VehicleClass.HUNTER_350
                action = Tier1Action.ACCEPT
                confidence = 0.6
                reasoning_parts.append(
                    "Vehicle fingerprint matches Hunter 350; accepting despite poor GPS."
                )
            uncertainty = min(1.0, uncertainty + 0.2)

        # ── Rule 3: Weak fingerprint with IN_VEHICLE ────────────────────
        if "weak fingerprint" in conflict:
            reasoning_parts.append(
                f"Vehicle fingerprint confidence is low ({request.classification_confidence:.2f})."
            )
            if activity and activity.activity == ActivityType.IN_VEHICLE:
                resolved_vehicle = VehicleClass.UNKNOWN
                action = Tier1Action.RECLASSIFY
                confidence = 0.4
                uncertainty = 0.6
                reasoning_parts.append(
                    "IN_VEHICLE detected but fingerprint weak — recommend reclassification."
                )

        # ── Rule 4: Multiple candidate POIs ─────────────────────────────
        if "Multiple candidate POIs" in conflict:
            if pois:
                # Pick the closest one with highest confidence
                best_poi = max(pois, key=lambda p: p.confidence)
                resolved_place = best_poi.name
                place_category = best_poi.category
                confidence = max(confidence, best_poi.confidence * 0.8)
                reasoning_parts.append(
                    f"Multiple POIs detected. Best match: {best_poi.name} "
                    f"(category: {best_poi.category}, confidence: {best_poi.confidence:.2f})."
                )

        # ── Rule 5: Unknown POI ─────────────────────────────────────────
        if "Unknown POI category" in conflict:
            unknown_pois = [p for p in pois if p.category == "unknown"]
            if unknown_pois:
                poi = unknown_pois[0]
                resolved_place = poi.name
                place_category = "retail"  # Default guess
                confidence = 0.4
                uncertainty = 0.6
                reasoning_parts.append(
                    f"Unknown POI '{poi.name}' — classified as 'retail' with low confidence."
                )

        # ── Rule 6: Session ambiguity ───────────────────────────────────
        if "Session paused with ambiguous context" in conflict:
            if session:
                action = Tier1Action.PAUSE
                confidence = 0.5
                uncertainty = 0.5
                reasoning_parts.append(
                    "Session is paused with ambiguous context. "
                    "Maintaining PAUSED state until clearer signal arrives."
                )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return Tier1Response(
            resolved_vehicle=resolved_vehicle,
            resolved_place=resolved_place,
            place_category=place_category,
            recommended_action=action,
            confidence=round(confidence, 4),
            uncertainty=round(uncertainty, 4),
            reasoning=" ".join(reasoning_parts) or "No specific conflict resolution needed.",
            model_id="mock-tier1-v1",
            tokens_used=0,
            latency_ms=round(elapsed_ms, 2),
        )

    # ── Live Mode (OpenRouter) ───────────────────────────────────────────

    def _live_resolve(self, request: Tier1Request) -> Tier1Response:
        """Call OpenRouter API for Tier 1 resolution."""
        import httpx

        start = time.perf_counter()
        prompt = self._build_prompt(request)

        try:
            response = httpx.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL_TIER1,
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": OPENROUTER_MAX_TOKENS,
                    "temperature": OPENROUTER_TEMPERATURE,
                    "response_format": {"type": "json_object"},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            elapsed_ms = (time.perf_counter() - start) * 1000

            parsed = json.loads(content)
            return Tier1Response(
                resolved_vehicle=VehicleClass(parsed.get("resolved_vehicle", "UNKNOWN")),
                resolved_place=parsed.get("resolved_place", ""),
                place_category=parsed.get("place_category", ""),
                recommended_action=Tier1Action(parsed.get("recommended_action", "ACCEPT")),
                confidence=parsed.get("confidence", 0.5),
                uncertainty=parsed.get("uncertainty", 0.5),
                reasoning=parsed.get("reasoning", ""),
                model_id=OPENROUTER_MODEL_TIER1,
                tokens_used=tokens,
                latency_ms=round(elapsed_ms, 2),
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return Tier1Response(
                reasoning=f"Tier 1 API error: {e}",
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

        if packet.activity_transition:
            sections.append(
                f"Activity: {packet.activity_transition.activity.value} "
                f"(transition: {packet.activity_transition.transition.value})"
            )
        if packet.classification:
            sections.append(
                f"Classification: {packet.classification.vehicle_class.value} "
                f"(confidence: {packet.classification.confidence:.2f})"
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
