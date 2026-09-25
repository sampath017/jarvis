"""
Test full Tier 2 LangGraph agent workflow with satellite inspection query.
"""

from src.graph.builder import build_workflow
from src.services.database import DatabaseService

def test_agent_with_satellite_query():
    db = DatabaseService()
    uid = "test_user_satellite"
    db.create_place(uid, {
        "id": "creations_valencia_home",
        "name": "Creations Valencia",
        "user_label": "Home",
        "latitude": 12.8450,
        "longitude": 80.2260,
    })

    app = build_workflow(db=db)

    state = {
        "uid": uid,
        "thread_id": "test_satellite_thread",
        "user_command": "can you check the Google maps satellite photo of my flats at Creations Valencia and tell me if I have space to walk and how far is the gate?",
        "request_type": "USER_COMMAND",
        "raw_request": {
            "text": "can you check the Google maps satellite photo of my flats at Creations Valencia and tell me if I have space to walk and how far is the gate?",
        },
        "context_packet": {
            "gps": {"latitude": 12.8450, "longitude": 80.2260},
        },
    }

    result = app.invoke(state)
    response = result.get("user_response", "")
    print("\n=== AGENT RESPONSE ===")
    print(response)
    print("\n=== TOOL CHANGED RECORDS / STEP COUNT ===")
    print("Step count:", result.get("agent_step_count"))
    print("Messages count:", len(result.get("agent_messages", [])))

    assert response, "Agent response should not be empty"
    # Agent should describe the complex / gate / walking space
    assert any(k in response.lower() for k in ("gate", "walk", "road", "block", "complex", "building", "path", "distance"))
    print("\n[PASS] Agent successfully executed satellite visual query!")


if __name__ == "__main__":
    test_agent_with_satellite_query()
