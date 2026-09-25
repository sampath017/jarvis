"""
Load Context node — scoped local database retrieval.

Class-based node implementation for loading context from SQLite.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
            context_memory = []
            semantic_contexts = []

            # A Cloud Run request can land on any instance.  Prefer the
            # uid-scoped Firestore session so journey context survives an
            # instance recycle; SQLite remains an offline/local fallback.
            try:
                from ...services.firestore_service import FirestoreService
                fs = FirestoreService()
                cloud_session = fs.get_active_mobility_session(uid) if fs.is_available else None
                if cloud_session:
                    context["session"] = cloud_session
                if fs.is_available and state.get("request_type") == "USER_COMMAND":
                    context_memory = fs.get_context_memory(uid, limit=20)
                    semantic_contexts = fs.get_semantic_contexts(uid)
                if fs.is_available:
                    for reminder in fs.get_reminders(uid):
                        self.db.create_reminder(uid, reminder)
                    for place in fs.get_places(uid):
                        self.db.create_place(uid, place)
            except Exception as cloud_err:
                logger.info("Optional Firestore session hydration skipped: %s", cloud_err)

            # Retrieve the latest GPS reading from context events
            latest_gps = None
            try:
                latest_gps = self.db.get_latest_gps(uid)
                if latest_gps:
                    observed = datetime.fromisoformat(str(latest_gps.get("observed_at", "")).replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                    if not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 300:
                        latest_gps = None
            except Exception as e:
                latest_gps = None
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
                elif latest_gps and state.get("request_type") == "USER_COMMAND":
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
                "context_memory": context_memory,
                "semantic_contexts": semantic_contexts,
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
