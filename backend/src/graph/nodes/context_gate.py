"""
Context Gate node — evaluate physical telemetry ambiguity.

Class-based node implementation for gating raw evidence before state mutations.
"""

from __future__ import annotations

from datetime import datetime

from ..state import JarvisState
from ...backend.context_resolver import ContextResolver
from ...backend.audit_log import audit_from_state
from ...services.database import DatabaseService
from ...models.schemas import ContextPacket, FeatureSummary, GPSReading, POICandidate, SessionState


def hydrate_packet(packet_dict: dict) -> ContextPacket:
    """Rebuild the complete typed packet without dropping burst evidence."""
    gps_data = packet_dict.get("gps")
    feature_data = packet_dict.get("feature_summary")
    return ContextPacket(
        event_id=packet_dict.get("event_id", ""),
        timestamp=packet_dict.get("timestamp") or datetime.utcnow().isoformat(),
        activity=packet_dict.get("activity", ""),
        transition=packet_dict.get("transition", "ENTER"),
        gps=GPSReading(**gps_data) if gps_data else None,
        feature_summary=FeatureSummary(**feature_data) if feature_data else None,
        nearby_pois=[POICandidate(**poi) for poi in packet_dict.get("nearby_pois", [])],
        session_id=packet_dict.get("session_id"),
        classification_confidence=packet_dict.get("classification_confidence", 0.0),
        vehicle_class_hint=packet_dict.get("vehicle_class_hint", ""),
    )


def hydrate_session(session_dict: dict | None) -> SessionState | None:
    if not session_dict:
        return None
    try:
        return SessionState(**session_dict)
    except Exception:
        return None


class ContextGateNode:
    """Class-based node handler to assess ambiguity on raw evidence."""

    def __init__(self, resolver: ContextResolver | None = None, db: DatabaseService | None = None) -> None:
        self.resolver = resolver or ContextResolver()
        self.db = db

    def __call__(self, state: JarvisState) -> dict:
        """Assess ambiguity on raw evidence before invoking SessionManager."""
        packet = hydrate_packet(state.get("context_packet", {}))
        session = hydrate_session(state.get("session"))
        conflicts = self.resolver.detect_conflicts(packet, session)
        audit = audit_from_state(state, self.db)

        audit.log(
            node_name="context_gate",
            action="conflict_detection",
            category="CONTEXT",
            event_id=packet.event_id,
            input_summary={
                "activity": packet.activity,
                "transition": packet.transition,
                "classification_confidence": packet.classification_confidence,
                "vehicle_class_hint": packet.vehicle_class_hint,
                "has_gps": packet.gps is not None,
                "session_status": session.status.value if session else None,
            },
            output_summary={
                "conflicts": conflicts,
                "needs_tier1": bool(conflicts),
                "conflict_count": len(conflicts),
            },
            gps_lat=packet.gps.latitude if packet.gps else None,
            gps_lon=packet.gps.longitude if packet.gps else None,
            confidence=packet.classification_confidence,
        )

        return {
            "conflicts": conflicts,
            "needs_tier1": bool(conflicts),
        }


# Callable instance for graph composition
context_gate = ContextGateNode()
