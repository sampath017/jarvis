from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.backend.context_automation import ContextAutomationService
from src.cloud.tier2_agent_tools import build_tier2_tools
from src.models.schemas import ReminderCreateRequest, ReminderPatchRequest
from src.services.database import DatabaseService
from src.services.firestore_service import FirestoreService
from test_semantic_context import _FakeFirestore


@pytest.mark.parametrize('mode', ['notification', 'alarm', 'in_app_call'])
def test_delivery_survives_storage_and_outbox_retry(tmp_path, mode):
    db = DatabaseService(tmp_path / 'alerts.db')
    due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    request = ReminderCreateRequest(title='Important task', due_at=due, delivery_mode=mode)
    saved = db.create_reminder('u', request.model_dump(mode='json'))
    db = DatabaseService(tmp_path / 'alerts.db')
    assert db.get_reminder('u', saved['id'])['delivery_mode'] == mode
    service = ContextAutomationService(db)
    service.process_due_reminders()
    service.process_due_reminders()
    notices = db.list_notifications('u')
    assert len(notices) == 1
    assert notices[0]['payload']['delivery_mode'] == mode
    assert notices[0]['payload']['alarm_due_at'] == saved['due_at']


def test_chat_tools_do_not_merge_different_alert_modes(tmp_path):
    db = DatabaseService(tmp_path / 'alerts.db')
    tools = {t.name: t for t in build_tier2_tools(uid='u', db=db)}
    for mode in ['notification', 'in_app_call']:
        result = tools['create_reminder'].invoke({'title': 'Drink water', 'due_at': 'in 20 minutes', 'delivery_mode': mode})
        assert 'Error' not in result
    records = db.list_reminders('u')
    assert {r['delivery_mode'] for r in records} == {'notification', 'in_app_call'}
    call = next(r for r in records if r['delivery_mode'] == 'in_app_call')
    tools['update_reminder'].invoke({'reminder_id': call['id'], 'title': 'Water now'})
    assert db.get_reminder('u', call['id'])['delivery_mode'] == 'in_app_call'
    tools['update_reminder'].invoke({'reminder_id': call['id'], 'delivery_mode': 'alarm'})
    assert db.get_reminder('u', call['id'])['delivery_mode'] == 'alarm'


def test_invalid_telephone_delivery_is_rejected():
    with pytest.raises(ValidationError):
        ReminderCreateRequest(title='Call me', activity='WALKING', delivery_mode='telephone')
    with pytest.raises(ValidationError):
        ReminderPatchRequest(delivery_mode=None)
    assert ReminderPatchRequest(title='Change title').model_dump(exclude_unset=True) == {'title': 'Change title'}


def test_stale_worker_cannot_emit_old_delivery_mode(tmp_path):
    db = DatabaseService(tmp_path / 'alerts.db')
    fs = object.__new__(FirestoreService)
    fs._db = _FakeFirestore()
    r = db.create_reminder('u', {'id': 'r', 'title': 'Water', 'activity': 'WALKING', 'delivery_mode': 'alarm'})
    fs._db.collection('reminders').document('r').set({**r, 'delivery_mode': 'notification'})
    notice, created = ContextAutomationService(db, cloud=fs)._fire_reminder(
        'u', r, {'event_id': 'walk'}, datetime.now(timezone.utc), 'ACTIVITY_ENTER')
    assert not created
    assert not notice
