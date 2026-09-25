from datetime import datetime, timedelta, timezone

import pytest

from src.backend.semantic_context import (
    GeoPoint,
    PredicateKind,
    ReminderPolicy,
    SemanticContextLedger,
    SemanticContextState,
    SemanticObservation,
    SemanticPlace,
    SemanticPlaceKind,
    evaluate_reminder_policy,
)
from src.services.firestore_service import FirestoreService


def observation(event_id: str, at: datetime, **kwargs) -> SemanticObservation:
    return SemanticObservation(event_id=event_id, occurred_at=at, **kwargs)


def test_parked_context_is_idempotent_and_closed_only_by_its_session():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ledger = SemanticContextLedger()
    parked = observation(
        "park-1", now, mobility_session_id="trip-a", mobility_status="PAUSED",
        parking_location=GeoPoint(12.0, 77.0),
    )

    first = ledger.reduce(parked)
    duplicate = ledger.reduce(parked)
    wrong_session = ledger.reduce(observation("resume-b", now, mobility_session_id="trip-b", mobility_status="RESUMED"))
    resumed = ledger.reduce(observation("resume-a", now, mobility_session_id="trip-a", mobility_status="RESUMED"))

    assert first[0].context.state is SemanticContextState.PARKED
    assert first[0].should_evaluate_agent
    assert not duplicate[0].should_evaluate_agent
    assert not wrong_session
    assert resumed[0].context.active is False


def test_dwell_then_shop_requires_time_and_structured_place_semantics():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ledger = SemanticContextLedger(dwell_seconds=90)
    loc = GeoPoint(12.0, 77.0, accuracy_m=8)
    shop = SemanticPlace(SemanticPlaceKind.SHOP, confidence=0.9, place_id="poi-1", label="Any display name")

    started = ledger.reduce(observation("stop-1", now, activity="STILL", location=loc, place=shop))
    confirmed = ledger.reduce(observation("stop-2", now + timedelta(seconds=91), activity="STILL", location=loc, place=shop))

    assert started[0].context.state is SemanticContextState.DWELLING
    assert not started[0].should_evaluate_agent
    assert [change.context.state for change in confirmed] == [SemanticContextState.DWELLING, SemanticContextState.IN_SHOP]
    assert all(change.should_evaluate_agent for change in confirmed)


def test_policy_evaluates_agent_plan_against_context_without_text_matching():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ledger = SemanticContextLedger(dwell_seconds=60)
    loc = GeoPoint(12.0, 77.0)
    shop = SemanticPlace(SemanticPlaceKind.SHOP, confidence=0.95, place_id="retail-1", label="Not inspected")
    ledger.reduce(observation("a", now, activity="STILL", location=loc, place=shop))
    contexts = ledger.reduce(observation("b", now + timedelta(seconds=61), activity="STILL", location=loc, place=shop))
    in_shop = next(change.context for change in contexts if change.context.state is SemanticContextState.IN_SHOP)
    policy = ReminderPolicy.from_agent_plan({
        "policy_id": "buy-something", "minimum_confidence": 0.75,
        "conditions": [
            {"kind": "CONTEXT_STATE", "values": ["IN_SHOP"]},
            {"kind": "PLACE_KIND", "values": ["SHOP"]},
            {"kind": "MIN_DWELL_SECONDS", "seconds": 60},
        ],
    })

    result = evaluate_reminder_policy(policy, in_shop, at=now + timedelta(seconds=61))

    assert result.matched
    assert not result.unmatched_conditions


def test_agent_plan_rejects_unbounded_or_unknown_conditions():
    with pytest.raises(ValueError, match="unknown reminder condition"):
        ReminderPolicy.from_agent_plan({"conditions": [{"kind": "FREE_TEXT", "values": ["when nearby"]}]})
    with pytest.raises(ValueError, match="unknown semantic context state"):
        ReminderPolicy.from_agent_plan({"conditions": [{"kind": "CONTEXT_STATE", "values": ["SOMEWHERE"]}]})


def test_ledger_serialization_preserves_multiple_contexts():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ledger = SemanticContextLedger()
    ledger.reduce(observation("p", now, mobility_session_id="trip-a", mobility_status="PAUSED", parking_location=GeoPoint(12.0, 77.0)))
    restored = SemanticContextLedger.from_dicts(ledger.to_dicts())

    assert len(restored.contexts) == 1
    assert restored.contexts[0].state is SemanticContextState.PARKED


