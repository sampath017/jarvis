"""
Tier 1 Context Agent Node — Autonomous LangGraph Context Reasoner.

Executes reasoning loops over physical sensor telemetry with place lookup,
vibration signature matching, and geofence evaluation.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...cloud.tier1_agent_tools import build_tier1_tools
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state
from ...models.enums import Tier1Action, VehicleClass
from ...models.schemas import Tier1Response
from ...settings import (
    AGENT_MAX_ITERATIONS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL_TIER1,
)
from ..state import JarvisState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TIER1 = """You are the Context & Telemetry Reasoner for Jarvis, a context-aware Android
assistant. You run silently in the background — you never address the user
directly and your output is never shown to them as-is. Your job is to resolve
raw sensor telemetry into a compact, structured context signal for the
downstream Context Gate / Session Manager state machine.

TOOLS
- lookup_nearby_places(lat, lon): resolve GPS coordinates to a nearby named
  place via Google Places or the local cache.
- match_vibration_signature(features): match IMU/vibration features against
  the known Hunter 350 spectral signature to confirm ride context.
- check_saved_geofences(lat, lon): check distance to the user's saved places
  (Home, Gym, Office).

RULES
1. Call only the tools the current event actually needs. Most telemetry
   events resolve with a single tool call — do not call all three by default.
2. Be decisive. No speculative or exploratory calls.
3. Your final output is not conversational. Return a single compact
   structured result the state machine can parse, e.g.:
   "at_geofence:home confidence:0.92" or "riding:hunter350 near:place_id=X4F2"
4. If tool results conflict, or confidence stays below the resolution
   threshold, say so plainly — return "context:uncertain reason:<short reason>"
   rather than guessing.
5. No commentary, apology, or explanation text. Terse and structured, always."""


class Tier1AgentNode:
    """Class-based node handler for Tier 1 Context Reasoner Agent."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()
        self.llm = ChatOpenAI(
            model=OPENROUTER_MODEL_TIER1,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            temperature=0.0,
            max_retries=2,
            request_timeout=25.0,
            extra_body={"reasoning": {"effort": "low"}},
        )

    def __call__(self, state: JarvisState) -> dict[str, Any]:
        uid = state.get("uid", "")
        tools = build_tier1_tools(self.db, uid)
        llm_with_tools = self.llm.bind_tools(tools)

        step_count = state.get("tier1_step_count", 0) + 1
        messages = list(state.get("tier1_messages", []))
        audit = audit_from_state(state, self.db)
        event_id = state.get("event_id", "")

        packet = state.get("context_packet", {})

        if not messages:
            imu = packet.get("imu", {})
            gps = packet.get("gps", {})
            user_msg = (
                f"Raw Sensor Telemetry Event:\n"
                f"- Activity: {packet.get('activity', 'UNKNOWN')} (Confidence: {packet.get('classification_confidence', 0.0)})\n"
                f"- GPS: Lat {gps.get('latitude', 0.0):.6f}, Lon {gps.get('longitude', 0.0):.6f} (Speed: {gps.get('speed_mps', 0.0)} m/s)\n"
                f"- IMU: dominant_frequency_hz={imu.get('dominant_frequency_hz', 0.0)}, rms_energy={imu.get('rms_energy', 0.0)}, spectral_entropy={imu.get('spectral_entropy', 0.0)}"
            )
            messages = [SystemMessage(content=SYSTEM_PROMPT_TIER1), HumanMessage(content=user_msg)]

        # Circuit breaker: stop if max iterations exceeded
        if step_count > AGENT_MAX_ITERATIONS:
            logger.warning("Tier 1 step limit reached (%d)", AGENT_MAX_ITERATIONS)
            return {"tier1_invoked": True}

        try:
            ai_msg: AIMessage = llm_with_tools.invoke(messages)  # type: ignore[assignment]
        except Exception as e:
            logger.error("Tier 1 agent invocation error: %s", e, exc_info=True)
            ai_msg = self.llm.invoke(messages)  # type: ignore[assignment]

        updated_messages = messages + [ai_msg]
        has_tool_calls = bool(getattr(ai_msg, "tool_calls", []))
        content_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content or "")

        res_dict: dict[str, Any] = {
            "tier1_messages": updated_messages,
            "tier1_step_count": step_count,
            "tier1_invoked": True,
        }

        # If agent finished calling tools, parse structured signal for downstream Session Manager
        if not has_tool_calls or step_count >= AGENT_MAX_ITERATIONS:
            tier1_res = self._parse_structured_output(content_text)
            res_dict["tier1_response"] = tier1_res.model_dump(mode="json")

        audit.log(
            node_name="tier1_agent",
            action=f"turn_{step_count}",
            category="CONTEXT",
            event_id=event_id,
            input_summary={"step": step_count, "has_tool_calls": has_tool_calls},
            output_summary={
                "tool_calls_count": len(getattr(ai_msg, "tool_calls", [])),
                "content_preview": content_text[:120],
            },
            model_id=OPENROUTER_MODEL_TIER1,
        )

        return res_dict

    def _parse_structured_output(self, text: str) -> Tier1Response:
        """Parse terse structured output into a typed Tier1Response."""
        lower = text.lower()

        # Extract confidence if present (e.g., confidence:0.92)
        conf_match = re.search(r"confidence\s*[:=]\s*([0-9.]+)", lower)
        confidence = float(conf_match.group(1)) if conf_match else 0.85
        confidence = min(max(confidence, 0.0), 1.0)
        uncertainty = max(0.0, 1.0 - confidence)

        # Extract place if present (e.g. at_geofence:home or near:place_id=X)
        place_match = re.search(r"(?:at_geofence|near|place)\s*[:=]\s*([a-zA-Z0-9_\-]+)", lower)
        resolved_place = place_match.group(1) if place_match else ""

        # Determine vehicle & action
        if "uncertain" in lower or "confidence" in lower and confidence < 0.6:
            return Tier1Response(
                resolved_vehicle=VehicleClass.UNKNOWN,
                resolved_place=resolved_place,
                recommended_action=Tier1Action.REJECT,
                confidence=confidence,
                uncertainty=uncertainty,
                reasoning=text[:300],
            )

        if "hunter" in lower or "motorcycle" in lower or "riding" in lower:
            resolved_vehicle = VehicleClass.HUNTER_350
            action = Tier1Action.ACCEPT
        elif "car" in lower or "bus" in lower or "vehicle" in lower:
            resolved_vehicle = VehicleClass.CAR
            action = Tier1Action.REJECT
        elif "walk" in lower or "pedestrian" in lower:
            resolved_vehicle = VehicleClass.UNKNOWN
            action = Tier1Action.ACCEPT
        else:
            resolved_vehicle = VehicleClass.HUNTER_350 if confidence >= 0.75 else VehicleClass.UNKNOWN
            action = Tier1Action.ACCEPT

        return Tier1Response(
            resolved_vehicle=resolved_vehicle,
            resolved_place=resolved_place,
            recommended_action=action,
            confidence=confidence,
            uncertainty=uncertainty,
            reasoning=text[:300],
        )
