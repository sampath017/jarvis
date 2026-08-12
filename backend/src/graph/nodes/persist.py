"""
Persist node — persist final session, messages, and context events to local database.

Class-based node implementation for state persistence.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from ..state import JarvisState
from ...services.database import DatabaseService
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
                    persisted["session_saved"] = True

            # 2. Persist context event
            if request_type == "CONTEXT_EVENT":
                event_id = state.get("event_id")
                packet = state.get("context_packet")
                if event_id and packet:
                    self.db.create_event_idempotent(uid, event_id, packet)
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
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    persisted["messages_saved"] += 1

                    if assistant_msg:
                        self.db.append_chat_message(uid, thread_id, {
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                            "content": assistant_msg,
                            "timestamp": datetime.utcnow().isoformat(),
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
