"""Context tools share deterministic services and never consume rule state."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.backend.context_automation import ContextAutomationService
from src.cloud.context_tools import BACKGROUND_CONTEXT_TOOL_NAMES, build_context_tools
from src.services.context_evidence import ContextEvidenceService, geofence_result
from src.services.database import DatabaseService


@pytest.fixture
def db(tmp_path):
    return DatabaseService(db_path=tmp_path / "context-tools.db")


def test_missing_vibration_is_uncertain_and_native_features_are_read(db):
    tools = {tool.name: tool for tool in build_context_tools(db, "u")}
    missing = json.loads(tools["match_vibration_signature"].invoke({}))
    assert missing["candidate"] == "UNKNOWN"
    assert missing["verified"] is False
    assert missing["confidence"] == 0
    native = json.loads(tools["match_vibration_signature"].invoke({"features": {"dominant_freq_hz": 32, "z_rms": 1.2}}))
    assert native["candidate"] == "HUNTER_350"
    assert native["verified"] is False
    walking = json.loads(tools["match_vibration_signature"].invoke({"dominant_frequency_hz": 2, "rms_energy": 0.2}))
    assert walking["candidate"] == "NOT_VEHICLE"


def test_geometry_and_rule_evaluation_share_missing_coordinate_behavior(db):
    tools = {tool.name: tool for tool in build_context_tools(db, "u")}
    db.create_place("u", {"name": "Home", "latitude": 0, "longitude": 0, "radius_m": 100})
    assert "uncertain" in tools["check_saved_geofences"].invoke({})
    assert "INSIDE GEOFENCE" in tools["check_saved_geofences"].invoke({"lat": 0, "lon": 0})
    target = {"latitude": 12.5, "longitude": 77.5, "radius_m": 150}
    observation = {"latitude": 12.5001, "longitude": 77.5001}
    tool_result = tools["check_geofence"].invoke({"latitude": observation["latitude"], "longitude": observation["longitude"],
                                               "target_latitude": target["latitude"], "target_longitude": target["longitude"], "radius_m": 150})
    assert tool_result == geofence_result(observation, target)
    evaluator = ContextAutomationService(db)
    assert evaluator._is_inside_geofence(target, {"location": observation}) == tool_result["inside"]
    assert not evaluator._is_inside_geofence(target, {})
    assert geofence_result({"latitude": float("nan"), "longitude": 0}, target)["status"] == "uncertain"


def test_context_freshness_and_event_isolation(db):
    now = datetime.now(timezone.utc)
    db.create_event_idempotent("u", "saved", {"activity": "WALKING", "timestamp": (now - timedelta(hours=2)).isoformat()})
    service = ContextEvidenceService(db, "u")
    saved = service.current_context(now=now)
    assert saved["activity"] == "WALKING" and saved["fresh"] is False
    event = {"event_id": "current", "timestamp": now.isoformat(), "activity": "STILL",
             "feature_summary": {"dominant_freq_hz": 0, "z_rms": 0}}
    isolated = ContextEvidenceService(db, "u", state={"request_type": "CONTEXT_EVENT", "context_packet": event})
    current = isolated.current_context(now=now)
    assert current["event_id"] == "current" and current["fresh"] is True
    assert isolated.motion_evidence()["spectral_hint"]["candidate"] == "UNKNOWN"
    assert ContextEvidenceService(db, "other").current_context()["status"] == "unavailable"
    assert isolated.monitoring_status()["permissions"] == "unknown"


def test_preview_does_not_consume_geofence_transition_or_deliver(db):
    now = datetime.now(timezone.utc)
    reminder = db.create_reminder("u", {"title": "Helmet", "latitude": 12.5, "longitude": 77.5, "radius_m": 100,
                                       "created_at": (now - timedelta(minutes=1)).isoformat()})
    event = {"event_id": "arrival", "timestamp": now.isoformat(), "location": {"latitude": 12.5, "longitude": 77.5}}
    tools = {tool.name: tool for tool in build_context_tools(db, "u")}
    before = db.get_reminder("u", reminder["id"])
    preview = tools["preview_reminder_match"].invoke({"reminder_id": reminder["id"], "event": event})
    assert preview["matches"] is True
    assert preview["trigger"] == "GEOFENCE_ENTER"
    assert db.get_trigger_state("u", "REMINDER", reminder["id"]) is None
    assert db.get_reminder("u", reminder["id"]) == before
    assert db.list_notifications("u") == []
    # The real event can still trigger once after a preview of that same event.
    assert len(ContextAutomationService(db).process_context_event("u", event)) == 1


def test_context_tool_registry_is_read_only_and_preview_is_user_scoped(db):
    tools = {tool.name: tool for tool in build_context_tools(db, "u")}
    assert set(tools) == BACKGROUND_CONTEXT_TOOL_NAMES
    assert not {"create_reminder", "delete_note", "configure_monitoring"} & set(tools)
    reminder = db.create_reminder("other", {"title": "Private"})
    result = tools["preview_reminder_match"].invoke({"reminder_id": reminder["id"]})
    assert result["status"] == "unavailable"
