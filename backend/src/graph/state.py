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
       preferences, and semantic contexts from local DB / RecordStore.
    3. Conditional Execution Branch:
       - USER_COMMAND: ``intent_router`` -> ``agent`` <-> ``agent_tools`` -> ``persist``
       - CONTEXT_EVENT: ``context_gate`` -> (optional shared ``agent`` <-> ``agent_tools``)
         -> ``session_reducer`` -> ``semantic_context`` -> ``persist``
    4. ``persist``: commits updated sessions, chat messages, reminders, audit entries,
       and semantic memory to local SQLite and RecordStore.
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

    # ── RecordStore-loaded context ─────────────────────────────────────────
    session: dict[str, Any] | None
    tasks: list[dict[str, Any]]
    reminders: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    preferences: list[dict[str, Any]]
    semantic_contexts: list[dict[str, Any]]
    semantic_context_changes: list[str]
    context_memory: list[dict[str, Any]]
    cloud_context_loaded: bool
    context_scope: str  # user commands fetch personal context only through selected tools
    context_history: dict[str, Any] | None

    # ── Context assessment ─────────────────────────────────────────────
    conflicts: list[str]
    needs_context_assessment: bool
    context_assessment_invoked: bool
    context_assessment: dict[str, Any] | None

    # ── Shared invocation scratch state ─────────────────────────────────
    agent_invoked: bool
    user_command: str
    is_greeting: bool
    agent_messages: list[Any]
    agent_step_count: int
    agent_model_call_count: int
    agent_started_at: float
    agent_tool_count: int

    # ── Tool execution ───────────────────────────────────────────────────
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    terminal_tool_error: str

    # ── Response ─────────────────────────────────────────────────────────
    needs_user_input: bool
    user_response: str
    changed_records: list[str]
    session_id: str | None
    error: str | None
    intent: str | None
    resolved_place: str | None
