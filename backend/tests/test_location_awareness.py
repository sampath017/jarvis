"""Comprehensive tests for Location Awareness and Exact Location Accuracy.

Tests:
1. Exact saved place detection (distance <= 40m labeled as CURRENTLY AT).
2. Saved place compound / geofence detection (distance <= radius_m).
3. Building footprint recognition vs distant POIs (distance <= 65m labeled as CURRENT BUILDING / PREMISE).
4. Relative location phrase resolution ("here", "this gate", "out of this gate", "when I leave") to saved places.
5. Extraction of relative location cues from reminder titles when location_name is omitted.
6. Fallback to current GPS when user is at an unsaved location.
7. Substring and token matching for place aliases ("my flat", "office", "home").
8. Location-aware reminder consolidation (merging relative gate reminders with existing errands).
9. get_current_location tool output structure and graceful handling of missing GPS.
10. Prompt injection structure prioritizing exact current location first without misleading distance strings.
"""

import uuid
from unittest.mock import MagicMock, patch
import pytest

from src.cloud.tier2_agent_tools import (
    _resolve_location_and_coords,
    build_tier2_tools,
)
from src.graph.nodes.tier2_agent import (
    SYSTEM_PROMPT_TIER2,
    Tier2AgentNode,
)
from src.services.database import DatabaseService


@pytest.fixture
def db_with_saved_places():
    """Database fixture populated with realistic saved places and GPS state."""
    db = DatabaseService()
    uid = f"test_user_loc_{uuid.uuid4().hex[:8]}"

    # Save user's home (Creations Valencia)
    db.create_place(uid, {
        "id": "place_home_1",
        "name": "Creations Valencia (Home)",
        "user_label": "Home",
        "alias": "Home",
        "category": "home",
        "latitude": 12.83711,
        "longitude": 80.22559,
        "radius_m": 150.0,
    })

    # Save user's office (Siri Campus TCS)
    db.create_place(uid, {
        "id": "place_work_1",
        "name": "Siri Campus TCS",
        "user_label": "Work",
        "alias": "Office",
        "category": "work",
        "latitude": 12.84000,
        "longitude": 80.22000,
        "radius_m": 250.0,
    })

    # Record latest GPS coordinate inside Creations Valencia (~1.1m from centroid)
    db.create_event_idempotent(
        uid=uid,
        event_id=f"evt_gps_{uid}_1",
        data={
            "gps": {
                "latitude": 12.83711,
                "longitude": 80.22558,
                "accuracy_m": 5.0,
            }
        },
    )

    return db, uid


# ── Test 1: Exact Saved Place Proximity in Prompt ─────────────────────────────

def test_saved_place_exact_match_prompt(db_with_saved_places):
    db, uid = db_with_saved_places
    node = Tier2AgentNode(db=db)

    # User is physically inside Creations Valencia (1.1m away)
    state = {
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {
            "gps": {"latitude": 12.83711, "longitude": 80.22558},
            "nearby_pois": [
                {
                    "name": "Creations Valencia",
                    "category": "apartment_building",
                    "distance_m": 51.0,
                },
                {
                    "name": "Indus Anantya Apartments",
                    "category": "apartment_complex",
                    "distance_m": 35.0,
                },
            ],
        },
    }

    prompt = node._build_user_prompt(state)

    # 1. Exact current location must be explicitly stated first
    assert "User Current Location: CURRENTLY AT saved place 'Creations Valencia (Home)' (Home)" in prompt
    # 2. Saved place proximity must note exact location match
    assert "CURRENTLY AT saved place 'Creations Valencia (Home)' (Home, exact location match, ~1m)" in prompt
    # 3. POI within 65m must be marked as CURRENT BUILDING / PREMISE rather than '50m away'
    assert "Creations Valencia (CURRENT BUILDING / PREMISE, apartment building)" in prompt
    assert "Creations Valencia (apartment building, ~51m away)" not in prompt
    # 4. Internal GPS reference is present for internal use
    assert "[Internal GPS Reference: 12.83711, 80.22558" in prompt


# ── Test 2: Saved Place Inside Compound / Geofence ────────────────────────────

