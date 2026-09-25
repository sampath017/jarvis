"""Reduce durable semantic contexts after a mobility session transition."""

from __future__ import annotations

from datetime import datetime, timezone

from ...backend.semantic_context import (
    GeoPoint, SemanticContextLedger, SemanticObservation, SemanticPlace,
    SemanticPlaceKind,
)
from ...services.firestore_service import FirestoreService


class SemanticContextNode:
    """Maintain independent parked/dwell/shop contexts in Firestore.

    The node is intentionally event-driven.  It performs no location polling
    and never invokes a model; the conversational agent creates policies while
    this reducer turns verified transition facts into durable context.
    """

    def __call__(self, state: dict) -> dict:
        uid = state.get("uid", "")
        packet = state.get("context_packet") or {}
        session = state.get("session") or {}
        gps = packet.get("gps") or {}
        if not uid or packet.get("transition") == "EXIT":
            return {"semantic_contexts": []}

        fs = FirestoreService()
        existing = fs.get_semantic_contexts(uid, active_only=False) if fs.is_available else []
        ledger = SemanticContextLedger.from_dicts(existing)
        place = self._trusted_place(packet.get("nearby_pois") or [])
        location = None
        if gps.get("latitude") is not None and gps.get("longitude") is not None:
            location = GeoPoint(float(gps["latitude"]), float(gps["longitude"]), float(gps.get("accuracy_m") or 25.0))
        parking = session.get("parking_gps") or {}
        parking_location = None
        if parking.get("latitude") is not None and parking.get("longitude") is not None:
            parking_location = GeoPoint(float(parking["latitude"]), float(parking["longitude"]), float(parking.get("accuracy_m") or 25.0))
        timestamp = packet.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        observation = SemanticObservation(
            event_id=str(packet.get("event_id", "")), occurred_at=timestamp,
            activity=str(packet.get("activity", "UNKNOWN")).upper(), location=location,
            mobility_session_id=session.get("session_id"), mobility_status=session.get("status"),
            parking_location=parking_location, place=place,
        )
        changes = ledger.reduce(observation)
        if fs.is_available:
            for change in changes:
                if change.context.last_event_id == observation.event_id:
                    if not fs.save_semantic_context(uid, change.context.context_id, change.context.to_dict()):
                        raise RuntimeError("Could not persist semantic context")
        return {
            "semantic_contexts": ledger.to_dicts(),
            "semantic_context_changes": [change.reason for change in changes if change.should_evaluate_agent],
        }

    @staticmethod
    def _trusted_place(pois: list[dict]) -> SemanticPlace | None:
        """Accept only a provider's explicit business category; never use its name."""
        for poi in pois:
            category = str(poi.get("category", "")).upper()
            if category in {"SHOP", "STORE", "SUPERMARKET", "GROCERY_STORE", "RETAIL"}:
                confidence = float(poi.get("confidence", 0.0))
                if confidence >= 0.8 and float(poi.get("distance_m", 9999)) <= 40:
                    return SemanticPlace(SemanticPlaceKind.SHOP, confidence, poi.get("place_id"), poi.get("name"))
        return None
