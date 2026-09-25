"""
Comprehensive tests for Tier 2 Agent Reminder Consolidation.

Validates:
1. Auto-consolidation during create_reminder (matching errand/task).
2. Multi-activity merging (WALKING + bike -> IN_VEHICLE, WALKING).
3. Location ambiguity resolution (saved place alias/name resolution to GPS coordinates).
4. Explicit consolidate_reminders tool (targeted criteria vs cluster-all).
5. Edge cases: empty/whitespace due_at, relative time expressions, sibling duplicate cleanup.
6. Tier 2 system prompt rules: verification of Rule 12 and Rule 13, and active reminder injection.
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.services.database import DatabaseService
from src.cloud.tier2_agent_tools import (
    build_tier2_tools,
    _normalize_activity_string,
    _are_matching_errands,
    _resolve_location_and_coords,
    normalize_due_at,
)
from src.graph.nodes.tier2_agent import SYSTEM_PROMPT_TIER2, Tier2AgentNode


@pytest.fixture
def temp_db(tmp_path: Path) -> DatabaseService:
    db_file = str(tmp_path / "test_jarvis.db")
    return DatabaseService(db_path=db_file)


def test_normalize_activity_string_edge_cases():
    """Verify normalization of various multi-activity and colloquial travel strings."""
    # Colloquial bike and walk
    assert _normalize_activity_string("walking or on my bike") == "IN_VEHICLE, WALKING"
    assert _normalize_activity_string("riding, walking") == "IN_VEHICLE, WALKING"
    assert _normalize_activity_string("motorcycle / running") == "IN_VEHICLE, RUNNING"
    assert _normalize_activity_string("bicycle and walk") == "ON_BICYCLE, WALKING"
    # Exact standard enum tokens
    assert _normalize_activity_string("WALKING, IN_VEHICLE") == "IN_VEHICLE, WALKING"
    assert _normalize_activity_string("IN_VEHICLE, WALKING") == "IN_VEHICLE, WALKING"
    # Empty / None
    assert _normalize_activity_string("") == ""
    assert _normalize_activity_string(None) == ""


def test_are_matching_errands_fuzzy():
    """Verify errand matching logic across phrasings, stop words, and locations."""
    # Walking in flat vs bike in flat
    assert _are_matching_errands(
        "remind me when walking in my flat", "flat",
        "bike in flat", "flat"
    )
    # Milk errand with different words
    assert _are_matching_errands(
        "buy milk", None,
        "get fresh milk when riding bike", None
    )
    # Different errands should NOT match
    assert not _are_matching_errands(
        "buy milk", "supermarket",
        "oil change at service center", "service center"
    )
    # Single core keyword match when one title is short
    assert _are_matching_errands(
        "groceries", None,
        "buy weekly groceries", None
    )


def test_location_ambiguity_saved_places_resolution(temp_db: DatabaseService):
    """Verify that ambiguous location names resolve to saved places and populate coordinates."""
    uid = "test_user_loc"
    # Create saved place "My Flat Valencia" with alias "Home"
    temp_db.create_place(uid, {
        "name": "My Flat Valencia",
        "user_label": "Home",
        "alias": "Home",
        "latitude": 17.4485,
        "longitude": 78.3842,
    })

    # Exact alias match
    name, lat, lon = _resolve_location_and_coords(temp_db, uid, "Home")
    assert name == "My Flat Valencia"
    assert lat == 17.4485
    assert lon == 78.3842

    # Substring / partial match on "flat"
    name2, lat2, lon2 = _resolve_location_and_coords(temp_db, uid, "flat")
    assert name2 == "My Flat Valencia"
    assert lat2 == 17.4485
    assert lon2 == 78.3842

    # Location not in saved places keeps user's location name without coordinates
    name3, lat3, lon3 = _resolve_location_and_coords(temp_db, uid, "Unknown Mall")
    assert name3 == "Unknown Mall"
    assert lat3 is None
    assert lon3 is None


def test_create_reminder_auto_consolidation(temp_db: DatabaseService):
    """Verify that creating a second reminder with overlapping errand auto-consolidates into 1 record."""
    uid = "test_user_auto"
    temp_db.create_place(uid, {
        "name": "My Flat Valencia",
        "user_label": "Home",
        "alias": "Home",
        "latitude": 17.4485,
        "longitude": 78.3842,
    })

    tools = {t.name: t for t in build_tier2_tools(temp_db, uid)}
    create_tool = tools["create_reminder"]

    # 1. Create first reminder: "Walking in my flat"
    res1 = create_tool.invoke({
        "confirmed": True,
        "title": "Walking in my flat",
        "location_name": "flat",
        "activity": "WALKING",
    })
    assert "Successfully created reminder" in res1
    rems = temp_db.list_reminders(uid, status="ACTIVE")
    assert len(rems) == 1
    assert rems[0]["activity"] == "WALKING"
    assert rems[0]["latitude"] == 17.4485

    # 2. Create second reminder for same errand on bike
    res2 = create_tool.invoke({
        "confirmed": True,
        "title": "Bike in flat",
        "location_name": "flat",
        "activity": "bike",
    })
    assert "Consolidated into a single intelligent reminder" in res2

    # Check that only 1 reminder exists in the database
    active_rems = temp_db.list_reminders(uid, status="ACTIVE")
    assert len(active_rems) == 1
    consolidated = active_rems[0]
    # Activities should be merged
    assert consolidated["activity"] == "IN_VEHICLE, WALKING"
    # Location and coordinates should be preserved
    assert consolidated["location_name"] == "My Flat Valencia"
    assert consolidated["latitude"] == 17.4485


def test_consolidate_reminders_tool_with_criteria(temp_db: DatabaseService):
    """Verify the explicit consolidate_reminders tool with a specific criteria filter."""
    uid = "test_user_tool"
    # Seed 2 duplicate grocery reminders with different modes
    temp_db.create_reminder(uid, {
        "title": "Buy groceries when walking",
        "activity": "WALKING",
        "status": "ACTIVE",
    })
    temp_db.create_reminder(uid, {
        "title": "Groceries on bike",
        "activity": "IN_VEHICLE",
        "due_at": "2026-10-15T09:00:00Z",
        "status": "ACTIVE",
    })
    # Unrelated reminder
    temp_db.create_reminder(uid, {
        "title": "Dentist appointment",
        "status": "ACTIVE",
    })

    assert len(temp_db.list_reminders(uid, status="ACTIVE")) == 3

    tools = {t.name: t for t in build_tier2_tools(temp_db, uid)}
    cons_tool = tools["consolidate_reminders"]

    res = cons_tool.invoke({"criteria": "groceries"})
    assert "Successfully digested and consolidated reminders" in res

    active_rems = temp_db.list_reminders(uid, status="ACTIVE")
    # 2 grocery reminders merged into 1, dentist remains -> total 2
    assert len(active_rems) == 2
    grocery_rem = next(r for r in active_rems if "groceries" in r["title"].lower())
    assert grocery_rem["activity"] == "IN_VEHICLE, WALKING"
    assert grocery_rem["due_at"] == "2026-10-15T09:00:00Z"


def test_consolidate_reminders_tool_all_clusters(temp_db: DatabaseService):
    """Verify consolidate_reminders(criteria='all') clusters multiple distinct duplicate sets."""
    uid = "test_user_all"
    # Set 1: Fueling
    temp_db.create_reminder(uid, {"title": "Refuel bike", "activity": "IN_VEHICLE", "status": "ACTIVE"})
    temp_db.create_reminder(uid, {"title": "Refuel Royal Enfield", "activity": "IN_VEHICLE", "status": "ACTIVE"})

    # Set 2: Flat walking
    temp_db.create_reminder(uid, {"title": "Walk in flat", "activity": "WALKING", "location_name": "Flat", "status": "ACTIVE"})
    temp_db.create_reminder(uid, {"title": "Flat walking", "activity": "WALKING", "location_name": "Flat", "status": "ACTIVE"})

    # Set 3: Unique reminder
    temp_db.create_reminder(uid, {"title": "Doctor visit", "status": "ACTIVE"})

    assert len(temp_db.list_reminders(uid, status="ACTIVE")) == 5

    tools = {t.name: t for t in build_tier2_tools(temp_db, uid)}
    cons_tool = tools["consolidate_reminders"]

    res = cons_tool.invoke({"criteria": "all"})
    assert "Successfully digested and consolidated" in res

    remaining = temp_db.list_reminders(uid, status="ACTIVE")
    # 2 refuel -> 1, 2 flat -> 1, 1 doctor -> 1 = total 3
    assert len(remaining) == 3


def test_due_at_normalization_and_coercion():
    """Verify time normalization and coercion of empty/whitespace due_at."""
    # Empty string or whitespace
    assert normalize_due_at("") == ""
    assert normalize_due_at("   ") == ""
    assert normalize_due_at(None) == ""

    # Relative time string
    rel_due = normalize_due_at("in 29 seconds")
    assert rel_due != ""
    assert "T" in rel_due

    # Valid ISO string
    iso = "2026-09-12T14:00:00Z"
    assert normalize_due_at(iso) == "2026-09-12T14:00:00+00:00"


def test_update_reminder_tool(temp_db: DatabaseService):
    """Verify the update_reminder tool modifies activity, location, and due_at cleanly."""
    uid = "test_user_upd"
    temp_db.create_place(uid, {
        "name": "My Flat Valencia",
        "user_label": "Home",
        "alias": "Home",
        "latitude": 17.4485,
        "longitude": 78.3842,
    })
    created = temp_db.create_reminder(uid, {
        "title": "Gym workout",
        "activity": "WALKING",
        "status": "ACTIVE",
    })
    rem_id = created["id"]

    tools = {t.name: t for t in build_tier2_tools(temp_db, uid)}
    upd_tool = tools["update_reminder"]

    res = upd_tool.invoke({
        "confirmed": True,
        "reminder_id": rem_id,
        "activity": "walking or bike",
        "location_name": "flat",
        "status": "ACTIVE",
    })
    assert "Successfully updated reminder" in res

    updated = temp_db.get_reminder(uid, rem_id)
    assert updated is not None
    assert updated["activity"] == "IN_VEHICLE, WALKING"
    assert updated["location_name"] == "My Flat Valencia"
    assert updated["latitude"] == 17.4485


def test_tier2_prompt_rules_and_active_reminders_injection(temp_db: DatabaseService):
    """Verify that SYSTEM_PROMPT_TIER2 retains both Rule 12 & Rule 13, and prompt includes active reminders."""
    # 1. Rule verification
    assert "12. Structured Output Delivery:" in SYSTEM_PROMPT_TIER2
    assert "respond_to_user" in SYSTEM_PROMPT_TIER2
    assert "13. Reminder Consolidation & Single Intelligent Reminder:" in SYSTEM_PROMPT_TIER2
    assert "DO NOT create multiple separate reminders" in SYSTEM_PROMPT_TIER2

    # 2. Injection verification
    uid = "test_user_prompt"
    temp_db.create_reminder(uid, {
        "title": "Walking in my flat",
        "location_name": "Flat",
        "activity": "WALKING",
        "status": "ACTIVE",
    })
    node = Tier2AgentNode(db=temp_db)
    state = {
        "uid": uid,
        "user_command": "remind me to ride bike in flat",
        "event_id": "test_evt_1",
    }
    prompt = node._build_user_prompt(state)
    assert "Existing Active Reminders:" in prompt
    assert "Walking in my flat" in prompt
    assert "WALKING" in prompt