def test_saved_place_compound_geofence_prompt(db_with_saved_places):
    db, uid = db_with_saved_places
    node = Tier2AgentNode(db=db)

    # User is in TCS Siri Campus compound (~75m from center, radius is 250m)
    state = {
        "uid": uid,
        "raw_request": {"text": "what is my current location"},
        "context_packet": {
            "gps": {"latitude": 12.84050, "longitude": 80.22050},
        },
    }

    prompt = node._build_user_prompt(state)
    assert "User Current Location: Inside saved place 'Siri Campus TCS' (Work)" in prompt
    assert "At saved place 'Siri Campus TCS' (Work, inside compound/geofence" in prompt


# ── Test 3: Building Footprint POI Recognition ────────────────────────────────

def test_building_footprint_poi_labeling_without_saved_places():
    db = DatabaseService()
    uid = "test_user_no_places"
    node = Tier2AgentNode(db=db)

    # User has no saved places, but is inside an apartment complex
    state = {
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {
            "gps": {"latitude": 12.90000, "longitude": 80.20000},
            "nearby_pois": [
                {
                    "name": "Skyline Heights",
                    "category": "residential_building",
                    "distance_m": 45.0,
                },
                {
                    "name": "Cafe Coffee Day",
                    "category": "cafe",
                    "distance_m": 120.0,
                },
            ],
        },
    }

    prompt = node._build_user_prompt(state)

    # When no saved place matches, falls back to building premise
    assert "User Current Location: Inside/at Skyline Heights (residential building)" in prompt
    assert "Skyline Heights (CURRENT BUILDING / PREMISE, residential building)" in prompt
    # Distant POI is formatted normally
    assert "Cafe Coffee Day (cafe, ~120m away)" in prompt


# ── Test 4: Relative Location Resolution ("this gate", "here") ────────────────

def test_relative_location_resolution_this_gate(db_with_saved_places):
    db, uid = db_with_saved_places

    # User asks relative to "this gate"
    name, lat, lon = _resolve_location_and_coords(db, uid, "out of this gate")
    assert name == "Creations Valencia (Home)"
    assert lat == 12.83711
    assert lon == 80.22559

    # User asks relative to "here"
    name, lat, lon = _resolve_location_and_coords(db, uid, "here")
    assert name == "Creations Valencia (Home)"
    assert lat == 12.83711
    assert lon == 80.22559

    # User asks relative to "this place"
    name, lat, lon = _resolve_location_and_coords(db, uid, "this place")
    assert name == "Creations Valencia (Home)"
    assert lat == 12.83711
    assert lon == 80.22559


# ── Test 5: Relative Location Extracted From Reminder Title ───────────────────

def test_relative_location_extracted_from_title(db_with_saved_places):
    db, uid = db_with_saved_places
    tools = {t.name: t for t in build_tier2_tools(db, uid)}
    create_tool = tools["create_reminder"]

    # User omitted location_name, but title says "when I go out of this gate"
    result = create_tool.invoke({
        "confirmed": True,
        "title": "buy eggs when I go out of this gate",
        "location_name": "",
        "activity": "WALKING",
    })

    assert "created reminder" in result.lower()
    rems = db.list_reminders(uid, status="ACTIVE")
    assert len(rems) == 1
    rem = rems[0]
    assert rem["location_name"] == "Creations Valencia (Home)"
    assert rem["latitude"] == 12.83711
    assert rem["longitude"] == 80.22559


def test_semantic_reminder_requires_confirmed_resolved_place(db_with_saved_places):
    """A guessed dwell policy must never become a locationless automation."""
    db, uid = db_with_saved_places
    tools = {t.name: t for t in build_tier2_tools(db, uid)}
    create_tool = tools["create_reminder"]

    unconfirmed = create_tool.invoke({
        "title": "Drink water",
        "location_name": "Home",
        "context_states": "DWELLING",
    })

    assert "CONFIRMATION_REQUIRED" in unconfirmed
    assert db.list_reminders(uid, status="ACTIVE") == []

    confirmed = create_tool.invoke({
        "title": "Drink water",
        "location_name": "Home",
        "context_states": "DWELLING",
        "confirmed": True,
    })

    assert "created reminder" in confirmed.lower()
    rem = db.list_reminders(uid, status="ACTIVE")[0]
    assert rem["location_name"] == "Creations Valencia (Home)"
    assert rem["latitude"] == 12.83711
    assert rem["longitude"] == 80.22559
    assert rem["activity"] == "DWELLING"


