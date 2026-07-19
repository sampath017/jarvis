"""
Intent Router node — prepare user command context.

Class-based node implementation for routing natural language commands.
"""

from __future__ import annotations

import logging
from ..state import JarvisState

logger = logging.getLogger(__name__)


class IntentRouterNode:
    """Class-based node handler to validate and route user command text."""

    def __call__(self, state: JarvisState) -> dict:
        """Route user command and ensure it has proper text and routing keys."""
        raw = state.get("raw_request", {})
        command_text = raw.get("text", "").strip()

        if not command_text:
            return {
                "error": "Empty user command received",
                "tier2_invoked": False,
            }

        # Extract thread ID
        thread_id = raw.get("thread_id", "")

        logger.info("Routing user command: thread_id=%s command=%s", thread_id, command_text[:50])

        return {
            "user_command": command_text,
            "thread_id": thread_id,
            "tier2_invoked": True,
        }


# Callable instance for graph composition
intent_router = IntentRouterNode()
