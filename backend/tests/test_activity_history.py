from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from src.api.routers import automation


class FakeHistoryStore:
    def query_context_memory(self, uid, start, end):
        assert uid == "test-user"
        assert start == datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
        return ([{
            "event_id": "e1",
            "timestamp": "2026-09-29T08:00:00+00:00",
            "activity": "WALKING",
            "transition": "ENTER",
            "gps": {"latitude": 12.9, "longitude": 77.6},
            "mobility_session_id": "journey-1",
            "saved_places": [{"name": "Office"}],
            "nearby_candidates": [{"name": "Shop"}],
            "contexts": [],
        }], False)

    def get_mobility_sessions(self, uid):
        return [
            {"session_id": "journey-1", "started_at": "2026-09-29T07:00:00+00:00",
             "last_updated": "2026-09-29T09:00:00+00:00", "status": "PAUSED"},
            {"session_id": "yesterday", "started_at": "2026-09-28T07:00:00+00:00",
             "last_updated": "2026-09-28T09:00:00+00:00", "status": "COMPLETED"},
        ]


def test_activity_history_returns_map_points_and_overlapping_sessions(monkeypatch):
    monkeypatch.setattr(automation, "_fs", FakeHistoryStore)
    result = automation.activity_history(
        "test-user", "2026-09-29T00:00:00+00:00", "2026-09-30T00:00:00+00:00"
    )
    assert result["observation_count"] == 1
    assert result["observations"][0]["gps"] == {"latitude": 12.9, "longitude": 77.6}
    assert result["timeline"][0]["session_id"] == "journey-1"
    assert [session["session_id"] for session in result["sessions"]] == ["journey-1"]


def test_activity_history_rejects_multi_day_window():
    with pytest.raises(HTTPException) as error:
        automation.activity_history(
            "test-user", "2026-09-29T00:00:00+00:00", "2026-10-01T00:00:00+00:00"
        )
    assert error.value.status_code == 422


def test_today_does_not_report_future_hours_as_a_gap(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 29, 8, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(automation, 'datetime', FrozenDateTime)
    monkeypatch.setattr(automation, '_fs', FakeHistoryStore)
    result = automation.activity_history(
        'test-user', '2026-09-29T00:00:00+00:00', '2026-09-30T00:00:00+00:00'
    )
    assert result['window_end'] == '2026-09-29T08:05:00+00:00'
    assert result['gap_count'] == 1
