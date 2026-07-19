"""
Verify node — validate the incoming request and set identity fields.

Class-based node implementation for the LangGraph workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..state import JarvisState


class VerifyNode:
    """Class-based node handler to validate request schema and set run metadata."""

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

        return {
            "run_id": run_id,
            "event_id": event_id,
            "thread_id": raw.get("thread_id", "") if request_type == "USER_COMMAND" else state.get("thread_id", ""),
            "context_packet": context_packet,
            "error": None,
        }


# Callable instance for graph composition
verify = VerifyNode()
