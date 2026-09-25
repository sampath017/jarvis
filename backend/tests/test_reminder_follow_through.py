from datetime import datetime, timedelta, timezone

import pytest

from src.backend.context_automation import ContextAutomationService
from src.cloud.tier2_agent_tools import build_tier2_tools
from src.services.database import DatabaseService


@pytest.fixture
def db(tmp_path):
    return DatabaseService(db_path=str(tmp_path / "reminders.db"))


def test_already_still_rechecked_once(db):
    now = datetime.now(timezone.utc)
    db.create_event_idempotent("u", "still", {
        "activity": "STILL", "timestamp": (now - timedelta(seconds=60)).isoformat(),
        "gps": {"latitude": 12, "longitude": 80},
    })
    reminder = db.create_reminder("u", {
        "title": "Water", "activity": "STILL", "location_name": "Office",
        "latitude": 12, "longitude": 80,
        "created_at": (now - timedelta(seconds=10)).isoformat(),
    })
    service = ContextAutomationService(db)
    assert len(service.process_due_reminders(now)) == 1
    assert service.process_due_reminders(now) == []
    assert db.get_reminder("u", reminder["id"])["status"] == "COMPLETED"


@pytest.mark.parametrize("age,latitude,transition", [(301, 12, "ENTER"), (60, 13, "ENTER"), (60, 12, "EXIT")])
def test_stale_outside_or_exited_context_does_not_fire(db, age, latitude, transition):
    now = datetime.now(timezone.utc)
    db.create_event_idempotent("u", "context", {
        "activity": "STILL", "transition": transition,
        "timestamp": (now - timedelta(seconds=age)).isoformat(),
        "gps": {"latitude": latitude, "longitude": 80},
    })
    db.create_reminder("u", {
        "title": "Water", "activity": "STILL", "latitude": 12, "longitude": 80,
        "due_at": (now - timedelta(seconds=30)).isoformat(),
        "created_at": (now - timedelta(seconds=120)).isoformat(),
    })
    assert ContextAutomationService(db).process_due_reminders(now) == []


def test_unresolved_update_leaves_existing_coordinates_untouched(db):
    reminder = db.create_reminder("u", {"title": "Water", "latitude": 12, "longitude": 80})
    tools = {tool.name: tool for tool in build_tier2_tools(db, "u")}
    result = tools["update_reminder"].invoke({"reminder_id": reminder["id"], "location_name": "Unknown desk", "confirmed": True})
    assert result.startswith("CONFIRMATION_REQUIRED")
    assert db.get_reminder("u", reminder["id"])["location_name"] is None


def test_missing_trigger_is_not_saved(db):
    tools = {tool.name: tool for tool in build_tier2_tools(db, "u")}
    assert tools["create_reminder"].invoke({"title": "Water"}).startswith("CONFIRMATION_REQUIRED")
    assert db.list_reminders("u") == []
