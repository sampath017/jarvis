"""
Tier 1 Resolve node — resolve ambiguous physical context.

Class-based node implementation for LLM Tier 1 context resolution.
"""

from __future__ import annotations

import logging

from ..state import JarvisState
from .context_gate import hydrate_packet, hydrate_session
from ...cloud.tier1_reasoner import Tier1Reasoner
from ...services.places_client import PlacesClient
from ...models.schemas import Tier1Request

logger = logging.getLogger(__name__)


class Tier1ResolveNode:
    """Class-based node handler to resolve telemetry ambiguity via Tier 1 LLM."""

    def __init__(self, reasoner: Tier1Reasoner | None = None) -> None:
        self.reasoner = reasoner or Tier1Reasoner()

    def __call__(self, state: JarvisState) -> dict:
        """Resolve raw telemetry ambiguity without directly changing a session."""
        if not state.get("needs_tier1", False):
            return {"tier1_invoked": False, "tier1_response": None}

        uid = state.get("uid", "")
        packet_dict = dict(state.get("context_packet", {}))
        conflicts = state.get("conflicts", [])
        packet = hydrate_packet(packet_dict)
        current_session = hydrate_session(state.get("session"))

        # Places enrichment is optional and only occurs for place/location ambiguity
        if packet.gps and not packet.nearby_pois and any(
            word in "; ".join(conflicts).lower()
            for word in ("poi", "place", "location", "multiple")
        ):
            try:
                nearby_pois = PlacesClient().search_nearby(
                    latitude=packet.gps.latitude,
                    longitude=packet.gps.longitude,
                    uid=uid,
                )
                packet_dict["nearby_pois"] = [poi.model_dump(mode="json") for poi in nearby_pois]
                packet = hydrate_packet(packet_dict)
            except Exception as exception:
                logger.warning("Places enrichment failed: %s", exception)

        request = Tier1Request(
            event_id=packet.event_id,
            context_packet=packet,
            session=current_session,
            conflict_reason="; ".join(conflicts),
            classification_confidence=packet.classification_confidence,
            gps_accuracy_m=packet.gps.accuracy_m if packet.gps else 0.0,
        )

        try:
            response = self.reasoner.resolve(request)
            return {
                "tier1_invoked": True,
                "tier1_response": response.model_dump(mode="json"),
                "context_packet": packet_dict,
            }
        except Exception as exception:
            logger.error("Tier 1 resolution failed: %s", exception)
            return {
                "tier1_invoked": True,
                "tier1_response": {
                    "resolved_vehicle": "UNKNOWN",
                    "recommended_action": "REJECT",
                    "confidence": 0.0,
                    "uncertainty": 1.0,
                    "reasoning": f"Tier 1 execution failed: {exception}",
                },
                "context_packet": packet_dict,
            }


# Callable instance for graph composition
tier1_resolve = Tier1ResolveNode()
