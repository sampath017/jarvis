"""
Tests for Tier 2 ReAct Agent and Tools.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.cloud.tier2_agent_tools import build_tier2_tools
from src.graph.nodes.tier2_agent import Tier2AgentNode
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


@pytest.fixture
def db(tmp_path):
    return DatabaseService(db_path=str(tmp_path / "test.db"))


def test_tier2_crud_tools_reminders(db):
    tools = {t.name: t for t in build_tier2_tools(db, uid="user-456")}

    # Create
    create_res = tools["create_reminder"].invoke({
        "title": "Check tire pressure",
        "location_name": "Indian Oil",
    })
    assert "Successfully created reminder" in create_res
    assert "Check tire pressure" in create_res

    # List
    list_res = tools["list_reminders"].invoke({"status": "ACTIVE"})
    assert "Check tire pressure" in list_res
    assert "Indian Oil" in list_res

    # Search
    search_res = tools["search_reminders"].invoke({"query": "tire"})
    assert "Check tire pressure" in search_res

    # Delete
    del_res = tools["delete_reminder"].invoke({"reminder_id": "Check tire pressure"})
    assert "Successfully deleted reminder" in del_res


def test_tier2_crud_tools_notes(db):
    tools = {t.name: t for t in build_tier2_tools(db, uid="user-456")}

    # Create note
    n_res = tools["create_note"].invoke({"text": "Odometer 4250 km", "place": "Garage"})
    assert "Successfully created note" in n_res

    # Search note
    search_res = tools["search_notes"].invoke({"query": "Odometer"})
    assert "Odometer 4250 km" in search_res

    # List notes
    list_res = tools["list_notes"].invoke({"limit": 5})
    assert "Odometer 4250 km" in list_res


def test_tier2_crud_tools_tasks(db):
    tools = {t.name: t for t in build_tier2_tools(db, uid="user-456")}

    # Create task
    t_res = tools["create_task"].invoke({"title": "Lube drive chain", "priority": "HIGH"})
    assert "Successfully created task" in t_res

    # List tasks
    list_res = tools["list_tasks"].invoke({})
    assert "Lube drive chain" in list_res
    assert "HIGH" in list_res


def test_tier2_tools_node_execution(db):
    tools_node = Tier2ToolsNode(db=db)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "create_reminder",
            "args": {"title": "Pick up helmet visor", "location_name": "Store"},
            "id": "call_rem_1",
            "type": "tool_call",
        }],
    )

    state = {
        "uid": "user-456",
        "event_id": "evt-2",
        "agent_messages": [ai_msg],
        "changed_records": [],
    }

    result = tools_node(state)
    agent_msgs = result.get("agent_messages", [])
    assert len(agent_msgs) == 2
    tool_msg = agent_msgs[-1]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_rem_1"
    assert "Successfully created reminder" in tool_msg.content
    assert len(result.get("changed_records", [])) > 0


def test_tier2_agent_multi_turn_history_injection(tmp_path):
    from unittest.mock import MagicMock, patch
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from src.graph.nodes.tier2_agent import Tier2AgentNode

    db = DatabaseService(tmp_path / "test_multi_turn.db")
    node = Tier2AgentNode(db=db)

    captured_messages = []
    def mock_invoke(messages):
        captured_messages.extend(messages)
        return AIMessage(content="I recall your earlier request.")

    mock_llm_tools = MagicMock()
    mock_llm_tools.invoke.side_effect = mock_invoke

    state = {
        "uid": "user-789",
        "user_command": "What did I ask before?",
        "raw_request": {
            "text": "What did I ask before?",
            "thread_id": "thread-123",
            "history": [
                {"role": "user", "content": "Set reminder for brake check"},
                {"role": "assistant", "content": "Created reminder for brake check"},
            ],
        },
    }

    with patch.object(ChatOpenAI, "bind_tools", return_value=mock_llm_tools):
        result = node(state)

    assert result["user_response"] == "I recall your earlier request."

    assert len(captured_messages) == 4
    assert isinstance(captured_messages[0], SystemMessage)
    assert isinstance(captured_messages[1], HumanMessage)
    assert captured_messages[1].content == "Set reminder for brake check"
    assert isinstance(captured_messages[2], AIMessage)
    assert captured_messages[2].content == "Created reminder for brake check"
    assert isinstance(captured_messages[3], HumanMessage)
    assert "What did I ask before?" in captured_messages[3].content