def test_unresolved_place_cannot_create_location_reminder():
    db = DatabaseService()
    uid = f"test_user_unresolved_{uuid.uuid4().hex[:8]}"
    tools = {t.name: t for t in build_tier2_tools(db, uid)}

    result = tools["create_reminder"].invoke({
        "title": "Drink water",
        "location_name": "My desk",
        "activity": "STILL",
        "confirmed": True,
    })

    assert "CONFIRMATION_REQUIRED" in result
    assert db.list_reminders(uid, status="ACTIVE") == []


# ── Test 6: Fallback to Current GPS for Unsaved Location ───────────────────────

def test_relative_location_fallback_to_current_gps():
    db = DatabaseService()
    uid = "test_user_unsaved_location"
    # Set GPS at a location far from any saved places
    db.create_event_idempotent(
        uid=uid,
        event_id="evt_gps_unsaved_1",
        data={"gps": {"latitude": 13.08270, "longitude": 80.27070, "accuracy_m": 10.0}},
    )

    name, lat, lon = _resolve_location_and_coords(db, uid, "here")
    assert name == "Current Location"
    assert lat == 13.08270
    assert lon == 80.27070


# ── Test 7: Substring and Token Matching for Place Names ──────────────────────

def test_location_token_and_alias_matching(db_with_saved_places):
    db, uid = db_with_saved_places

    # "my flat" matches "Creations Valencia (Home)"
    name, lat, lon = _resolve_location_and_coords(db, uid, "my flat")
    assert name == "Creations Valencia (Home)"
    assert lat == 12.83711
    assert lon == 80.22559

    # "office" matches "Siri Campus TCS" (alias Office / category work)
    name, lat, lon = _resolve_location_and_coords(db, uid, "office")
    assert name == "Siri Campus TCS"
    assert lat == 12.84000
    assert lon == 80.22000

    # "valencia" matches "Creations Valencia (Home)"
    name, lat, lon = _resolve_location_and_coords(db, uid, "valencia")
    assert name == "Creations Valencia (Home)"
    assert lat == 12.83711


# ── Test 8: Location-Aware Reminder Consolidation ─────────────────────────────

def test_location_aware_reminder_consolidation(db_with_saved_places):
    db, uid = db_with_saved_places
    tools = {t.name: t for t in build_tier2_tools(db, uid)}
    create_tool = tools["create_reminder"]

    # 1. Existing reminder created with location "Creations Valencia (Home)"
    create_tool.invoke({
        "confirmed": True,
        "title": "buy eggs",
        "location_name": "Creations Valencia (Home)",
        "activity": "WALKING",
    })

    rems_initial = db.list_reminders(uid, status="ACTIVE")
    assert len(rems_initial) == 1

    # 2. User adds reminder with relative phrasing "when go out of this gate"
    result = create_tool.invoke({
        "confirmed": True,
        "title": "get fresh eggs when go out of this gate",
        "location_name": "out of this gate",
        "activity": "IN_VEHICLE",
    })

    # Must consolidate into a single reminder rather than duplicate
    assert "consolidat" in result.lower()
    rems_after = db.list_reminders(uid, status="ACTIVE")
    assert len(rems_after) == 1
    consolidated = rems_after[0]
    assert consolidated["location_name"] == "Creations Valencia (Home)"
    assert consolidated["latitude"] == 12.83711
    assert consolidated["longitude"] == 80.22559
    assert "WALKING" in consolidated["activity"]
    assert "IN_VEHICLE" in consolidated["activity"]


# ── Test 9: get_current_location Tool Output Structure ────────────────────────

def test_get_current_location_tool_output(db_with_saved_places):
    db, uid = db_with_saved_places
    tools = {t.name: t for t in build_tier2_tools(db, uid)}
    loc_tool = tools["get_current_location"]

    # When live GPS is available and inside Creations Valencia
    output = loc_tool.invoke({})
    assert "CURRENTLY AT saved place: 'Creations Valencia (Home)'" in output
    assert "exact location match" in output
    assert "[Internal GPS Reference: 12.83711, 80.22558]" in output

    # When GPS is absent
    db_empty = DatabaseService()
    uid_empty = "test_empty_gps"
    tools_empty = {t.name: t for t in build_tier2_tools(db_empty, uid_empty)}
    output_empty = tools_empty["get_current_location"].invoke({})
    assert "No live GPS coordinates available in the current session." in output_empty


