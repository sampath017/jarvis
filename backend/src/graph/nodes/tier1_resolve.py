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
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state
from ...models.schemas import Tier1Request

logger = logging.getLogger(__name__)


class Tier1ResolveNode:
    """Class-based node handler to resolve telemetry ambiguity via Tier 1 LLM."""

    def __init__(self, reasoner: Tier1Reasoner | None = None, db: DatabaseService | None = None) -> None:
        self.reasoner = reasoner or Tier1Reasoner()
        self.db = db

    def __call__(self, state: JarvisState) -> dict:
        """Resolve raw telemetry ambiguity without directly changing a session."""
        audit = audit_from_state(state, self.db)

        if not state.get("needs_tier1", False):
            audit.log(
                node_name="tier1_resolve",
                action="skipped",
                category="LLM",
                event_id=state.get("event_id", ""),
                execution_result="skipped",
                output_summary={"reason": "needs_tier1 is False"},
            )
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

                audit.log(
                    node_name="tier1_resolve",
                    action="places_enrichment",
                    category="CONTEXT",
                    event_id=packet.event_id,
                    output_summary={"poi_count": len(nearby_pois)},
                    gps_lat=packet.gps.latitude,
                    gps_lon=packet.gps.longitude,
                )
            except Exception as exception:
                logger.warning("Places enrichment failed: %s", exception)
                audit.log(
                    node_name="tier1_resolve",
                    action="places_enrichment_failed",
                    category="CONTEXT",
                    event_id=packet.event_id,
                    execution_result="error",
                    error_detail=str(exception),
                )

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

            audit.log(
                node_name="tier1_resolve",
                action="llm_resolution",
                category="LLM",
                event_id=packet.event_id,
                input_summary={
                    "conflicts": conflicts,
                    "classification_confidence": packet.classification_confidence,
                    "gps_accuracy_m": packet.gps.accuracy_m if packet.gps else 0.0,
                },
                output_summary={
                    "resolved_vehicle": response.resolved_vehicle.value,
                    "resolved_place": response.resolved_place,
                    "recommended_action": response.recommended_action.value,
                    "confidence": response.confidence,
                    "uncertainty": response.uncertainty,
                    "reasoning": response.reasoning,
                },
                model_id=response.model_id,
                confidence=response.confidence,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                gps_lat=packet.gps.latitude if packet.gps else None,
                gps_lon=packet.gps.longitude if packet.gps else None,
            )

            return {
                "tier1_invoked": True,
                "tier1_response": response.model_dump(mode="json"),
                "context_packet": packet_dict,
            }
        except Exception as exception:
            logger.critical("Tier 1 resolution failed: %s", exception, exc_info=True)

            audit.log(
                node_name="tier1_resolve",
                action="llm_resolution_failed",
                category="LLM",
                event_id=packet.event_id,
                execution_result="error",
                error_detail=str(exception),
            )

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
