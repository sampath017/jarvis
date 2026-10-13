from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.auth import get_current_user
from src.api.routers import motion_diagnostics as routes
from src.models.schemas import ContextEventRequest
from src.models.telemetry import MotionDiagnosticBatch


def record(**changes):
    return {"id": "motion_1234", "timestamp": "2026-10-12T12:00:00+05:30",
            "source": "local_motion", "candidate": "ON_FOOT", "provisional": True,
            "model_version": "motion_rules_v1", "boot_count": 9,
            "observed_elapsed_ms": 1000, "received_elapsed_ms": 1001,
            "delivery_delay_ms": 1, "features": {"samples": 75, "usable": True}, **changes}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: 'test-user'
    guard = MagicMock(); monkeypatch.setattr(routes, 'TokenBudgetGuard', lambda: guard)
    collection = MagicMock(); monkeypatch.setattr(routes, 'collection', lambda uid: collection)
    return TestClient(app), collection


def test_shadow_batch_is_separate_and_acknowledged_only_after_commit(client):
    api, collection = client
    response = api.post('/motion-diagnostics', json={'records': [record()]})
    assert response.status_code == 200
    assert response.json() == {'accepted_ids': ['motion_1234']}
    batch = collection._client.batch.return_value
    batch.commit.assert_called_once()
    _, stored = batch.set.call_args.args
    assert stored['timestamp'] == '2026-10-12T06:30:00+00:00'
    assert stored['provisional'] is True
    assert 'activity' not in stored and 'mobility_session_id' not in stored


def test_failed_write_never_acknowledges_device_records(client):
    api, collection = client
    collection._client.batch.return_value.commit.side_effect = RuntimeError('offline')
    response = api.post('/motion-diagnostics', json={'records': [record()]})
    assert response.status_code == 503
    assert 'accepted_ids' not in response.json()


@pytest.mark.parametrize('change', [{'provisional': False}, {'timestamp': '2026-10-12T12:00:00'},
                                  {'delivery_delay_ms': -1}, {'candidate': 'SLEEPING'},
                                  {'id': '../../other-user'}, {'features': {'samples': -1}}])
def test_invalid_diagnostics_are_rejected(change):
    with pytest.raises(ValidationError):
        MotionDiagnosticBatch(records=[record(**change)])


def test_batches_cannot_grow_without_bound():
    with pytest.raises(ValidationError):
        MotionDiagnosticBatch(records=[record()]*49)


def test_context_event_preserves_monotonic_and_upload_timing():
    timing = {k: record()[k] for k in ('boot_count', 'observed_elapsed_ms', 'received_elapsed_ms', 'delivery_delay_ms')}
    event = ContextEventRequest(event_type='ACTIVITY_SAMPLE', telemetry_diagnostics={
        **timing, 'upload_elapsed_ms': 2000, 'upload_delay_ms': 999})
    assert event.model_dump(mode='json')['telemetry_diagnostics']['upload_delay_ms'] == 999


def test_history_requires_a_bounded_timezone_aware_window(client):
    api, _ = client
    response = api.get('/motion-diagnostics', params={'start_at': '2026-10-12T00:00:00',
        'end_at': '2026-10-13T00:00:00+05:30'})
    assert response.status_code == 422


def test_collection_is_scoped_to_authenticated_user(monkeypatch):
    fs = MagicMock(is_available=True)
    monkeypatch.setattr(routes, 'FirestoreService', lambda: fs)
    routes.collection('account-a')
    fs._db.collection.assert_called_once_with('users')
    fs._db.collection.return_value.document.assert_called_once_with('account-a')
    fs._db.collection.return_value.document.return_value.collection.assert_called_once_with('motion_diagnostics')
