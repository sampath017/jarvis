"""Domain and agent SQL state import atomically on the same request connection."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.services.sqlite_store import SqlStore
from src.services.database import DatabaseService
from src.services.mobile_scope import MobileScope, current


UID = "jarvis_local_user"
STAMP = "2026-10-28T10:00:00+00:00"


@contextmanager
def mobile_scope():
    state = MobileScope()
    token = current.set(state)
    try:
        yield state
    finally:
        current.reset(token)
        state.release()


def mixed_state():
    return {
        "records": {"notes": [{"id": "phone-note", "title": "Walking log",
                                "content": "Original phone text", "updated_at": STAMP}]},
        "agent": {
            "domain": {
                "context_events": [{"id": "phone-event", "uid": "phone-owner",
                                    "activity": "WALKING", "transition": "ENTER",
                                    "timestamp": STAMP, "created_at": STAMP}],
                "context_trigger_state": [{"uid": "phone-owner", "source_type": "REMINDER",
                                           "source_id": "water", "is_inside": 1}],
            },
            "records": [
                {"table": "context_memory", "uid": "phone-owner", "id": "phone-memory",
                 "data": {"activity": "WALKING", "timestamp": STAMP}},
                {"table": "semantic_contexts", "uid": "phone-owner", "id": "phone-context",
                 "data": {"state": "DWELLING", "active": True, "confidence": 0.9}},
            ],
        },
    }


def assert_imported(state):
    snapshot = state.snapshot()
    assert snapshot["context_events"][0]["id"] == "phone-event"
    assert snapshot["context_events"][0]["uid"] == UID
    assert snapshot["context_trigger_state"][0]["is_inside"] == 1
    sql = SqlStore()
    memory = sql.get("context_memory", "phone-memory", uid=UID)
    assert memory["activity"] == "WALKING" and memory["timestamp"] == STAMP
    assert sql.get("context_memory", "phone-memory", uid="phone-owner") is None
    context = sql.get("semantic_contexts", "phone-context", uid=UID)
    assert context["state"] == "DWELLING"


def test_seed_mixed_domain_and_agent_state_has_no_nested_transaction():
    with mobile_scope() as state:
        # This mirrors the worker's real _mobile_state with both SQL namespaces.
        state.seed(mixed_state())
        assert not state.db.in_transaction
        assert_imported(state)
        changes = state.changes()
        assert changes["records"]["notes"] == []
        assert all(not rows for rows in changes["agent"]["domain"].values())
        assert changes["agent"]["records"] == []
        # A later normal tool transaction must also start cleanly.
        SqlStore().put("semantic_contexts", "phone-context", {"active": False}, uid=UID)
        assert len(state.changes()["agent"]["records"]) == 1


def test_mixed_import_read_commits_domain_rows_and_preserves_earlier_tool_writes():
    with mobile_scope() as state:
        state.seed({})
        db = DatabaseService()
        db.create_note(UID, {"id": "written-note", "content": "Saved earlier in this command"})
        state.import_read(mixed_state())
        assert not state.db.in_transaction
        assert_imported(state)
        # Re-reading the same phone state is a baseline, not a mutation or a
        # reason to overwrite state already changed during this command.
        state.import_read(mixed_state())
        assert not state.db.in_transaction
        assert_imported(state)
        changes = state.changes()
        assert [row["id"] for row in changes["records"]["notes"]] == ["written-note"]
        assert all(not rows for rows in changes["agent"]["domain"].values())
        assert changes["agent"]["records"] == []
        SqlStore().put("context_memory", "later-memory",
                       {"activity": "RUNNING", "timestamp": STAMP}, uid=UID)
        assert [row["id"] for row in state.changes()["agent"]["records"]] == ["later-memory"]


def test_invalid_mixed_seed_is_discarded_with_its_ram_scope():
    value = mixed_state()
    value["agent"]["records"][0]["table"] = "chat_messages"
    with mobile_scope() as failed:
        with pytest.raises(ValueError, match="Invalid SQL state record"):
            failed.seed(value)
        assert failed.db.execute("SELECT COUNT(*) FROM context_events").fetchone()[0] == 0
        assert failed.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert failed.closed
    with mobile_scope() as next_request:
        next_request.seed({})
        assert next_request.snapshot()["context_events"] == []
        assert next_request.snapshot()["notes"] == []


def test_selected_read_preserves_mutation_and_state_deletion_has_explicit_sql_key():
    with mobile_scope() as state:
        state.seed(mixed_state())
        sql = SqlStore()
        sql.put("semantic_contexts", "phone-context", {"active": False}, uid=UID)
        state.import_read(mixed_state())
        assert sql.get("semantic_contexts", "phone-context", uid=UID)["active"] is False
        sql.delete("context_memory", "phone-memory", uid=UID)
        changes = state.changes()["agent"]
        assert changes["removed"] == [{"table": "context_memory", "id": "phone-memory", "uid": UID}]
        assert [row["id"] for row in changes["records"]] == ["phone-context"]


def test_unsupported_agent_schema_is_rejected():
    with mobile_scope() as state:
        with pytest.raises(ValueError, match="Invalid SQL agent state"):
            state.seed({"agent": {"unsupported_state": []}})


def test_departure_state_survives_separate_phone_sql_requests():
    from src.backend.dynamic_reminders import DynamicReminders
    from src.services.record_store import RecordStore

    now = datetime.now(timezone.utc)
    reminder = {
        "id": "departure", "title": "Synthetic departure reminder", "status": "ACTIVE",
        "created_at": (now - timedelta(hours=1)).isoformat(),
        "dynamic_policy": {"version": 1, "trigger": "exit", "radius_m": 200,
                           "origin": {"name": "Gym", "latitude": 12.0, "longitude": 80.0}},
    }

    def observation(latitude, observed):
        return {"event_id": "synthetic-" + str(latitude), "occurred_at": observed.isoformat(),
                "activity": "WALKING", "transition": "ENTER",
                "location": {"latitude": latitude, "longitude": 80.0,
                             "accuracy_m": 5, "timestamp": observed.isoformat()}}

    with mobile_scope() as inside:
        inside.seed({"records": {"reminders": [reminder]}})
        matcher = DynamicReminders(DatabaseService(), RecordStore())
        assert matcher.match(UID, reminder, observation(12.0, now), now) is None
        saved = inside.changes()["agent"]["records"]
        assert [row["table"] for row in saved] == ["dynamic_reminder_state"]
        assert saved[0]["id"] == reminder["id"]
        assert saved[0]["data"]["origin_seen"] == now.isoformat()

    later = now + timedelta(seconds=30)
    with mobile_scope() as outside:
        outside.seed({"records": {"reminders": [reminder]}, "agent": {"records": saved}})
        result = DynamicReminders(DatabaseService(), RecordStore()).match(
            UID, reminder, observation(12.004, later), later)
        assert result is not None
        assert result["name"] == "Gym"
