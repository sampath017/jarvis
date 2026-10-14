"""Saved-place hydration preserves the phone's timestamps and extension fields."""
from datetime import datetime, timezone

import pytest

from src.graph.nodes.load_context import LoadContextNode
from src.services.database import DatabaseService
from src.services.mobile_scope import MobileScope, current
from src.services.sqlite_store import SqlStore


UID = "jarvis_local_user"
CREATED = "2026-01-02T03:04:05+00:00"
UPDATED = "2026-02-03T04:05:06+00:00"


@pytest.fixture
def mobile_workspace():
    scope = MobileScope()
    token = current.set(scope)
    try:
        yield scope
    finally:
        current.reset(token)
        scope.release()


def saved_place():
    return {
        "id": "saved-home", "name": "Home", "google_place_id": "map-home",
        "user_label": "My home", "category": "home", "latitude": 12.9,
        "longitude": 80.2, "notes": "Use the east gate", "tags": ["saved", "home"],
        "created_at": CREATED, "updated_at": UPDATED,
        "alias": "My flat", "address": "Synthetic home address", "radius_m": 125.0,
    }


def test_background_context_hydration_has_no_saved_place_delta(mobile_workspace, monkeypatch):
    from src.services.places_client import PlacesClient

    def unexpected_provider(*args, **kwargs):
        pytest.fail("A context event without GPS must not call a place provider")

    monkeypatch.setattr(PlacesClient, "search_nearby", unexpected_provider)
    scope = mobile_workspace
    # Exercise preservation of both extension JSON and a future SQL column.
    scope.db.execute("ALTER TABLE places ADD COLUMN phone_revision TEXT")
    place = {**saved_place(), "phone_revision": "phone-version-7"}
    scope.seed({"records": {"places": [place]}})
    before = dict(scope.db.execute("SELECT * FROM places WHERE id=?", (place["id"],)).fetchone())
    initial = scope.snapshot()["places"]

    result = LoadContextNode()(dict(uid=UID, request_type="CONTEXT_EVENT",
        event_id="walking-enter", run_id="place-hydration-regression", raw_request={}))

    assert "error" not in result
    assert result["cloud_context_loaded"] is True  # Real RecordStore hydration ran.
    assert scope.changes()["records"]["places"] == []
    assert scope.snapshot()["places"] == initial
    after = dict(scope.db.execute("SELECT * FROM places WHERE id=?", (place["id"],)).fetchone())
    assert after == before  # Includes exact extra_json bytes, SQL extensions and timestamps.
    for field, value in place.items():
        if field != "tags":
            assert initial[0][field] == value


def test_place_upsert_uses_clock_but_retains_existing_creation_time(mobile_workspace, monkeypatch):
    from src.services.database.repositories import places_repo

    class Clock:
        value = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz):
            return cls.value

    monkeypatch.setattr(places_repo, "datetime", Clock)
    mobile_workspace.seed({})
    db = DatabaseService()
    created = db.create_place(UID, {"id": "new-place", "name": "Gym", "latitude": 1, "longitude": 2})
    assert created["created_at"] == created["updated_at"] == Clock.value.isoformat()

    Clock.value = datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc)
    updated = db.create_place(UID, {"id": "new-place", "name": "Gym entrance", "latitude": 1, "longitude": 2})
    stored = db.get_place(UID, "new-place")
    assert updated["created_at"] == stored["created_at"] == created["created_at"]
    assert updated["updated_at"] == stored["updated_at"] == Clock.value.isoformat()
    assert stored["name"] == "Gym entrance"


def test_place_upsert_respects_explicit_timestamps(mobile_workspace):
    mobile_workspace.seed({})
    db = DatabaseService()
    place = saved_place()
    created = db.create_place(UID, place)
    assert created["created_at"] == CREATED and created["updated_at"] == UPDATED
    assert db.get_place(UID, place["id"])["created_at"] == CREATED
    later = "2026-03-04T05:06:07+00:00"
    updated = db.create_place(UID, {**place, "name": "Home entrance", "updated_at": later})
    assert updated["created_at"] == CREATED and updated["updated_at"] == later
    stored = db.get_place(UID, place["id"])
    assert stored["created_at"] == CREATED and stored["updated_at"] == later


def test_place_upsert_cannot_replace_another_owners_key(mobile_workspace):
    mobile_workspace.seed({"records": {"places": [saved_place()]}})
    sql = SqlStore()
    before = sql.get("places", "saved-home", uid=UID)
    with pytest.raises(ValueError, match="another user"):
        DatabaseService().create_place("another-user", {**saved_place(), "name": "Foreign overwrite"})
    assert sql.get("places", "saved-home", uid=UID) == before
    assert sql.get("places", "saved-home", uid="another-user") is None
