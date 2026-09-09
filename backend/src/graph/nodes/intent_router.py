"""
Intent Router node — prepare user command context.

Class-based node implementation for routing natural language commands.
"""

from __future__ import annotations

import logging
from ..state import JarvisState
from ...backend.audit_log import audit_from_state
from ...services.database import DatabaseService

logger = logging.getLogger(__name__)


class IntentRouterNode:
    """Class-based node handler to validate and route user command text."""

    def __init__(self, db: DatabaseService | None = None) -> None:
        self.db = db

    def __call__(self, state: JarvisState) -> dict:
        """Route user command and ensure it has proper text and routing keys."""
        raw = state.get("raw_request", {})
        command_text = raw.get("text", "").strip()
        audit = audit_from_state(state, self.db)

        if not command_text:
            audit.log(
                node_name="intent_router",
                action="empty_command",
                category="API",
                event_id=state.get("event_id", ""),
                execution_result="error",
                error_detail="Empty user command received",
            )
            return {
                "error": "Empty user command received",
                "tier2_invoked": False,
            }

        # Extract thread ID
        thread_id = raw.get("thread_id", "")

        # Fast heuristic check for simple greetings / pleasantries (<10ms)
        import re
        cleaned = re.sub(r"[^\w\s]", "", command_text.lower()).strip()
        cleaned_no_jarvis = re.sub(r"\bjarvis\b", "", cleaned).strip()
        GREETINGS = {
            "hi", "hello", "hey", "hiya", "howdy", "sup", "yo",
            "good morning", "good afternoon", "good evening", "namaste",
            "who are you", "what can you do", "help",
        }
        if cleaned in GREETINGS or cleaned_no_jarvis in GREETINGS:
            logger.info("Fast-path greeting matched: '%s'", cleaned)
            return {
                "user_command": command_text,
                "thread_id": thread_id,
                "user_response": "Hello! Jarvis here. How can I help you today?",
                "is_greeting": True,
                "tier2_invoked": False,
            }

        return {
            "user_command": command_text,
            "thread_id": thread_id,
            "is_greeting": False,
            "tier2_invoked": True,
        }


# Callable instance for graph composition
intent_router = IntentRouterNode()