# ── Test 10: SYSTEM_PROMPT_TIER2 Rule 10 Verification ────────────────────────

def test_system_prompt_tier2_location_rules():
    assert "10. Location Awareness, Queries & Landmarks:" in SYSTEM_PROMPT_TIER2
    assert "CURRENT BUILDING / PREMISE" in SYSTEM_PROMPT_TIER2
    assert "Never tell someone their own building is 50m away" in SYSTEM_PROMPT_TIER2
    assert "NEVER output raw latitude/longitude coordinates" in SYSTEM_PROMPT_TIER2
    assert "link the reminder to the user's current saved place or current GPS coordinates" in SYSTEM_PROMPT_TIER2


# ── Test 11: End-to-End Tier 2 Agent Node Execution on "where am I" ────────────

def test_tier2_react_node_execution_where_am_i(db_with_saved_places):
    db, uid = db_with_saved_places
    node = Tier2AgentNode(db=db)

    # Mock the LLM to return a natural structured response using respond_to_user tool
    mock_ai_msg = MagicMock()
    mock_ai_msg.content = ""
    mock_ai_msg.tool_calls = [
        {
            "name": "respond_to_user",
            "args": {
                "message": "You are currently at Home at Creations Valencia in Navallur.",
                "intent": "location_query",
                "resolved_place": "Creations Valencia (Home)",
            },
            "id": "call_respond_1",
        }
    ]

    mock_llm = MagicMock()
    mock_runnable = MagicMock()
    mock_runnable.invoke.return_value = mock_ai_msg
    mock_llm.bind_tools.return_value = mock_runnable
    node.llm = mock_llm

    state = {
        "uid": uid,
        "user_command": "where am I?",
        "raw_request": {"text": "where am I?"},
        "context_packet": {
            "gps": {"latitude": 12.83711, "longitude": 80.22558},
            "nearby_pois": [
                {
                    "name": "Creations Valencia",
                    "category": "apartment_building",
                    "distance_m": 51.0,
                }
            ],
        },
        "agent_step_count": 0,
        "agent_messages": [],
    }

    result = node(state)
    assert result["user_response"] == "You are currently at Home at Creations Valencia in Navallur."
    assert result["intent"] == "location_query"
    assert result["resolved_place"] == "Creations Valencia (Home)"
    assert "50m away" not in result["user_response"]


# ── Test 12: Combined Multi-Activity & Relative Location Reminder ──────────────

def test_multi_activity_and_relative_gate_reminder(db_with_saved_places):
    db, uid = db_with_saved_places
    tools = {t.name: t for t in build_tier2_tools(db, uid)}
    create_tool = tools["create_reminder"]

    result = create_tool.invoke({
        "confirmed": True,
        "title": "check tire pressure",
        "location_name": "this gate",
        "activity": "walking or riding my bike",
    })

    assert "created reminder" in result.lower()
    rems = db.list_reminders(uid, status="ACTIVE")
    assert len(rems) == 1
    rem = rems[0]
    assert rem["location_name"] == "Creations Valencia (Home)"
    assert rem["latitude"] == 12.83711
    assert rem["longitude"] == 80.22559
    assert "IN_VEHICLE" in rem["activity"]
    assert "WALKING" in rem["activity"]


# ── Test 13: Multiple Saved Places Proximity Categorization ───────────────────

def test_multiple_saved_places_proximity_ordering():
    db = DatabaseService()
    uid = f"test_multi_places_{uuid.uuid4().hex[:8]}"

    # 1. Home (at user position ~0m)
    db.create_place(uid, {
        "id": "p_home",
        "name": "My Home Valencia",
        "user_label": "Home",
        "latitude": 12.83710,
        "longitude": 80.22558,
        "radius_m": 100.0,
    })
    # 2. Nearby Gym (300m away)
    db.create_place(uid, {
        "id": "p_gym",
        "name": "Slam Fitness",
        "user_label": "Gym",
        "latitude": 12.83980,
        "longitude": 80.22558,
        "radius_m": 150.0,
    })
    # 3. Distant Office (5km away)
    db.create_place(uid, {
        "id": "p_office",
        "name": "DLF Cybercity",
        "user_label": "Office",
        "latitude": 12.98000,
        "longitude": 80.25000,
        "radius_m": 300.0,
    })

    node = Tier2AgentNode(db=db)
    state = {
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {
            "gps": {"latitude": 12.83710, "longitude": 80.22558},
        },
    }

    prompt = node._build_user_prompt(state)
    assert "User Current Location: CURRENTLY AT saved place 'My Home Valencia' (Home)" in prompt
    assert "CURRENTLY AT saved place 'My Home Valencia' (Home, exact location match, ~0m)" in prompt
    assert "Near saved place 'Slam Fitness' (Gym, ~300m away)" in prompt
    # Distant office (>1500m) should not clutter proximity list
    assert "DLF Cybercity" not in prompt


