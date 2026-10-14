"""Queued history must not replay live reasoning, journey changes or alerts."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.api.routers import context_events
from src.models.enums import SessionStatus, VehicleClass
from src.models.schemas import ContextEventRequest, SessionState
from src.services.database import DatabaseService
from src.services.mobile_scope import MobileScope, current
from src.services.record_store import RecordStore


UID = "jarvis_local_user"


@pytest.fixture(autouse=True)
def mobile(monkeypatch):
    monkeypatch.setattr(context_events, "TokenBudgetGuard", Mock())


@contextmanager
def mobile_scope():
    state = MobileScope()
    token = current.set(state)
    try:
        state.seed({})
        yield state
    finally:
        current.reset(token)
        state.release()


def test_stale_event_preserves_raw_history_without_live_side_effects(monkeypatch):
    now = datetime.now(timezone.utc)
    observed = now - timedelta(hours=2)
    request = ContextEventRequest(
        event_id="offline-walking", event_type="ACTIVITY_ENTER",
        activity="WALKING", transition="ENTER", occurred_at=observed,
        context_request_id="expired-device-request",
        location={"latitude": 12.9, "longitude": 80.2, "accuracy_m": 75,
                  "timestamp": observed.isoformat()},
        feature_summary={"classification_confidence": 0.1,
                         "vehicle_class_hint": "UNKNOWN"},
    )
    workflow = Mock()
    workflow.invoke.side_effect = AssertionError("Historical replay cannot invoke the live graph")
    for target in (
        "src.services.places_client.PlacesClient.search_nearby",
        "src.services.device_context.DeviceContext.receive",
        "src.backend.activity_sessions.enriched_history",
    ):
        monkeypatch.setattr(target, Mock(side_effect=AssertionError("No live historical processing")))
    automation = Mock(side_effect=AssertionError("Historical replay cannot evaluate reminders"))
    monkeypatch.setattr(context_events, "ContextAutomationService", automation)

    with mobile_scope() as state:
        db, records = DatabaseService(), RecordStore()
        reminder = db.create_reminder(UID, {
            "id": "walk-reminder", "title": "Drink water", "activity": "WALKING",
            "status": "ACTIVE", "created_at": (observed - timedelta(days=1)).isoformat(),
        })
        records.save_reminder(reminder["id"], reminder)
        session = SessionState(status=SessionStatus.ACTIVE, vehicle_class=VehicleClass.CAR)
        db.upsert_session(UID, session.session_id, session.model_dump(mode="json"))
        records.save_mobility_session(UID, session.session_id, session.model_dump(mode="json"))
        before_session = db.get_active_session(UID)
        before_reminders = db.list_reminders(UID)
        state.baseline = state.snapshot()

        for _ in range(2):  # A lost acknowledgement may replay this same event.
            response = asyncio.run(context_events.ingest_context_event(request, UID, workflow))
            assert response.status == "ok", response.error
            assert response.changed_records == [] and response.session_id is None

        assert db.get_active_session(UID) == before_session
        assert db.list_reminders(UID) == before_reminders
        event = db.get_latest_context_event(UID)
        assert event["id"] == request.event_id and event["activity"] == "WALKING"
        assert datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) == observed
        assert event["gps"]["latitude"] == 12.9
        assert event["feature_summary"]["classification_confidence"] == 0.1
        assert state.db.execute("SELECT COUNT(*) FROM context_events").fetchone()[0] == 1
        memories = records.sql.list("context_memory", uid=UID)
        assert len(memories) == 1
        memory = memories[0]
        assert datetime.fromisoformat(memory["timestamp"]) == observed
        assert memory["mobility_session_id"] is None
        assert memory["contexts"] == [] and memory["nearby_candidates"] == []
        changes = state.changes()
        assert changes["notifications"] == []
        assert all(not rows for rows in changes["records"].values())
        for table in ("mobility_sessions", "dynamic_reminder_state", "context_trigger_state"):
            assert changes["agent"]["domain"][table] == []
    workflow.invoke.assert_not_called()
    automation.assert_not_called()


def test_stale_http_event_returns_normal_mobile_history_changes(monkeypatch):
    from src.api.dependencies import get_workflow
    from src.api.main import create_app

    workflow = Mock()
    workflow.invoke.side_effect = AssertionError("No live graph for history")
    app = create_app()
    app.dependency_overrides[get_workflow] = lambda: workflow
    observed = datetime.now(timezone.utc) - timedelta(days=1)
    with TestClient(app) as client:
        response = client.post("/context-events", json={
            "event_id": "historical-http", "event_type": "ACTIVITY_ENTER",
            "activity": "WALKING", "occurred_at": observed.isoformat(),
        })
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["status"] == "ok", result
    changes = result["_mobile_changes"]
    assert changes["operation_id"] == "event:historical-http"
    assert changes["notifications"] == []
    events = changes["agent"]["domain"]["context_events"]
    assert len(events) == 1 and events[0]["id"] == "historical-http"
    assert datetime.fromisoformat(events[0]["timestamp"].replace("Z", "+00:00")) == observed
    assert any(row["table"] == "context_memory"
               for row in changes["agent"]["records"])
    workflow.invoke.assert_not_called()


@pytest.mark.parametrize("event_type", ["ACTIVITY_ENTER", "ACTIVITY_TRANSITION"])
def test_fresh_transition_still_uses_graph_and_automation(monkeypatch, event_type):
    workflow = Mock()
    workflow.invoke.return_value = {"run_id": "fresh-run", "semantic_contexts": [], "error": None}
    automation = Mock()
    automation.return_value.process_context_event.return_value = []
    monkeypatch.setattr(context_events, "ContextAutomationService", automation)
    monkeypatch.setattr("src.backend.activity_sessions.enriched_history", Mock())
    with mobile_scope():
        response = asyncio.run(context_events.ingest_context_event(
            ContextEventRequest(event_type=event_type, activity="WALKING"), UID, workflow))
    assert response.status == "ok" and response.run_id == "fresh-run"
    workflow.invoke.assert_called_once()
    automation.return_value.process_context_event.assert_called_once()
    event = automation.return_value.process_context_event.call_args.args[1]
    assert event["event_type"] == event_type


def test_future_event_keeps_existing_graph_handling_without_live_automation(monkeypatch):
    workflow = Mock()
    workflow.invoke.return_value = {"run_id": "future-run", "error": None}
    automation = Mock(side_effect=AssertionError("A future event cannot deliver reminders"))
    monkeypatch.setattr(context_events, "ContextAutomationService", automation)
    with mobile_scope():
        response = asyncio.run(context_events.ingest_context_event(ContextEventRequest(
            event_type="ACTIVITY_SAMPLE", activity="WALKING",
            occurred_at=datetime.now(timezone.utc) + timedelta(minutes=10)), UID, workflow))
    assert response.status == "ok" and response.run_id == "future-run"
    workflow.invoke.assert_called_once()
    automation.assert_not_called()
