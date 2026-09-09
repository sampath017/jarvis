"""
Load Context node — scoped local database retrieval.

Class-based node implementation for loading context from SQLite.
"""

from __future__ import annotations

import logging
from ..state import JarvisState
from ...services.database import DatabaseService
from ...backend.audit_log import audit_from_state

logger = logging.getLogger(__name__)


class LoadContextNode:
    """Class-based node handler for scoped local database context retrieval."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()

    def __call__(self, state: JarvisState) -> dict:
        """Load scoped context from local database for the verified user."""
        uid = state.get("uid", "")
        thread_id = state.get("thread_id") or state.get("raw_request", {}).get("thread_id")
        audit = audit_from_state(state, self.db)

        if not uid:
            audit.log(
                node_name="load_context",
                action="no_authenticated_user",
                category="CONTEXT",
                execution_result="error",
                error_detail="No authenticated user",
            )
            return {"error": "No authenticated user"}

        try:
            context = self.db.load_scoped_context(uid=uid, thread_id=thread_id)

            # Retrieve the latest GPS reading from context events
            latest_gps = None
            try:
                latest_gps = self.db.get_latest_gps(uid)
            except Exception as e:
                logger.info("Optional latest GPS fetch skipped: %s", e)

            # Merge latest GPS and nearby POIs into the context packet
            packet = dict(state.get("context_packet") or {})
            raw_req = state.get("raw_request") or {}

            gps_info = packet.get("gps")
            if not gps_info:
                if raw_req.get("latitude") is not None and raw_req.get("longitude") is not None:
                    gps_info = {
                        "latitude": raw_req["latitude"],
                        "longitude": raw_req["longitude"],
                        "accuracy_m": 10.0,
                    }
                    packet["gps"] = gps_info
                elif latest_gps:
                    gps_info = latest_gps
                    packet["gps"] = latest_gps

            if gps_info and not packet.get("nearby_pois"):
                try:
                    from ...services.places_client import PlacesClient
                    client = PlacesClient()
                    pois = client.search_nearby(
                        latitude=gps_info["latitude"],
                        longitude=gps_info["longitude"],
                        radius_m=250.0,
                        uid=uid,
                        max_results=5,
                    )
                    if pois:
                        packet["nearby_pois"] = [p.model_dump() for p in pois]
                except Exception as pe:
                    logger.info("Optional nearby POI search skipped: %s", pe)

            # Audit: log context loaded
            session = context.get("session")
            gps = packet.get("gps") or latest_gps or {}
            audit.log(
                node_name="load_context",
                action="context_loaded",
                category="CONTEXT",
                event_id=state.get("event_id", ""),
                input_summary={
                    "uid": uid,
                    "thread_id": thread_id,
                },
                output_summary={
                    "session_status": session.get("status") if session else None,
                    "session_id": session.get("session_id") if session else None,
                    "task_count": len(context.get("tasks", [])),
                    "message_count": len(context.get("messages", [])),
                    "preference_count": len(context.get("preferences", [])),
                    "has_gps": bool(gps),
                    "nearby_poi_count": len(packet.get("nearby_pois", [])),
                },
                gps_lat=gps.get("latitude") if isinstance(gps, dict) else None,
                gps_lon=gps.get("longitude") if isinstance(gps, dict) else None,
            )

            client_history = state.get("raw_request", {}).get("history", [])
            messages = client_history if client_history else context.get("messages", [])

            return {
                "thread_id": thread_id,
                "session": context.get("session"),
                "tasks": context.get("tasks", []),
                "reminders": context.get("reminders", []),
                "notes": context.get("notes", []),
                "messages": messages,
                "preferences": context.get("preferences", []),
                "context_packet": packet,
            }

        except Exception as e:
            logger.critical("Failed to load context: %s", e, exc_info=True)
            audit.log(
                node_name="load_context",
                action="context_load_failed",
                category="CONTEXT",
                event_id=state.get("event_id", ""),
                execution_result="error",
                error_detail=str(e),
            )
            return {
                "session": None,
                "tasks": [],
                "messages": [],
                "preferences": [],
                "error": f"Failed to load context: {e}",
            }


# Callable instance for graph composition
load_context = LoadContextNode()
