"""
Verify node — validate the incoming request and set identity fields.

Class-based node implementation for the LangGraph workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..state import JarvisState
from ...backend.audit_log import audit_from_state
from ...services.database import DatabaseService


class VerifyNode:
    """Class-based node handler to validate request schema and set run metadata."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db

    def __call__(self, state: JarvisState) -> dict:
        """Validate the incoming request schema and set run metadata."""
        run_id = state.get("run_id") or str(uuid.uuid4())
        request_type = state.get("request_type", "")
        raw = state.get("raw_request", {})

        # Build a normalised context packet from the raw request
        if request_type == "CONTEXT_EVENT":
            event_id = raw.get("event_id", str(uuid.uuid4()))
            context_packet = {
                "event_id": event_id,
                "timestamp": raw.get("occurred_at", datetime.utcnow().isoformat()),
                "activity": raw.get("activity", "UNKNOWN"),
                "transition": raw.get("transition", "ENTER"),
                "gps": raw.get("location"),
                "feature_summary": raw.get("feature_summary"),
                "classification_confidence": (
                    raw.get("feature_summary", {}) or {}
                ).get("classification_confidence", 0.0),
                "vehicle_class_hint": (
                    raw.get("feature_summary", {}) or {}
                ).get("vehicle_class_hint", ""),
                "session_id": raw.get("session_hint"),
            }
        else:
            # USER_COMMAND — minimal context packet
            event_id = raw.get("request_id", str(uuid.uuid4()))
            context_packet = {
                "event_id": event_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

        result = {
            "run_id": run_id,
            "event_id": event_id,
            "thread_id": raw.get("thread_id", "") if request_type == "USER_COMMAND" else state.get("thread_id", ""),
            "context_packet": context_packet,
            "error": None,
        }

        # Audit: log the verified request
        # Build a temporary state with run_id set so audit_from_state can use it
        audit_state = {**state, "run_id": run_id}
        audit = audit_from_state(audit_state, self.db)

        gps_data = raw.get("location") or {}
        audit.log(
            node_name="verify",
            action="request_validated",
            category="API",
            event_id=event_id,
            input_summary={
                "request_type": request_type,
                "event_id": event_id,
                "has_gps": bool(raw.get("location")),
                "has_feature_summary": bool(raw.get("feature_summary")),
                "activity": raw.get("activity", ""),
                "user_command": raw.get("text", ""),
            },
            output_summary={
                "run_id": run_id,
                "request_type": request_type,
            },
            gps_lat=gps_data.get("latitude") if gps_data else None,
            gps_lon=gps_data.get("longitude") if gps_data else None,
        )

        return result


# Callable instance for graph composition
verify = VerifyNode()
