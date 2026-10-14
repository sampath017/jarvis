"""
Tests for Tier 1 Agent and Tools.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.cloud.tier1_agent_tools import build_tier1_tools
from src.graph.nodes.tier1_agent import Tier1AgentNode
from src.graph.nodes.tier1_tools_node import Tier1ToolsNode
from src.models.enums import Tier1Action, VehicleClass
from src.services.database import DatabaseService


@pytest.fixture
def db(tmp_path):
    return DatabaseService(db_path=str(tmp_path / "test.db"))


def test_tier1_tools_vibration_match(db):
    tools = {t.name: t for t in build_tier1_tools(db, uid="user-123")}

    # Hunter 350 harmonic test
    match_tool = tools["match_vibration_signature"]
    res = match_tool.invoke({
        "dominant_frequency_hz": 32.5,
        "rms_energy": 1.2,
        "spectral_entropy": 0.45,
    })
    assert "Royal Enfield Hunter 350" in res
    assert "0.92" in res or "Confidence" in res

    # Car/bus signature test
    res_car = match_tool.invoke({
        "dominant_frequency_hz": 12.0,
        "rms_energy": 0.2,
        "spectral_entropy": 0.1,
    })
    assert "Enclosed vehicle" in res_car


def test_tier1_tools_geofences(db):
    db.create_place("user-123", {
        "name": "Home",
        "category": "home",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "radius_m": 200.0,
    })

    tools = {t.name: t for t in build_tier1_tools(db, uid="user-123")}
    geofence_tool = tools["check_saved_geofences"]

    # Inside geofence
    res = geofence_tool.invoke({"lat": 12.9716, "lon": 77.5946})
    assert "INSIDE GEOFENCE: 'Home'" in res

    # Outside geofence
    res_out = geofence_tool.invoke({"lat": 13.5000, "lon": 78.0000})
    assert "not currently within any saved user geofence" in res_out


def test_tier1_agent_parse_structured_output(db):
    node = Tier1AgentNode(db=db)

    # Riding signal
    res1 = node._parse_structured_output("riding:hunter350 near:place_id=X4F2 confidence:0.92")
    assert res1.resolved_vehicle == VehicleClass.HUNTER_350
    assert res1.recommended_action == Tier1Action.ACCEPT
    assert res1.confidence == 0.92

    # Geofence signal
    res2 = node._parse_structured_output("at_geofence:home confidence:0.95")
    assert res2.resolved_place == "home"
    assert res2.recommended_action == Tier1Action.ACCEPT

    # Uncertain signal
    res3 = node._parse_structured_output("context:uncertain reason:conflicting IMU and GPS confidence:0.35")
    assert res3.recommended_action == Tier1Action.REJECT
    assert res3.confidence == 0.35


def test_tier1_tools_node_execution(db):
    tools_node = Tier1ToolsNode(db=db)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "match_vibration_signature",
            "args": {"dominant_frequency_hz": 30.0, "rms_energy": 1.5, "spectral_entropy": 0.5},
            "id": "call_123",
            "type": "tool_call",
        }],
    )

    state = {
        "uid": "user-123",
        "event_id": "evt-1",
        "tier1_messages": [ai_msg],
    }

    result = tools_node(state)
    messages = result.get("tier1_messages", [])
    assert len(messages) == 2
    tool_msg = messages[-1]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_123"
    assert "Hunter 350" in tool_msg.content
