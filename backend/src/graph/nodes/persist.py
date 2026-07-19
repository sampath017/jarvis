"""
Persist node — persist final session, messages, and audit trail to Firestore.

Class-based node implementation for state persistence.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..state import JarvisState
from ...services.firestore_client import FirestoreService

logger = logging.getLogger(__name__)


class PersistNode:
    """Class-based node handler to persist session, messages, and agent runs to Firestore."""

    def __init__(self, firestore_service: FirestoreService | None = None) -> None:
        self.firestore_service = firestore_service or FirestoreService()

    def __call__(self, state: JarvisState) -> dict:
        """Save final run outputs, session updates, and audits to Firestore."""
        uid = state.get("uid", "")
        run_id = state.get("run_id", "")
        request_type = state.get("request_type", "CONTEXT_EVENT")

        if not uid:
            return {"error": "Missing UID for state persistence"}

        fs = self.firestore_service

        try:
            # 1. Persist Session changes if any
            session = state.get("session")
            if session:
                session_id = session.get("session_id")
                if session_id:
                    logger.info("Persisting session %s status=%s for uid=%s", session_id, session.get("status"), uid)
                    fs.upsert_session(uid, session_id, session)

            # 2. Persist Context Event if this was a context event ingestion
            if request_type == "CONTEXT_EVENT":
                event_id = state.get("event_id")
                packet = state.get("context_packet")
                if event_id and packet:
                    # Deduplicate and create event
                    fs.create_event_idempotent(uid, event_id, packet)

            # 3. Append messages if command request
            elif request_type == "USER_COMMAND":
                thread_id = state.get("thread_id")
                user_msg = state.get("user_command")
                assistant_msg = state.get("user_response")

                if thread_id:
                    # Add user message
                    import uuid
                    user_msg_id = str(uuid.uuid4())
                    fs.append_chat_message(uid, thread_id, {
                        "message_id": user_msg_id,
                        "role": "user",
                        "content": user_msg,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

                    # Add assistant message if response exists
                    if assistant_msg:
                        assistant_msg_id = str(uuid.uuid4())
                        fs.append_chat_message(uid, thread_id, {
                            "message_id": assistant_msg_id,
                            "role": "assistant",
                            "content": assistant_msg,
                            "timestamp": datetime.utcnow().isoformat(),
                            "run_id": run_id,
                        })

            # 4. Record the agent run and audit trail
            t1_resp = state.get("tier1_response") or {}
            t2_resp = state.get("tier2_response") or {}

            run_data = {
                "run_id": run_id,
                "request_type": request_type,
                "event_id": state.get("event_id"),
                "thread_id": state.get("thread_id"),
                "model_tier1": t1_resp.get("model_id"),
                "model_tier2": t2_resp.get("model_id"),
                "tier1_tokens": t1_resp.get("tokens_used", 0),
                "tier2_tokens": t2_resp.get("tokens_used", 0),
                "tier1_latency_ms": t1_resp.get("latency_ms", 0.0),
                "tier2_latency_ms": t2_resp.get("latency_ms", 0.0),
                "tool_calls": state.get("tool_calls", []),
                "status": "completed" if not state.get("error") else "error",
                "error": state.get("error"),
                "audit_trail": state.get("audit_entries", []),
            }
            fs.record_agent_run(uid, run_id, run_data)
            fs.complete_agent_run(uid, run_id, run_data)

            return {"error": None}

        except Exception as e:
            logger.error("Failed to persist state to Firestore: %s", e)
            return {"error": f"Persistence failure: {str(e)}"}


# Callable instance for graph composition
persist = PersistNode()
