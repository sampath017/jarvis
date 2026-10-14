"""Activity countdowns use the phone SQL delta and Android's local clock alarm."""
from datetime import datetime, timedelta, timezone
import pytest
from src.services.mobile_scope import MobileScope, current
from src.services.record_store import RecordStore
from src.services.database import DatabaseService
from src.services.activity_reminder_timers import ActivityReminderTimers
from src.backend.context_automation import ContextAutomationService
from src.cloud.agent_tools import build_agent_tools


@pytest.fixture
def setup():
    now = datetime.now(timezone.utc)
    scope = MobileScope()
    token = current.set(scope)
    try:
        scope.seed({'records': {'reminders': [{'id': 'r', 'title': 'Drink water', 'activity': 'WALKING',
            'activity_delay_seconds': 600, 'created_at': (now - timedelta(hours=1)).isoformat(),
            'updated_at': 'phone-v1', 'status': 'ACTIVE', 'one_shot': True}]}})
        db, records = DatabaseService(), RecordStore()
        event = {'event_id': 'walk-start', 'activity': 'WALKING', 'event_type': 'ACTIVITY_ENTER',
                 'transition': 'ENTER', 'occurred_at': now.isoformat()}
        yield now, db, records, db.get_reminder('jarvis_local_user', 'r'), event, scope
    finally:
        current.reset(token)
        scope.release()


@pytest.mark.parametrize('activity', ['WALKING', 'IN_VEHICLE'])
@pytest.mark.parametrize('mode', ['notification', 'alarm', 'in_app_call'])
def test_fresh_activity_returns_same_id_as_phone_clock_alarm(setup, activity, mode):
    now, db, records, reminder, event, scope = setup
    reminder = {**reminder, 'activity': activity, 'delivery_mode': mode,
                'latitude': 12, 'longitude': 80, 'location_name': 'Office'}
    ActivityReminderTimers(records).arm('jarvis_local_user', reminder, {**event, 'activity': activity}, now)
    updated, = scope.changes()['records']['reminders']
    assert updated['id'] == 'r' and updated['title'] == reminder['title']
    assert updated['delivery_mode'] == mode and updated['status'] == 'ACTIVE'
    assert datetime.fromisoformat(updated['due_at']) == now + timedelta(minutes=10)
    assert updated['activity'] is None and updated['activity_delay_seconds'] == 0
    assert updated['latitude'] is None and updated['longitude'] is None and updated['location_name'] is None
    assert scope.changes()['notifications'] == []


def test_duplicate_start_does_not_reset_armed_phone_deadline(setup):
    now, db, records, reminder, event, scope = setup
    service = ContextAutomationService(db, cloud=records)
    service.process_context_event('jarvis_local_user', event)
    due = db.get_reminder('jarvis_local_user', 'r')['due_at']
    service.process_context_event('jarvis_local_user', {**event, 'event_id': 'duplicate'})
    assert db.get_reminder('jarvis_local_user', 'r')['due_at'] == due
    assert len(scope.changes()['records']['reminders']) == 1


@pytest.mark.parametrize('event_type,transition,age', [
    ('ACTIVITY_SAMPLE', 'ENTER', 0), ('ACTIVITY_ENTER', 'EXIT', 0), ('ACTIVITY_ENTER', 'ENTER', 360),
])
def test_late_samples_and_exit_cannot_arm_phone_timer(setup, event_type, transition, age):
    now, db, records, reminder, event, scope = setup
    ActivityReminderTimers(records).arm('jarvis_local_user', reminder,
        {**event, 'event_type': event_type, 'transition': transition}, now - timedelta(seconds=age))
    assert db.get_reminder('jarvis_local_user', 'r')['due_at'] is None
    assert scope.changes()['records']['reminders'] == []


def test_paused_policy_is_not_armed_by_context_processing(setup):
    now, db, records, reminder, event, scope = setup
    db.update_reminder('jarvis_local_user', 'r', {'status': 'PAUSED'})
    records.save_reminder('r', {**reminder, 'status': 'PAUSED'})
    ContextAutomationService(db, cloud=records).process_context_event('jarvis_local_user', event)
    assert db.get_reminder('jarvis_local_user', 'r')['due_at'] is None


def test_tools_store_delay_and_zero_removes_it(setup):
    now, db, records, reminder, event, scope = setup
    tools = {tool.name: tool for tool in build_agent_tools(db, 'jarvis_local_user')}
    reply = tools['create_reminder'].invoke({'title': 'Stretch', 'activity': 'WALKING', 'activity_delay_seconds': 600})
    assert 'Successfully created' in reply
    saved = next(row for row in db.list_reminders('jarvis_local_user') if row['title'] == 'Stretch')
    assert saved['activity_delay_seconds'] == 600
    reply = tools['update_reminder'].invoke({'reminder_id': saved['id'], 'activity_delay_seconds': 0})
    assert 'Successfully updated' in reply
    assert db.get_reminder('jarvis_local_user', saved['id'])['activity_delay_seconds'] == 0
