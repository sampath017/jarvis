"""
Tier 2 Orchestrate node — agentic command orchestrator.

Class-based node implementation for LLM Tier 2 command orchestration.
"""

from __future__ import annotations

import logging
from ..state import JarvisState
from ...cloud.tier2_orchestrator import Tier2Orchestrator
from ...cloud.function_registry import FunctionRegistry
from ...models.schemas import (
    ContextPacket,
    GPSReading,
    SessionState,
    Tier1Response,
    Tier2Request,
)

logger = logging.getLogger(__name__)


class Tier2OrchestrateNode:
    """Class-based node handler to orchestrate user commands into allow-listed function calls."""

    def __call__(self, state: JarvisState) -> dict:
        """Orchestrate user command into function calls using Tier 2 reasoner."""
        user_command = state.get("user_command", "")
        if not user_command:
            return {"tier2_invoked": False}

        packet_dict = state.get("context_packet", {})
        session_dict = state.get("session")
        tier1_resp_dict = state.get("tier1_response")

        # Reconstruct GPS and packet
        gps_data = packet_dict.get("gps") if packet_dict else None
        gps = GPSReading(**gps_data) if gps_data else None

        packet = None
        if packet_dict:
            packet = ContextPacket(
                event_id=packet_dict.get("event_id", ""),
                activity=packet_dict.get("activity", ""),
                transition=packet_dict.get("transition", "ENTER"),
                gps=gps,
                classification_confidence=packet_dict.get(
                    "classification_confidence", 0.0),
                vehicle_class_hint=packet_dict.get("vehicle_class_hint", ""),
            )

        # Reconstruct session
        session = None
        if session_dict:
            try:
                session = SessionState(**session_dict)
            except Exception:
                session = None

        # Reconstruct Tier 1 response
        tier1_response = None
        if tier1_resp_dict:
            tier1_response = Tier1Response(**tier1_resp_dict)

        # Determine resolved place/category
        resolved_place = ""
        resolved_place_category = ""
        if tier1_response and tier1_response.resolved_place:
            resolved_place = tier1_response.resolved_place
            resolved_place_category = tier1_response.place_category
        elif packet_dict and packet_dict.get("nearby_pois"):
            # Fallback to closest high confidence POI
            pois = packet_dict.get("nearby_pois", [])
            if pois:
                best = max(pois, key=lambda p: p.get("confidence", 0.0))
                resolved_place = best.get("name", "")
                resolved_place_category = best.get("category", "")

        # Resolve exact address if GPS is present using Google Geocoding API
        resolved_address = None
        if gps:
            from ...settings import GOOGLE_PLACES_API_KEY
            if GOOGLE_PLACES_API_KEY:
                try:
                    import httpx
                    r = httpx.get(
                        f"https://maps.googleapis.com/maps/api/geocode/json?latlng={gps.latitude},{gps.longitude}&key={GOOGLE_PLACES_API_KEY}",
                        timeout=5.0
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("status") == "OK" and data.get("results"):
                            resolved_address = data["results"][0].get(
                                "formatted_address")
                except Exception as e:
                    logger.warning(
                        "Failed to reverse geocode GPS location with Google Maps: %s", e)
            else:
                logger.warning(
                    "Google Places API key is placeholder or empty - skipping Google Maps Geocoding")

        # Build Tier 2 request
        req = Tier2Request(
            user_command=user_command,
            thread_id=state.get("thread_id", ""),
            context_packet=packet,
            session=session,
            tier1_response=tier1_response,
            resolved_place=resolved_place,
            resolved_place_category=resolved_place_category,
            resolved_address=resolved_address,
            recent_messages=state.get("messages", []),
            user_tasks=state.get("tasks", []),
        )

        # Instantiate orchestrator
        registry = FunctionRegistry(None)  # type: ignore[arg-type]
        orchestrator = Tier2Orchestrator(registry)

        try:
            res = orchestrator.process_command(req)
            res_dict = res.model_dump(mode="json")

            # Extract function calls
            function_calls = res_dict.get("function_calls", [])

            return {
                "tier2_invoked": True,
                "tier2_response": res_dict,
                "user_response": res.user_response,
                "tool_calls": function_calls,
            }

        except Exception as e:
            logger.error("Tier 2 orchestrator failed: %s", e)
            return {
                "tier2_invoked": True,
                "tier2_response": {
                    "user_response": "I encountered an error trying to process that command.",
                    "reasoning": f"Tier 2 execution failed: {e}",
                },
                "user_response": "I encountered an error trying to process that command.",
                "tool_calls": [],
            }


# Callable instance for graph composition
tier2_orchestrate = Tier2OrchestrateNode()
