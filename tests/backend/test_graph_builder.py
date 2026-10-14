"""Shared runtime routing and independent request workflows."""

from unittest.mock import Mock

from langchain_core.messages import AIMessage

from src.graph.builder import (
    build_workflow, route_agent_loop, route_context_assessment_needed,
    route_intent, route_request_type,
)


def test_build_workflow_contains_only_one_agent_loop():
    app = build_workflow()
    assert {"agent", "agent_tools"}.issubset(app.nodes)
    assert {"agent", "agent_tools"} == {name for name in app.nodes if name.startswith("agent")}


def test_routing_request_type():
    assert route_request_type({"request_type": "USER_COMMAND"}) == "intent_router"
    assert route_request_type({"request_type": "CONTEXT_EVENT"}) == "context_gate"


def test_routing_intent():
    assert route_intent({"is_greeting": True}) == "agent"
    assert route_intent({"is_greeting": False}) == "agent"


def test_context_requires_model_only_for_ambiguity():
    assert route_context_assessment_needed({"needs_context_assessment": True}) == "agent"
    assert route_context_assessment_needed({"needs_context_assessment": False}) == "session_reducer"


def test_shared_loop_returns_to_each_invocation_workflow():
    final = AIMessage(content="Done")
    tool = AIMessage(content="", tool_calls=[{
        "name": "get_motion_evidence", "args": {}, "id": "call_1", "type": "tool_call",
    }])
    for request_type, destination in (("USER_COMMAND", "persist"), ("CONTEXT_EVENT", "session_reducer")):
        base = {"request_type": request_type, "agent_step_count": 1}
        assert route_agent_loop({**base, "agent_messages": [final]}) == destination
        assert route_agent_loop({**base, "agent_messages": [tool]}) == "agent_tools"
        assert route_agent_loop({**base, "agent_messages": [tool], "agent_step_count": 50}) == destination


def test_greeting_workflow_execution(monkeypatch):
    model = Mock(return_value=AIMessage(content="Hello!"))
    monkeypatch.setattr("src.graph.nodes.agent.AgentNode._invoke_complete", model)
    result = build_workflow().invoke({
        "uid": "user-test", "request_type": "USER_COMMAND",
        "raw_request": {"text": "hello jarvis"},
    })
    assert result.get("agent_invoked") is True
    assert result.get("user_response") == "Hello!"
    model.assert_called_once()


def test_background_final_contract_ends_loop_even_after_tool_budget_failure():
    request = AIMessage(content="", tool_calls=[{
        "name": "get_motion_evidence", "args": {}, "id": "call_1", "type": "tool_call",
    }])
    state = {"request_type": "CONTEXT_EVENT", "agent_messages": [request], "agent_step_count": 1,
             "context_assessment": {"recommended_action": "REJECT"}}
    assert route_agent_loop(state) == "session_reducer"
    assert route_agent_loop({**state, "context_assessment": None, "agent_step_count": 4}) == "session_reducer"
