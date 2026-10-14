"""Real SQLite ownership and atomic domain-repository guarantees."""
from datetime import datetime, timezone
import sqlite3

import pytest

from src.services.record_store import RecordStore
from src.services.sqlite_store import AlreadyExists, SqlStore


def test_named_sql_entities_and_owner_isolation():
    store = SqlStore(":memory:")
    store.put("semantic_contexts", "shared-id", {"state": "DWELLING", "active": True,
        "confidence": 0.9, "anchor": {"latitude": 12.9, "longitude": 80.2}}, uid="one")
    store.put("semantic_contexts", "shared-id", {"state": "PARKED"}, uid="two")
    assert store.get("semantic_contexts", "shared-id", uid="one")["state"] == "DWELLING"
    assert store.get("semantic_contexts", "shared-id", uid="two")["state"] == "PARKED"
    with pytest.raises(ValueError, match="Owner is required"):
        store.get("semantic_contexts", "shared-id")
    assert len(store.list("semantic_contexts", uid="one", filters=[("active", "==", True)])) == 1
    assert store.db.execute("SELECT state,confidence FROM state_semantic_contexts WHERE uid='one'").fetchone()["confidence"] == 0.9
    with pytest.raises(ValueError):
        store.list("semantic_contexts; DROP TABLE notes")
    with pytest.raises(ValueError):
        store.list("semantic_contexts", filters=[("state); DROP TABLE notes", "==", "bad")])


def test_atomic_nested_rollback_and_independent_state_namespace():
    store = SqlStore(":memory:")
    with pytest.raises(RuntimeError):
        with store.atomic():
            store.put("notes", "note", {"content": "must roll back"}, uid="u")
            with store.atomic():
                store.put("context_memory", "event", {"activity": "WALKING"}, uid="u")
            raise RuntimeError("abort outer operation")
    assert store.get("notes", "note", uid="u") is None
    assert store.get("context_memory", "event", uid="u") is None
    store.db.execute("INSERT INTO mobility_sessions(id,uid,status,vehicle_class,started_at,last_updated,created_at,updated_at) VALUES('s','u','ACTIVE','CAR','now','now','now','now')")
    store.put("mobility_sessions", "s", {"status": "PAUSED", "vehicle_class": "CAR",
        "parking_gps": {"latitude": 12.9, "longitude": 80.2}}, uid="u")
    assert store.db.in_transaction  # Nested helper does not commit caller SQL.
    store.db.commit()
    assert store.db.execute("SELECT status FROM mobility_sessions WHERE id='s'").fetchone()[0] == "ACTIVE"
    assert store.get("mobility_sessions", "s", uid="u")["status"] == "PAUSED"
    assert store.get("mobility_sessions", "s", uid="u")["parking_gps"]["latitude"] == 12.9


def test_datetime_nested_payload_and_unique_insert_roundtrip():
    store = SqlStore(":memory:")
    now = datetime.now(timezone.utc)
    store.create("command_runs", "run", {"status": "queued", "started_at": now,
        "payload": {"sent_at": now, "text": "a' OR 1=1 --"}}, uid="u")
    row = store.get("command_runs", "run", uid="u")
    assert row["started_at"] == now and row["payload"]["sent_at"] == now
    store.put("command_runs", "run", {"status": "complete"}, uid="u")
    assert store.get("command_runs", "run", uid="u")["payload"]["text"] == "a' OR 1=1 --"
    with pytest.raises(AlreadyExists):
        store.create("command_runs", "run", {}, uid="u")


def test_entity_id_is_its_canonical_sql_primary_key():
    store = SqlStore(":memory:")
    with pytest.raises(ValueError, match="Entity id must match its SQL key"):
        store.put("file_memories", "different-key", {"id": "file-id", "name": "CV.pdf"}, uid="owner")
    assert store.list("file_memories", uid="owner") == []
    store.put("file_memories", "file-id", {"id": "file-id", "name": "CV.pdf"}, uid="owner")
    assert store.get("file_memories", "file-id", uid="owner")["id"] == "file-id"


def test_replace_clears_old_scalar_columns_and_nested_values():
    store = SqlStore(":memory:")
    store.put("command_runs", "run", {"status": "running", "message": "Old progress",
        "started_at": datetime.now(timezone.utc), "calendar_result": {"status": "ok"}}, uid="u")
    replaced = store.put("command_runs", "run", {"status": "complete"}, uid="u", merge=False)
    assert replaced["status"] == "complete"
    assert replaced["message"] is None and replaced["started_at"] is None
    assert "calendar_result" not in replaced
    store.put("notes", "note", {"content": "Old text", "place": "Gym", "category": "work"}, uid="u")
    note = store.put("notes", "note", {"content": "New text"}, uid="u", merge=False)
    assert note["content"] == "New text" and note["place"] == "" and note["category"] == ""




def test_record_store_reminder_notification_is_atomic_and_one_shot():
    store = SqlStore(":memory:")
    records = RecordStore.from_sql(store)
    assert records.save_reminder("rem", {"uid": "u", "title": "Drink water", "activity": "WALKING"})
    reminder = records.get_reminders("u")[0]
    notification = {"title": "Drink water", "body": "Walking", "trigger_type": "ACTIVITY_ENTER",
        "event_id": "event", "reminder_id": "rem", "payload": {"occurred_at": "2026-10-28T10:00:00+00:00"}}
    result, created, saved = records.commit_reminder_notification("u", reminder, notification)
    assert created and saved["status"] == "COMPLETED"
    repeated, created, _ = records.commit_reminder_notification("u", reminder, notification)
    assert not created and repeated["id"] == result["id"]
    assert len(records.get_notifications("u", "PENDING")) == 1
    assert records.get_notifications("other") == []




def test_domain_repository_respects_outer_sql_transaction_and_commits_standalone():
    from src.services.database import DatabaseService
    from src.services.mobile_scope import MobileScope, current
    scope = MobileScope()
    token = current.set(scope)
    try:
        store = SqlStore()
        domain = DatabaseService()
        with pytest.raises(RuntimeError, match="abort combined operation"):
            with store.atomic():
                domain.create_note("u", {"id": "rolled-back", "content": "Do not commit early"})
                store.put("context_memory", "event", {"activity": "WALKING"}, uid="u")
                assert scope.db.in_transaction
                raise RuntimeError("abort combined operation")
        assert store.get("notes", "rolled-back", uid="u") is None
        assert store.get("context_memory", "event", uid="u") is None
        domain.create_note("u", {"id": "committed", "content": "Standalone operation"})
        assert not scope.db.in_transaction
        assert store.get("notes", "committed", uid="u")["content"] == "Standalone operation"
    finally:
        current.reset(token)
        scope.release()


def test_domain_savepoint_failure_does_not_discard_valid_outer_changes():
    from src.services.database import DatabaseService
    from src.services.mobile_scope import MobileScope, current
    scope = MobileScope()
    token = current.set(scope)
    try:
        store = SqlStore()
        domain = DatabaseService()
        with store.atomic():
            store.put("notes", "kept", {"content": "Outer work"}, uid="u")
            with pytest.raises(sqlite3.IntegrityError):
                with domain._conn() as connection:
                    connection.execute("INSERT INTO notes(id,uid,content,created_at,updated_at) VALUES('invalid','u',NULL,'now','now')")
            assert store.get("notes", "kept", uid="u")["content"] == "Outer work"
        assert store.get("notes", "kept", uid="u") is not None
        assert store.get("notes", "invalid", uid="u") is None
    finally:
        current.reset(token)
        scope.release()
