import pytest
from src.models.schemas import CommandRequest
from src.graph.nodes.tier2_agent import Tier2AgentNode, reverse_geocode_location
from src.services.database import DatabaseService


def test_command_request_gps_fields():
    req = CommandRequest(
        text="where am I?",
        latitude=17.4401,
        longitude=78.3489,
    )
    assert req.latitude == 17.4401
    assert req.longitude == 78.3489


def test_tier2_agent_prompt_includes_gps_and_saved_places():
    db = DatabaseService()
    uid = "test_user_loc"
    db.create_place(uid, {
        "name": "Work Campus",
        "category": "work",
        "latitude": 17.4400,
        "longitude": 78.3488,
        "radius_m": 200.0,
    })

    node = Tier2AgentNode(db=db)
    state = {
        "uid": uid,
        "raw_request": {
            "text": "what is my current location",
            "latitude": 17.4401,
            "longitude": 78.3489,
        },
        "context_packet": {
            "gps": {
                "latitude": 17.4401,
                "longitude": 78.3489,
            }
        },
    }

    prompt = node._build_user_prompt(state)
    assert "[Internal GPS Reference:" in prompt
    assert "Work Campus" in prompt
    assert "Immediate Landmarks (Google Places):" in prompt
