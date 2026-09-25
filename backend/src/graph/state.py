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
    1. ``verify``: validates request schema, generates run_id, and builds context_packet.
    2. ``load_context``: loads active session, reminders, notes, places, chat messages,
       preferences, and semantic contexts from local DB / Firestore.
    3. Conditional Execution Branch:
       - USER_COMMAND: ``intent_router`` -> (fast greeting -> ``persist``) OR
         (``tier2_agent`` <-> ``tier2_tools`` ReAct loop -> ``persist``)
       - CONTEXT_EVENT: ``context_gate`` -> (optional ``tier1_agent`` <-> ``tier1_tools`` loop)
         -> ``session_reducer`` -> ``semantic_context`` -> ``persist``
    4. ``persist``: commits updated sessions, chat messages, reminders, audit entries,
       and semantic memory to local SQLite and Firestore.
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
    reminders: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    preferences: list[dict[str, Any]]
    semantic_contexts: list[dict[str, Any]]
    semantic_context_changes: list[str]
    context_memory: list[dict[str, Any]]

    # ── Conflict detection ───────────────────────────────────────────────
    conflicts: list[str]
    needs_tier1: bool

    # ── Tier 1 agent loop ────────────────────────────────────────────────
    tier1_invoked: bool
    tier1_response: dict[str, Any] | None
    tier1_messages: list[Any]
    tier1_step_count: int

    # ── Tier 2 agent loop ────────────────────────────────────────────────
    tier2_invoked: bool
    tier2_response: dict[str, Any] | None
    user_command: str
    is_greeting: bool
    agent_messages: list[Any]
    agent_step_count: int

    # ── Tool execution ───────────────────────────────────────────────────
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]

    # ── Response ─────────────────────────────────────────────────────────
    user_response: str
    changed_records: list[str]
    session_id: str | None
    error: str | None
    intent: str | None
    resolved_place: str | None
