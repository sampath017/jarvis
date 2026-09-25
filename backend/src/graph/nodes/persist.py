"""
Persist node — persist final session, messages, and context events to local database.

Class-based node implementation for state persistence.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from ..state import JarvisState
from ...services.database import DatabaseService
from ...services.firestore_service import FirestoreService
from ...backend.audit_log import audit_from_state

logger = logging.getLogger(__name__)


class PersistNode:
    """Class-based node handler to persist session, messages, and events to local database."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db or DatabaseService()

    def __call__(self, state: JarvisState) -> dict:
        """Save final run outputs — session, context events, and chat messages."""
        uid = state.get("uid", "")
        run_id = state.get("run_id", "")
        request_type = state.get("request_type", "CONTEXT_EVENT")
        audit = audit_from_state(state, self.db)

        if not uid:
            audit.log(
                node_name="persist",
                action="missing_uid",
                category="SYSTEM",
                execution_result="error",
                error_detail="Missing UID for state persistence",
            )
            return {"error": "Missing UID for state persistence"}

        try:
            persisted = {
                "session_saved": False,
                "event_saved": False,
                "messages_saved": 0,
            }

            # 1. Persist session changes
            session = state.get("session")
            if session:
                session_id = session.get("session_id")
                if session_id:
                    logger.info("Persisting session %s status=%s for uid=%s",
                                session_id, session.get("status"), uid)
                    self.db.upsert_session(uid, session_id, session)
                    # Cloud Run instances are ephemeral.  Keep the cloud
                    # session copy authoritative for cross-instance parking,
                    # dwell, and return-trip continuity; SQLite remains a
                    # short-lived local cache/fallback.
                    fs = FirestoreService()
                    if fs.is_available:
                        if not fs.save_mobility_session(uid, session_id, session):
                            raise RuntimeError("Could not persist cloud session")
                    persisted["session_saved"] = True

            # 2. Persist context event
            if request_type == "CONTEXT_EVENT":
                event_id = state.get("event_id")
                packet = state.get("context_packet")
                if event_id and packet:
                    self.db.create_event_idempotent(uid, event_id, packet)
                    fs = FirestoreService()
                    if fs.is_available:
                        memory = {
                            "source": "phone_observation",
                            "event_type": state.get("raw_request", {}).get("event_type"),
                            "timestamp": packet.get("timestamp"),
                            "activity": packet.get("activity"),
                            "transition": packet.get("transition"),
                            "gps": packet.get("gps"),
                            "mobility_session_id": state.get("session_id"),
                            "nearby_candidates": packet.get("nearby_pois", [])[:5],
                            "context_changes": state.get("semantic_context_changes", []),
                            "contexts": [c for c in state.get("semantic_contexts", [])
                                         if c.get("active") and c.get("confidence", 0) >= 0.8],
                        }
                        from ...backend.session_manager import _haversine_m
                        gps = packet.get("gps") or {}
                        memory["saved_places"] = []
                        if gps.get("latitude") is not None and gps.get("longitude") is not None:
                            for place in self.db.list_places(uid):
                                if place.get("latitude") is None or place.get("longitude") is None:
                                    continue
                                distance = _haversine_m(gps["latitude"], gps["longitude"], place["latitude"], place["longitude"])
                                if distance <= float(place.get("radius_m") or 100):
                                    memory["saved_places"].append({"name": place.get("name"), "distance_m": round(distance)})
                        if not fs.save_context_memory(uid, event_id, memory):
                            raise RuntimeError("Could not persist context memory")
                    persisted["event_saved"] = True

            # 3. Append chat messages for command requests
            elif request_type == "USER_COMMAND":
                thread_id = state.get("thread_id")
                user_msg = state.get("user_command")
                assistant_msg = state.get("user_response")

                if thread_id:
                    self.db.append_chat_message(uid, thread_id, {
                        "message_id": str(uuid.uuid4()),
                        "role": "user",
                        "content": user_msg,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    persisted["messages_saved"] += 1

                    if assistant_msg:
                        self.db.append_chat_message(uid, thread_id, {
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                            "content": assistant_msg,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "run_id": run_id,
                        })
                        persisted["messages_saved"] += 1

            # Audit: log persistence summary
            # (No agent_runs table anymore — run summaries are derived from audit_entries)
            audit.log(
                node_name="persist",
                action="state_persisted",
                category="SYSTEM",
                event_id=state.get("event_id", ""),
                output_summary={
                    "session_saved": persisted["session_saved"],
                    "event_saved": persisted["event_saved"],
                    "messages_saved": persisted["messages_saved"],
                    "request_type": request_type,
                    "has_error": bool(state.get("error")),
                },
            )

            return {"error": None}

        except Exception as e:
            logger.critical("Failed to persist state: %s", e, exc_info=True)
            audit.log(
                node_name="persist",
                action="persistence_failed",
                category="SYSTEM",
                event_id=state.get("event_id", ""),
                execution_result="error",
                error_detail=str(e),
            )
            return {"error": f"Persistence failure: {str(e)}"}


# Callable instance for graph composition
persist = PersistNode()
