"""
Local Authentication — default local user for Android app connection.
"""

from __future__ import annotations

# Default local user ID used by the Android app
DEFAULT_UID = "jarvis_local_user"


def get_current_user() -> str:
    """Return the default local user ID."""
    return DEFAULT_UID