# ── Test 14: Distance Boundaries for Exact vs Compound vs Distant ─────────────

def test_distance_boundary_categorization():
    from src.backend.session_manager import _haversine_m

    db = DatabaseService()
    uid = f"test_bounds_{uuid.uuid4().hex[:8]}"

    # Fixed base point
    base_lat = 12.80000
    base_lon = 80.20000

    # Saved place with radius 150m
    db.create_place(uid, {
        "id": "p_base",
        "name": "Valencia Compound",
        "user_label": "Home",
        "latitude": base_lat,
        "longitude": base_lon,
        "radius_m": 150.0,
    })

    node = Tier2AgentNode(db=db)

    # 1. Distance <= 40m (e.g. 25m away): must be CURRENTLY AT
    lat_25m = base_lat + (25.0 / 111111.0)
    prompt_exact = node._build_user_prompt({
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {"gps": {"latitude": lat_25m, "longitude": base_lon}},
    })
    assert "CURRENTLY AT saved place 'Valencia Compound'" in prompt_exact
    assert "exact location match" in prompt_exact

    # 2. Distance 80m (inside 150m compound): must be inside compound/geofence
    lat_80m = base_lat + (80.0 / 111111.0)
    prompt_compound = node._build_user_prompt({
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {"gps": {"latitude": lat_80m, "longitude": base_lon}},
    })
    assert "Inside saved place 'Valencia Compound'" in prompt_compound
    assert "inside compound/geofence" in prompt_compound

    # 3. Distance 250m (outside 150m, within 1500m): must be Near saved place
    lat_250m = base_lat + (250.0 / 111111.0)
    prompt_near = node._build_user_prompt({
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {"gps": {"latitude": lat_250m, "longitude": base_lon}},
    })
    assert "Near saved place 'Valencia Compound'" in prompt_near


# ── Test 15: Zero Coordinates Gracefully Ignored ──────────────────────────────

def test_zero_coordinates_ignored():
    db = DatabaseService()
    uid = f"test_zero_gps_{uuid.uuid4().hex[:8]}"
    node = Tier2AgentNode(db=db)

    state = {
        "uid": uid,
        "raw_request": {"text": "where am I"},
        "context_packet": {
            "gps": {"latitude": 0.0, "longitude": 0.0},
        },
    }

    prompt = node._build_user_prompt(state)
    assert "[Internal GPS Reference:" not in prompt
    assert "CURRENTLY AT saved place" not in prompt


# ── Test 16: Location Questions Like "what is near me" ─────────────────────────

def test_location_question_what_is_near_me(db_with_saved_places):
    db, uid = db_with_saved_places
    node = Tier2AgentNode(db=db)

    state = {
        "uid": uid,
        "raw_request": {"text": "what landmarks are near me?"},
        "context_packet": {
            "gps": {"latitude": 12.83711, "longitude": 80.22558},
            "nearby_pois": [
                {
                    "name": "Indian Oil Petrol Bunk",
                    "category": "gas_station",
                    "distance_m": 90.0,
                },
                {
                    "name": "Apollo Pharmacy",
                    "category": "pharmacy",
                    "distance_m": 140.0,
                },
            ],
        },
    }

    prompt = node._build_user_prompt(state)
    assert "User Request: \"what landmarks are near me?\"" in prompt
    assert "Indian Oil Petrol Bunk (gas station, ~90m away)" in prompt
    assert "Apollo Pharmacy (pharmacy, ~140m away)" in prompt
    assert "User Current Location: CURRENTLY AT saved place 'Creations Valencia (Home)' (Home)" in prompt
