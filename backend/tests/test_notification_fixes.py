import pytest
from datetime import datetime, timezone
from src.services.database import DatabaseService
from src.backend.context_automation import ContextAutomationService, _activity_entered


@pytest.fixture
def db(tmp_path):
    return DatabaseService(db_path=str(tmp_path / "test.db"))


def test_multi_activity_matching():
    # Event is WALKING ENTER
    event_walking = {"transition": "ENTER", "activity": "WALKING"}
    assert _activity_entered(event_walking, "WALKING, IN_VEHICLE")
    assert _activity_entered(event_walking, "IN_VEHICLE, WALKING")
    assert _activity_entered(event_walking, "WALKING / IN_VEHICLE")
    assert _activity_entered(event_walking, "WALKING or IN_VEHICLE")

    # Event is IN_VEHICLE ENTER
    event_vehicle = {"transition": "ENTER", "activity": "IN_VEHICLE"}
    assert _activity_entered(event_vehicle, "WALKING, IN_VEHICLE")

    # Event is STILL ENTER - should not match
    event_still = {"transition": "ENTER", "activity": "STILL"}
    assert not _activity_entered(event_still, "WALKING, IN_VEHICLE")

    # Event is EXIT - should not match
    event_exit = {"transition": "EXIT", "activity": "WALKING"}
    assert not _activity_entered(event_exit, "WALKING, IN_VEHICLE")


def test_list_due_reminders_excludes_empty_due_at(db):
    uid = "test_user"
    # Create reminder with empty string due_at
    r1 = db.create_reminder(uid, {"title": "Buy chicken", "due_at": "", "activity": "WALKING"})
    # Create reminder with None due_at
    r2 = db.create_reminder(uid, {"title": "Listen music", "due_at": None, "activity": "WALKING"})
    # Create reminder with actual overdue time
    r3 = db.create_reminder(uid, {"title": "Take pill", "due_at": "2026-01-01T00:00:00+00:00"})

    now = datetime.now(timezone.utc).isoformat()
    due = db.list_due_reminders(now)
    due_ids = [r["id"] for r in due]

    assert r1["id"] not in due_ids
    assert r2["id"] not in due_ids
    assert r3["id"] in due_ids


def test_sibling_auto_completion_on_fire(db):
    uid = "test_user"
    automation = ContextAutomationService(db)

    # Create two reminders with same title (e.g. WALKING and IN_VEHICLE)
    r1 = db.create_reminder(uid, {"title": "Buy groceries", "activity": "WALKING", "one_shot": True})
    r2 = db.create_reminder(uid, {"title": "Buy groceries", "activity": "IN_VEHICLE", "one_shot": True})

    event = {"event_id": "evt_test", "occurred_at": datetime.now(timezone.utc).isoformat(), "transition": "ENTER", "activity": "WALKING"}
    now = datetime.now(timezone.utc)

    # Fire r1
    notif, created = automation._fire_reminder(uid, r1, event, now, "ACTIVITY_ENTER")
    assert created

    # Check that r1 is COMPLETED
    updated_r1 = db.get_reminder(uid, r1["id"])
    assert updated_r1["status"] == "COMPLETED"

    # Check that sibling r2 was also automatically COMPLETED
    updated_r2 = db.get_reminder(uid, r2["id"])
    assert updated_r2["status"] == "COMPLETED"


def test_co_located_walking_reminder_fires_while_already_inside_flats(db):
    uid = "test_user"
    automation = ContextAutomationService(db)

    # Reminder to "Buy milk" when WALKING in Creations Valencia
    r = db.create_reminder(
        uid,
        {
            "title": "Buy milk",
            "activity": "WALKING",
            "location_name": "Creations Valencia (Home)",
            "latitude": 12.83729,
            "longitude": 80.22563,
            "radius_m": 150.0,
            "one_shot": True,
            "created_at": "2026-09-23T10:00:00+00:00",
        },
    )

    # User was ALREADY inside their flats (e.g. sitting in room)
    db.upsert_trigger_state(uid, "REMINDER", r["id"], True, "old_event_inside", "2026-09-23T10:05:00+00:00")

    # User starts WALKING inside flats (ACTIVITY_ENTER while inside)
    event = {
        "event_id": "evt_walk_start",
        "event_type": "ACTIVITY_ENTER",
        "transition": "ENTER",
        "activity": "WALKING",
        "location": {"latitude": 12.83729, "longitude": 80.22563},
        "occurred_at": "2026-09-23T10:15:00+00:00",
    }

    changed = automation.process_context_event(uid, event)
    assert len(changed) == 1

    # Reminder should now be marked COMPLETED
    updated = db.get_reminder(uid, r["id"])
    assert updated["status"] == "COMPLETED"
