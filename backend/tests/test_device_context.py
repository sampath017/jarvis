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


@pytest.mark.parametrize('offset,expected', [(0, True), (-300, False)])
def test_receipt_requires_fresh_location(offset, expected):
    service = DeviceContext.__new__(DeviceContext)
    service.fs = Mock()
    ref = service.fs._user_collection.return_value.document.return_value
    now = datetime.now(timezone.utc)
    ref.get.return_value = Mock(exists=True, to_dict=lambda: {'expires_at': (now+timedelta(seconds=90)).isoformat()})
    service.receive('u', {'context_request_id': 'r', 'event_id': 'e', 'location': {
        'latitude': 1, 'longitude': 2, 'timestamp': (now+timedelta(seconds=offset)).isoformat()}})
    saved = ref.update.call_args.args[0]
    assert bool(saved['gps']) == expected


def test_expired_wake_receipt_cannot_complete_request():
    service = DeviceContext.__new__(DeviceContext)
    service.fs = Mock()
    ref = service.fs._user_collection.return_value.document.return_value
    ref.get.return_value = Mock(exists=True, to_dict=lambda: {'expires_at': '2020-01-01T00:00:00+00:00'})
    service.receive('u', {'context_request_id': 'r'})
    ref.update.assert_not_called()