def test_leaving_a_shop_closes_visit_context_without_closing_parking():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ledger = SemanticContextLedger(dwell_seconds=1)
    loc = GeoPoint(12.0, 77.0, accuracy_m=5)
    shop = SemanticPlace(SemanticPlaceKind.SHOP, confidence=0.9, place_id="poi-1")
    ledger.reduce(observation("park", now, mobility_session_id="trip-a", mobility_status="PAUSED", parking_location=loc))
    ledger.reduce(observation("a", now, activity="STILL", location=loc, place=shop))
    ledger.reduce(observation("b", now + timedelta(seconds=2), activity="STILL", location=loc, place=shop))

    changes = ledger.reduce(observation("left", now + timedelta(seconds=3), activity="WALKING", location=GeoPoint(12.01, 77.01, accuracy_m=5)))

    exited = {change.context.state for change in changes if change.reason == "left_context_area"}
    parked = next(context for context in ledger.contexts if context.state is SemanticContextState.PARKED)
    assert exited == {SemanticContextState.DWELLING, SemanticContextState.IN_SHOP}
    assert parked.active


class _Snapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Doc:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def collection(self, name):
        return _Collection(self.store, (*self.path, name))

    def get(self):
        return _Snapshot(self.store.get(self.path))

    def set(self, data, merge=False):
        current = self.store.get(self.path, {}) if merge else {}
        self.store[self.path] = {**current, **data}


class _Collection:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def document(self, name):
        return _Doc(self.store, (*self.path, name))

    def stream(self):
        length = len(self.path)
        return [_Snapshot(value) for path, value in self.store.items() if path[:-1] == self.path and len(path) == length + 1]


class _FakeFirestore:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return _Collection(self.store, (name,))


def test_firestore_semantic_contexts_are_uid_scoped_and_reject_stale_updates():
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    first = {
        "state": "IN_SHOP", "active": True, "last_event_id": "event-2",
        "last_observed_at": "2026-01-01T00:02:00+00:00",
    }
    stale = {**first, "active": False, "last_event_id": "event-1", "last_observed_at": "2026-01-01T00:01:00+00:00"}

    assert service.save_semantic_context("alice", "shop-1", first)
    assert service.save_semantic_context("alice", "shop-1", stale)
    assert service.save_semantic_context("bob", "shop-1", {**first, "state": "PARKED"})

    alice_context = service.get_semantic_contexts("alice")[0]
    assert alice_context["state"] == "IN_SHOP"
    assert alice_context["active"] is True
    assert alice_context["version"] == 1
    assert alice_context["uid"] == "alice"
    assert service.get_semantic_contexts("bob")[0]["state"] == "PARKED"


def test_firestore_active_mobility_session_is_latest_active_session():
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    assert service.save_mobility_session("alice", "old", {"status": "COMPLETED", "last_updated": "2026-01-01T00:00:00+00:00"})
    assert service.save_mobility_session("alice", "active", {"status": "PAUSED", "last_updated": "2026-01-01T00:02:00+00:00"})
    assert service.get_active_mobility_session("alice")["session_id"] == "active"


def test_repeated_parking_and_shop_stops_retain_separate_history():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    loc = GeoPoint(12, 77, 5)
    shop = SemanticPlace(SemanticPlaceKind.SHOP, 0.9, "store")
    ledger = SemanticContextLedger(dwell_seconds=1)
    def send(key, seconds, **kwargs):
        return ledger.reduce(observation(key, now + timedelta(seconds=seconds), **kwargs))
    send("park1", 0, mobility_session_id="trip", mobility_status="PAUSED", parking_location=loc)
    send("stop1", 1, activity="STILL", location=loc, place=shop)
    send("dwell1", 3, activity="STILL", location=loc, place=shop)
    send("drive", 4, activity="IN_VEHICLE", mobility_session_id="trip", mobility_status="RESUMED")
    send("park2", 10, mobility_session_id="trip", mobility_status="PAUSED", parking_location=loc)
    send("stop2", 11, activity="STILL", location=loc, place=shop)
    send("dwell2", 13, activity="STILL", location=loc, place=shop)
    for state in (SemanticContextState.PARKED, SemanticContextState.IN_SHOP):
        contexts = [c for c in ledger.contexts if c.state is state]
        assert len(contexts) == 2
        assert sum(c.active for c in contexts) == 1
    before = ledger.to_dicts()
    send("stale", 2, activity="STILL", location=GeoPoint(14, 78))
    assert ledger.to_dicts() == before


