"""
Tests for LangGraph Builder, state compilation, and conditional routing.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from src.graph.builder import (
    build_workflow,
    route_intent,
    route_request_type,
    route_tier1_agent_loop,
    route_tier1_needed,
    route_tier2_agent_loop,
)
from src.graph.state import JarvisState


def test_build_workflow_compilation():
    app = build_workflow()
    assert app is not None


def test_routing_request_type():
    assert route_request_type({"request_type": "USER_COMMAND"}) == "intent_router"
    assert route_request_type({"request_type": "CONTEXT_EVENT"}) == "context_gate"


def test_routing_intent():
    assert route_intent({"is_greeting": True}) == "persist"
    assert route_intent({"is_greeting": False}) == "tier2_agent"


def test_routing_tier2_agent_loop():
    # Final answer (no tool calls)
    msg_final = AIMessage(content="You have 2 reminders.")
    state_final: JarvisState = {"agent_messages": [msg_final], "agent_step_count": 1}
    assert route_tier2_agent_loop(state_final) == "persist"

    # Tool call needed
    msg_tool = AIMessage(
        content="",
        tool_calls=[{"name": "list_reminders", "args": {}, "id": "call_1", "type": "tool_call"}],
    )
    state_tool: JarvisState = {"agent_messages": [msg_tool], "agent_step_count": 1}
    assert route_tier2_agent_loop(state_tool) == "tier2_tools"

    # Step limit reached
    state_overflow: JarvisState = {"agent_messages": [msg_tool], "agent_step_count": 50}
    assert route_tier2_agent_loop(state_overflow) == "persist"


def test_routing_tier1_agent_loop():
    msg_final = AIMessage(content="riding:hunter350 confidence:0.92")
    state_final: JarvisState = {"tier1_messages": [msg_final], "tier1_step_count": 1}
    assert route_tier1_agent_loop(state_final) == "session_reducer"

    msg_tool = AIMessage(
        content="",
        tool_calls=[{"name": "match_vibration_signature", "args": {}, "id": "call_1", "type": "tool_call"}],
    )
    state_tool: JarvisState = {"tier1_messages": [msg_tool], "tier1_step_count": 1}
    assert route_tier1_agent_loop(state_tool) == "tier1_tools"


def test_fast_greeting_workflow_execution():
    app = build_workflow()
    initial_state = {
        "uid": "user-test",
        "request_type": "USER_COMMAND",
        "raw_request": {"text": "hello jarvis"},
    }
    result = app.invoke(initial_state)
    assert result.get("is_greeting") is True
    assert "Jarvis here" in result.get("user_response", "")
