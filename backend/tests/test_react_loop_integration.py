"""
Integration tests for true LangGraph ReAct multi-turn agent loops (Tier 1 and Tier 2).
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.graph.builder import build_workflow
from src.services.database import DatabaseService


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "integration_test.db")
    monkeypatch.setenv("JARVIS_LOCAL_DB_PATH", db_file)
    db = DatabaseService(db_path=db_file)
    return db


def test_tier2_react_loop_list_reminders(test_db, monkeypatch):
    """
    Assert: Tier 2 calls list_reminders, receives tool result via ToolMessage,
    and returns a reasoned final response answering the question with the actual reminders.
    """
    uid = "user-react-1"
    test_db.create_reminder(uid, {
        "title": "Check tire pressure",
        "location_name": "Indian Oil",
        "status": "ACTIVE",
    })

    # Mock ChatOpenAI for Tier 2 to simulate multi-turn ReAct responses
    call_count = 0

    def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Turn 1: Agent calls list_reminders tool
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "list_reminders",
                    "args": {"status": "ACTIVE"},
                    "id": "call_rem_list_1",
                    "type": "tool_call",
                }],
            )
        else:
            # Turn 2: Agent observes ToolMessage and formulates reasoned final answer
            assert any(isinstance(m, ToolMessage) and m.tool_call_id == "call_rem_list_1" for m in messages)
            return AIMessage(content="You have 1 active reminder: Check tire pressure at Indian Oil.")

    mock_llm = MagicMock()
    mock_llm.invoke = mock_invoke
    mock_bound = MagicMock()
    mock_bound.invoke = mock_invoke
    mock_llm.bind_tools.return_value = mock_bound

    monkeypatch.setattr("src.graph.nodes.tier2_agent.ChatOpenAI", lambda **kwargs: mock_llm)

    app = build_workflow(db=test_db)
    initial_state = {
        "uid": uid,
        "request_type": "USER_COMMAND",
        "raw_request": {
            "request_id": "req-rem-1",
            "text": "do we have any reminders",
        },
    }

    result = app.invoke(initial_state)

    assert result.get("agent_step_count") == 2
    assert "Check tire pressure" in result.get("user_response", "")
    assert call_count == 2

    # Verify ToolMessage observation exists in state
    messages = result.get("agent_messages", [])
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert "Indian Oil" in tool_msgs[0].content


def test_tier2_react_loop_create_reminder(test_db, monkeypatch):
    """
    Assert: Tier 2 calls create_reminder, receives confirmation, and answers with reminder details.
    """
    uid = "user-react-2"
    call_count = 0

    def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "create_reminder",
                    "args": {
                        "title": "Check tire pressure",
                        "location_name": "Indian Oil",
                        "latitude": 12.0, "longitude": 80.0, "confirmed": True,
                    },
                    "id": "call_create_rem_1",
                    "type": "tool_call",
                }],
            )
        else:
            assert any(isinstance(m, ToolMessage) and m.tool_call_id == "call_create_rem_1" for m in messages)
            return AIMessage(content="I've set a reminder to check tire pressure when you are at Indian Oil.")

    mock_llm = MagicMock()
    mock_llm.invoke = mock_invoke
    mock_bound = MagicMock()
    mock_bound.invoke = mock_invoke
    mock_llm.bind_tools.return_value = mock_bound

    monkeypatch.setattr("src.graph.nodes.tier2_agent.ChatOpenAI", lambda **kwargs: mock_llm)

    app = build_workflow(db=test_db)
    initial_state = {
        "uid": uid,
        "request_type": "USER_COMMAND",
        "raw_request": {
            "request_id": "req-create-1",
            "text": "remind me to check tire pressure at Indian Oil",
        },
    }

    result = app.invoke(initial_state)

    assert result.get("agent_step_count") == 2
    assert "Indian Oil" in result.get("user_response", "")
    assert len(result.get("changed_records", [])) >= 1

    # Verify reminder is persisted in DB
    rems = test_db.list_reminders(uid)
    assert len(rems) == 1
    assert rems[0]["title"] == "Check tire pressure"
    assert rems[0]["location_name"] == "Indian Oil"


def test_tier1_react_loop_ambiguous_vibration(test_db, monkeypatch):
    """
    Assert: Tier 1 calls match_vibration_signature, loops, and emits a structured
    classification for session_reducer.
    """
    uid = "user-react-3"
    call_count = 0

    def mock_invoke_tier1(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "match_vibration_signature",
                    "args": {
                        "dominant_frequency_hz": 32.5,
                        "rms_energy": 1.2,
                        "spectral_entropy": 0.45,
                    },
                    "id": "call_vibe_match_1",
                    "type": "tool_call",
                }],
            )
        else:
            assert any(isinstance(m, ToolMessage) and m.tool_call_id == "call_vibe_match_1" for m in messages)
            return AIMessage(content="riding:hunter350 confidence:0.92")

    mock_llm = MagicMock()
    mock_llm.invoke = mock_invoke_tier1
    mock_bound = MagicMock()
    mock_bound.invoke = mock_invoke_tier1
    mock_llm.bind_tools.return_value = mock_bound

    monkeypatch.setattr("src.graph.nodes.tier1_agent.ChatOpenAI", lambda **kwargs: mock_llm)

    app = build_workflow(db=test_db)
    initial_state = {
        "uid": uid,
        "request_type": "CONTEXT_EVENT",
        "raw_request": {
            "event_id": "evt-vibe-test",
            "activity": "IN_VEHICLE",
            "transition": "ENTER",
            "location": {"latitude": 12.9716, "longitude": 77.5946, "speed_mps": 12.0},
            "feature_summary": {
                "dominant_freq_hz": 32.5,
                "z_rms": 1.2,
                "classification_confidence": 0.50,  # Below threshold -> triggers Tier 1
                "vehicle_class_hint": "UNKNOWN",
            },
        },
    }

    result = app.invoke(initial_state)

    assert result.get("tier1_step_count") == 2
    assert result.get("tier1_invoked") is True

    # Tier 1 response parsed properly
    tier1_res = result.get("tier1_response")
    assert tier1_res is not None
    assert tier1_res["resolved_vehicle"] == "HUNTER_350"
    assert tier1_res["confidence"] == 0.92

    # Session reducer received the signal and activated session
    session = result.get("session")
    assert session is not None
    assert session["status"] == "ACTIVE"
    assert session["vehicle_class"] == "HUNTER_350"
