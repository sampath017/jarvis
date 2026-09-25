from datetime import datetime, timedelta, timezone

from src.backend.activity_sessions import build_activity_sessions
from src.models.schemas import ContextEventRequest

BASE = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)


def event(minutes, activity, transition="ENTER", *, home=False, kind=None, anchor="network-a"):
    at = BASE + timedelta(minutes=minutes)
    return {"event_id": f"{minutes}:{activity}:{transition}:{kind}", "timestamp": at.isoformat(),
            "activity": activity, "transition": transition,
            "event_type": kind or ("ACTIVITY_ENTER" if transition == "ENTER" else "ACTIVITY_EXIT"),
            "saved_places": [{"id": "home", "user_label": "HOME"}] if home else [],
            "ambient_context": {"collected_at": at.isoformat(), "wifi": {"connected": {"id": anchor}}}}


def learned(duration=600, anchor="network-a"):
    return [{"moment_id": f"old-{i}", "end_at": (BASE-timedelta(days=60-i)).isoformat(),
             "duration": duration, "place_key": "wifi:"+anchor,
             "routine_key": "wifi:"+anchor+":weekend:2"} for i in range(3)]


def test_cold_start_groups_related_actions_without_a_timer_or_history():
    result = build_activity_sessions([event(0, "WALKING"), event(2, "STILL"),
                                     event(180, "STILL", kind="CONTEXT_CHECKPOINT")])
    assert len(result["activity_sessions"]) == 1
    assert result["activity_sessions"][0]["status"] == "PROVISIONAL"
    assert result["routine_learning"]["status"] == "LEARNING"
    assert result["micromoments"][0]["end_at"] == event(2, "STILL")["timestamp"]


def test_home_evidence_can_close_an_outing_without_waiting_for_training():
    result = build_activity_sessions([event(0, "WALKING"), event(2, "STILL", home=True),
                                     event(3, "STILL", home=True, kind="CONTEXT_CHECKPOINT"), event(4, "WALKING")])
    assert len(result["activity_sessions"]) == 2
    assert result["activity_sessions"][0]["boundary_reason"] == "confirmed_home_arrival"


def test_two_month_old_learning_survives_a_fresh_install_and_changes_boundaries():
    current = [event(0, "WALKING"), event(2, "STILL"), event(8, "STILL", kind="CONTEXT_CHECKPOINT"), event(10, "WALKING")]
    assert len(build_activity_sessions(current, learned(300))["activity_sessions"]) == 2
    assert len(build_activity_sessions(current, learned(1800))["activity_sessions"]) == 1


def test_late_events_rebuild_intervals_in_event_time_order():
    records = [event(0, "WALKING"), event(10, "WALKING", kind="CONTEXT_CHECKPOINT"), event(5, "WALKING", "EXIT"), event(5, "STILL")]
    result = build_activity_sessions(records)
    walk = result["micromoments"][0]
    assert walk["end_at"] == event(5, "WALKING", "EXIT")["timestamp"]
    assert walk["end_evidence"] == "detected_exit"
    assert len(walk["observations"]) == 2


def test_call_overlays_walking_and_does_not_replace_motion_or_close_mid_call():
    records = [event(0, "WALKING"), event(1, "WALKING", kind="CALL_START"), event(2, "STILL"),
               event(8, "STILL", kind="CONTEXT_CHECKPOINT"), event(10, "WALKING"), event(12, "WALKING", "EXIT", kind="CALL_END")]
    result = build_activity_sessions(records, learned(300))
    assert len(result["activity_sessions"]) == 1
    call = next(m for m in result["micromoments"] if m["activity"] == "PHONE_CALL")
    assert call["start_at"] == event(1, "WALKING", kind="CALL_START")["timestamp"]
    assert call["end_at"] == event(12, "WALKING", "EXIT", kind="CALL_END")["timestamp"]
    assert call["session_id"] == result["micromoments"][0]["session_id"]


def test_stale_radio_evidence_cannot_become_a_place_anchor():
    record = event(0, "STILL")
    record["ambient_context"]["collected_at"] = (BASE+timedelta(minutes=10)).isoformat()
    assert build_activity_sessions([record])["micromoments"][0]["place_key"] is None


def test_cached_bluetooth_observations_keep_their_original_age():
    record = event(0, "STILL")
    record["ambient_context"].pop("wifi")
    record["ambient_context"]["bluetooth"] = {"nearby": [
        {"id": "beacon-a", "rssi": -60, "age_ms": 120_001},
        {"id": "beacon-b", "rssi": -60, "age_ms": 120_001},
    ]}
    assert build_activity_sessions([record])["micromoments"][0]["place_key"] is None
    for beacon in record["ambient_context"]["bluetooth"]["nearby"]:
        beacon["age_ms"] = 30_000
    assert build_activity_sessions([record])["micromoments"][0]["place_key"].startswith("radio:")


def test_new_event_schema_retains_bounded_radio_and_location_status():
    request = ContextEventRequest.model_validate({"activity": "STILL", "location_status": "fix_unavailable",
        "ambient_context": {"collected_at": BASE.isoformat(), "wifi": {"status": "available", "connected": {"id": "a"}},
                            "bluetooth": {"status": "available", "nearby": [{"id": "b", "rssi": -65}]}}})
    saved = request.model_dump(mode="json")
    assert saved["ambient_context"]["wifi"]["connected"]["id"] == "a"
    assert saved["location_status"] == "fix_unavailable"


def test_partial_old_training_data_does_not_break_a_new_session():
    result = build_activity_sessions([event(0, 'WALKING')], [
        {'moment_id': 'incomplete'},
        {'moment_id': 'bad', 'place_key': 'p', 'routine_key': 'r', 'duration': 30, 'end_at': 'bad-date'},
    ])
    assert len(result['activity_sessions']) == 1
    assert result['routine_learning']['status'] == 'LEARNING'