def test_context_memory_is_durable_idempotent_and_user_scoped():
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    record = {"timestamp": "2026-09-24T00:00:00+00:00", "activity": "WALKING",
              "nearby_candidates": [{"name": "Shop"}], "contexts": []}
    assert service.save_context_memory("alice", "event/1", record)
    assert service.save_context_memory("alice", "event/1", record)
    assert service.get_context_memory("bob") == []
    rows = service.get_context_memory("alice")
    assert len(rows) == 1
    assert rows[0]["contexts"] == []
    assert rows[0]["version"] == 1


def test_history_query_reads_two_days_beyond_recent_preview_limit():
    from src.backend.context_history import build_timeline, history_window
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    end = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    for i in range(180):
        service.save_context_memory("alice", f"event-{i}", {
            "timestamp": (end - timedelta(minutes=i * 10)).isoformat(),
            "activity": "WALKING", "mobility_session_id": "trip", "contexts": [],
        })
    start, stop = history_window(2880, end_at=end.isoformat())
    records, truncated = service.query_context_memory("alice", start, stop)
    assert len(records) == 180
    assert not truncated
    recent, _ = service.query_context_memory("alice", end - timedelta(minutes=10), end)
    assert len(recent) == 2
    assert service.query_context_memory("bob", start, stop) == ([], False)
    _, truncated = service.query_context_memory("alice", start, stop, limit=10)
    assert truncated
    report = build_timeline(records, start, stop)
    assert report["observation_count"] == 180
    assert report["gap_count"] == 1  # Time before the first observation is unknown.


def test_history_distinguishes_nearby_from_visits_and_flags_missing_data():
    from src.backend.context_history import build_timeline, history_window
    start, end = history_window(start_at="2026-09-25T10:00:00+05:30", end_at="2026-09-25T10:30:00+05:30")
    record = {"timestamp": "2026-09-25T10:01:00+05:30", "activity": "STILL",
              "nearby_candidates": [{"name": "Grocery"}], "contexts": []}
    report = build_timeline([record], start, end)
    assert report["window_start"] == "2026-09-25T04:30:00+00:00"
    assert report["timeline"][0]["nearby_not_confirmed_visits"] == ["Grocery"]
    assert report["timeline"][0]["inferred_contexts"] == []
    assert report["gap_count"] == 1
    with pytest.raises(ValueError):
        history_window(start_at="2026-09-25T10:00:00", end_at="2026-09-25T10:30:00")


def test_cloud_reminder_outbox_survives_retries_and_preserves_delivery():
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    reminder = {"id": "water", "uid": "alice", "title": "Water", "activity": "STILL", "status": "ACTIVE"}
    service._db.collection("reminders").document("water").set(reminder)
    notification = {"reminder_id": "water", "event_id": "first", "title": "Water",
                    "payload": {"occurred_at": "2026-09-25T00:00:00+00:00"}}
    record, created, saved = service.commit_reminder_notification("alice", reminder, notification)
    assert created and saved["status"] == "COMPLETED"
    service.acknowledge_cloud_notification("alice", record["id"])
    repeated, created, _ = service.commit_reminder_notification("alice", reminder, {**notification, "event_id": "second"})
    assert not created and repeated["status"] == "DELIVERED"
    assert service.get_notifications("alice", "PENDING") == []
    assert service.get_notifications("bob") == []


def test_changed_reminder_policy_is_not_fired_from_stale_context_plan():
    service = object.__new__(FirestoreService)
    service._db = _FakeFirestore()
    reminder = {"id": "water", "uid": "alice", "title": "Water", "activity": "STILL", "status": "ACTIVE"}
    service._db.collection("reminders").document("water").set({**reminder, "activity": "WALKING"})
    _, created, _ = service.commit_reminder_notification("alice", reminder, {"event_id": "first"})
    assert not created
    assert service.get_notifications("alice") == []
