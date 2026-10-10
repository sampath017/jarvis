from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from test_semantic_context import _FakeFirestore
from src.services.firestore_service import FirestoreService
from src.services.database import DatabaseService
from src.services.activity_reminder_timers import ActivityReminderTimers
from src.backend.context_automation import ContextAutomationService
from src.cloud.tier2_agent_tools import build_tier2_tools


@pytest.fixture
def setup(tmp_path):
    now = datetime.now(timezone.utc)
    db = DatabaseService(tmp_path / 'timers.db')
    fs = object.__new__(FirestoreService)
    fs._db = _FakeFirestore()
    reminder = db.create_reminder('u', {'id': 'r', 'title': 'Drink water', 'activity': 'WALKING',
        'activity_delay_seconds': 600, 'created_at': (now-timedelta(hours=1)).isoformat(), 'status': 'ACTIVE'})
    fs._db.collection('reminders').document('r').set(reminder)
    # SQLite supplies defaults absent from old Firestore records.
    reminder = db.get_reminder('u', 'r')
    tasks = Mock(configured=True)
    timers = ActivityReminderTimers(fs, tasks)
    event = {'event_id': 'walk-start', 'activity': 'WALKING', 'event_type': 'ACTIVITY_ENTER',
             'transition': 'ENTER', 'occurred_at': now.isoformat()}
    return now, db, fs, reminder, tasks, timers, event


def test_durable_timer_is_stable_across_duplicate_starts_and_worker_restarts(setup):
    now, db, fs, reminder, tasks, timers, event = setup
    timers.arm('u', reminder, event, now)
    original = tasks.enqueue.call_args
    ActivityReminderTimers(fs, tasks).arm('u', reminder, {**event, 'event_id': 'duplicate'}, now+timedelta(seconds=1))
    assert tasks.enqueue.call_args == original
    assert original.args[3] == now+timedelta(minutes=10)
    assert db.get_reminder('u', 'r')['status'] == 'ACTIVE'


def test_delivery_fires_once_at_deadline_without_new_phone_events(setup):
    now, db, fs, reminder, tasks, timers, event = setup
    timers.arm('u', reminder, event, now)
    timer_id = tasks.enqueue.call_args.args[1]['timer_id']
    service = ContextAutomationService(db, cloud=fs)
    with pytest.raises(RuntimeError, match='before'):
        timers.deliver('u', 'r', timer_id, service, now+timedelta(minutes=9))
    assert timers.deliver('u', 'r', timer_id, service, now+timedelta(minutes=10))
    assert not timers.deliver('u', 'r', timer_id, service, now+timedelta(minutes=11))
    assert fs._db.collection('reminders').document('r').get().to_dict()['status'] == 'COMPLETED'
    notices = list(fs._user_collection('u', 'notifications').stream())
    assert len(notices) == 1 and '10 minutes after' in notices[0].to_dict()['body']


@pytest.mark.parametrize('patch', [{'status':'PAUSED'}, {'status':'DELETED'}, {'activity_delay_seconds':1200}, {'activity':'RUNNING'}])
def test_changed_or_cancelled_policy_invalidates_old_timer(setup, patch):
    now, db, fs, reminder, tasks, timers, event = setup
    timers.arm('u', reminder, event, now)
    timer_id = tasks.enqueue.call_args.args[1]['timer_id']
    fs._db.collection('reminders').document('r').set(patch, merge=True)
    assert not timers.deliver('u', 'r', timer_id, ContextAutomationService(db, cloud=fs), now+timedelta(hours=1))


def test_late_samples_and_exit_cannot_arm_a_timer(setup):
    now, db, fs, reminder, tasks, timers, event = setup
    timers.arm('u', reminder, event, now-timedelta(minutes=6))
    timers.arm('u', reminder, {**event,'event_type':'ACTIVITY_SAMPLE'}, now)
    timers.arm('u', reminder, {**event,'transition':'EXIT'}, now)
    tasks.enqueue.assert_not_called()


def test_failed_enqueue_is_recoverable_without_resetting_deadline(setup):
    now, db, fs, reminder, tasks, timers, event = setup
    tasks.enqueue.side_effect = RuntimeError('temporary network failure')
    with pytest.raises(RuntimeError):
        timers.arm('u', reminder, event, now)
    tasks.enqueue.side_effect = None
    timers.reconcile('u', reminder)
    assert tasks.enqueue.call_args.args[3] == now+timedelta(minutes=10)


def test_existing_immediate_reminder_without_delay_field_still_fires(setup):
    now, db, fs, reminder, tasks, timers, event = setup
    saved = {k:v for k,v in reminder.items() if k != 'activity_delay_seconds'}
    fs._db.collection('reminders').document('r').set(saved)
    db.create_reminder('u', saved)
    assert len(ContextAutomationService(db, cloud=fs).process_context_event('u', event)) == 1


def test_tools_store_delay_and_zero_removes_it(tmp_path):
    db = DatabaseService(tmp_path / 'tools.db')
    tools = {t.name:t for t in build_tier2_tools(db, 'u')}
    reply = tools['create_reminder'].invoke({'title':'Drink water','activity':'WALKING','activity_delay_seconds':600})
    assert 'Successfully created' in reply
    saved, = db.list_reminders('u')
    assert saved['activity_delay_seconds'] == 600
    reply = tools['update_reminder'].invoke({'reminder_id':saved['id'],'activity_delay_seconds':0})
    assert 'Successfully updated' in reply
    assert db.get_reminder('u', saved['id'])['activity_delay_seconds'] == 0
