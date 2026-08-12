"""
JarvisState — typed state for the LangGraph workflow.

Each request runs a fresh graph invocation.  The state carries all
context from ingestion through to the final response.
"""

from __future__ import annotations

from typing import Any, TypedDict


class JarvisState(TypedDict, total=False):
    """
    Typed state passed through every LangGraph node.

    Fields are populated progressively as the graph executes:
    1. ``verify`` sets uid, run_id, request_type, and the raw request
    2. ``load_context`` populates session, tasks, reminders, messages, preferences
    3. ``session_reducer`` / ``tier1_resolve`` update session and tier1_*
    4. ``tier2_orchestrate`` fills tier2_*, tool_calls
    5. ``validate_and_execute`` sets tool_results
    6. ``persist`` writes everything to Firestore
    """

    # ── Identity & routing ───────────────────────────────────────────────
    uid: str
    run_id: str
    request_type: str                      # "CONTEXT_EVENT" | "USER_COMMAND"

    # ── Raw request ──────────────────────────────────────────────────────
    event_id: str
    thread_id: str
    raw_request: dict[str, Any]

    # ── Context packet (normalised from the request) ─────────────────────
    context_packet: dict[str, Any]

    # ── Firestore-loaded context ─────────────────────────────────────────
    session: dict[str, Any] | None
    tasks: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    preferences: list[dict[str, Any]]

    # ── Conflict detection ───────────────────────────────────────────────
    conflicts: list[str]
    needs_tier1: bool

    # ── Tier 1 output ────────────────────────────────────────────────────
    tier1_invoked: bool
    tier1_response: dict[str, Any] | None

    # ── Tier 2 output ────────────────────────────────────────────────────
    tier2_invoked: bool
    tier2_response: dict[str, Any] | None
    user_command: str

    # ── Tool execution ───────────────────────────────────────────────────
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]

    # ── Response ─────────────────────────────────────────────────────────
    user_response: str
    changed_records: list[str]
    session_id: str | None
    error: str | None
