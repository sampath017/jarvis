from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from src.services.device_context import DeviceContext, dispatch_device_action


def test_background_location_dispatch_bypasses_flutter(monkeypatch):
    native = Mock()
    native.request_and_wait.return_value = {'status': 'ok', 'gps': {'latitude': 1, 'longitude': 2}}
    monkeypatch.setattr('src.services.device_context.DeviceContext', lambda: native)
    fallback, check = Mock(), Mock()
    assert dispatch_device_action('u', {'operation': 'location_read'}, fallback, check)['status'] == 'ok'
    fallback.assert_not_called()
    check.assert_called_once()


def test_unrelated_writes_do_not_wake_sensors(monkeypatch):
    native = Mock(side_effect=AssertionError('No sensor request for a write'))
    monkeypatch.setattr('src.services.device_context.DeviceContext', native)
    fallback = Mock(return_value={'status': 'ok'})
    dispatch_device_action('u', {'operation': 'file_save'}, fallback, Mock())
    fallback.assert_called_once()


@pytest.fixture
def context_store():
    from src.services.sqlite_store import SqlStore
    from src.services.record_store import RecordStore
    sql = SqlStore(':memory:')
    service = DeviceContext.__new__(DeviceContext)
    service.fs = RecordStore.from_sql(sql)
    yield service, sql
    sql.db.close()


@pytest.mark.parametrize('offset,expected', [(0, True), (-300, False)])
def test_receipt_requires_fresh_location(context_store, offset, expected):
    service, sql = context_store
    now = datetime.now(timezone.utc)
    sql.put('context_requests', 'r', {'status': 'PENDING',
        'expires_at': (now + timedelta(seconds=90)).isoformat()}, uid='u')
    service.receive('u', {'context_request_id': 'r', 'event_id': 'e', 'location': {
        'latitude': 1, 'longitude': 2, 'timestamp': (now + timedelta(seconds=offset)).isoformat()}})
    saved = sql.get('context_requests', 'r', uid='u')
    assert saved['status'] == 'COMPLETED' and bool(saved['gps']) == expected


def test_expired_wake_receipt_cannot_complete_request(context_store):
    service, sql = context_store
    sql.put('context_requests', 'r', {'status': 'PENDING', 'expires_at': '2020-01-01T00:00:00+00:00'}, uid='u')
    before = sql.get('context_requests', 'r', uid='u')
    service.receive('u', {'context_request_id': 'r'})
    assert sql.get('context_requests', 'r', uid='u') == before


def test_receipt_cannot_complete_another_owners_request(context_store):
    service, sql = context_store
    sql.put('context_requests', 'r', {'status': 'PENDING',
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}, uid='u')
    service.receive('different-user', {'context_request_id': 'r'})
    assert sql.get('context_requests', 'r', uid='u')['status'] == 'PENDING'
