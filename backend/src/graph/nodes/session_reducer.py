"""
Session Reducer node — apply mobility state transitions.

Class-based node implementation for journey session state reductions.
"""

from __future__ import annotations

from ..state import JarvisState
from .context_gate import hydrate_packet, hydrate_session
from ...backend.session_manager import SessionManager
from ...backend.audit_log import audit_from_state
from ...services.database import DatabaseService
from ...models.schemas import Tier1Response


class SessionReducerNode:
    """Class-based node handler to execute deterministic journey session updates."""

    def __init__(self, session_manager: SessionManager | None = None, db: DatabaseService | None = None) -> None:
        self.session_manager = session_manager or SessionManager()
        self.db = db

    def __call__(self, state: JarvisState) -> dict:
        """Apply either verified raw telemetry or a bounded Tier 1 resolution."""
        packet = hydrate_packet(state.get("context_packet", {}))
        current_session = hydrate_session(state.get("session"))
        tier1_dict = state.get("tier1_response")
        audit = audit_from_state(state, self.db)

        old_status = current_session.status.value if current_session else None
        old_vehicle = current_session.vehicle_class.value if current_session else None

        if tier1_dict:
            try:
                tier1 = Tier1Response(**tier1_dict)
                updated_session = self.session_manager.apply_tier1_resolution(
                    packet=packet,
                    current_session=current_session,
                    action=tier1.recommended_action.value,
                    resolved_vehicle=tier1.resolved_vehicle.value,
                    confidence=tier1.confidence,
                )
            except Exception:
                # A malformed resolution must never promote or mutate a journey.
                updated_session = current_session
        else:
            updated_session = self.session_manager.process_event(packet, current_session)

        new_status = updated_session.status.value if updated_session else None
        new_vehicle = updated_session.vehicle_class.value if updated_session else None

        audit.log(
            node_name="session_reducer",
            action="session_transition",
            category="SESSION",
            event_id=packet.event_id,
            input_summary={
                "old_status": old_status,
                "old_vehicle_class": old_vehicle,
                "tier1_applied": tier1_dict is not None,
                "activity": packet.activity,
                "transition": packet.transition,
            },
            output_summary={
                "new_status": new_status,
                "new_vehicle_class": new_vehicle,
                "session_id": updated_session.session_id if updated_session else None,
                "status_changed": old_status != new_status,
                "vehicle_changed": old_vehicle != new_vehicle,
            },
            gps_lat=packet.gps.latitude if packet.gps else None,
            gps_lon=packet.gps.longitude if packet.gps else None,
            confidence=updated_session.classification_confidence if updated_session else None,
        )

        return {
            "session": updated_session.model_dump(mode="json") if updated_session else None,
            "session_id": updated_session.session_id if updated_session else None,
        }


# Callable instance for graph composition
session_reducer = SessionReducerNode()
