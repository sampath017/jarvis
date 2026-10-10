"""Durable one-shot countdowns started by a verified activity transition.

These measure elapsed time after a start, not uninterrupted exercise duration.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from .background_tasks import BackgroundTasks


POLICY_FIELDS = ('activity', 'activity_delay_seconds', 'location_name', 'latitude',
                 'longitude', 'radius_m', 'due_at', 'one_shot', 'created_at')


def policy_key(reminder):
    values = {k: reminder.get(k) or None for k in POLICY_FIELDS}
    values.update(one_shot=reminder.get('one_shot', True), radius_m=float(reminder.get('radius_m') or 100),
                  activity_delay_seconds=int(reminder.get('activity_delay_seconds') or 0))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


class ActivityReminderTimers:
    def __init__(self, cloud, tasks=None):
        self.cloud = cloud
        self.tasks = tasks or BackgroundTasks()

    def arm(self, uid, reminder, event, occurred_at):
        if not self.cloud or not self.tasks.configured:
            raise RuntimeError('Durable activity timer delivery is unavailable')
        if (event.get('event_type') not in {'ACTIVITY_ENTER', 'ACTIVITY_TRANSITION'}
                or event.get('transition') != 'ENTER' or event.get('activity') != reminder.get('activity')):
            return
        now = datetime.now(timezone.utc)
        if not 0 <= (now-occurred_at).total_seconds() <= 300:
            return
        delay = int(reminder.get('activity_delay_seconds') or 0)
        if not 1 <= delay <= 86400 or not reminder.get('one_shot', True):
            return
        ref = self.cloud._user_collection(uid, 'activity_reminder_timers').document(reminder['id'])
        saved_ref = self.cloud._db.collection('reminders').document(reminder['id'])
        key = policy_key(reminder)
        def reserve(tx=None):
            saved = (saved_ref.get(transaction=tx) if tx else saved_ref.get()).to_dict() or {}
            previous = (ref.get(transaction=tx) if tx else ref.get()).to_dict() or {}
            if saved.get('uid') != uid or saved.get('status') != 'ACTIVE' or policy_key(saved) != key:
                return None
            if previous.get('policy_key') == key and previous.get('status') in {'PENDING', 'COMPLETED'}:
                return previous if previous['status'] == 'PENDING' else None
            timer_id = hashlib.sha256(f"{uid}:{reminder['id']}:{key}:{event['event_id']}".encode()).hexdigest()
            value = {'timer_id': timer_id, 'policy_key': key, 'status': 'PENDING',
                     'started_at': occurred_at.isoformat(), 'due_at': (occurred_at+timedelta(seconds=delay)).isoformat()}
            if tx:
                tx.set(ref, value)
            else:
                ref.set(value)
            return value
        timer = firestore.transactional(reserve)(self.cloud._db.transaction()) if hasattr(self.cloud._db, 'transaction') else reserve()
        if timer:
            # Retry the same named task after a crash between reservation and
            # enqueue. Cloud Tasks treats duplicate task names as success.
            self.tasks.enqueue('activity-reminder', {'uid': uid, 'reminder_id': reminder['id'],
                'timer_id': timer['timer_id']}, 'activity-timer:'+timer['timer_id'],
                datetime.fromisoformat(timer['due_at']))

    def reconcile(self, uid, reminder):
        if not reminder.get('activity_delay_seconds') or reminder.get('status') != 'ACTIVE':
            return
        timer = self.cloud._user_collection(uid, 'activity_reminder_timers').document(reminder['id']).get().to_dict() or {}
        if timer.get('status') == 'PENDING' and timer.get('policy_key') == policy_key(reminder):
            self.tasks.enqueue('activity-reminder', {'uid': uid, 'reminder_id': reminder['id'],
                'timer_id': timer['timer_id']}, 'activity-timer:'+timer['timer_id'], datetime.fromisoformat(timer['due_at']))

    def deliver(self, uid, reminder_id, timer_id, automation, now=None):
        ref = self.cloud._user_collection(uid, 'activity_reminder_timers').document(reminder_id)
        timer = ref.get().to_dict() or {}
        reminder = self.cloud._db.collection('reminders').document(reminder_id).get().to_dict() or {}
        if (timer.get('timer_id') != timer_id or timer.get('status') != 'PENDING'
                or reminder.get('uid') != uid or reminder.get('status') != 'ACTIVE'
                or policy_key(reminder) != timer.get('policy_key')):
            return False
        now = now or datetime.now(timezone.utc)
        if now < datetime.fromisoformat(timer['due_at']):
            raise RuntimeError('Activity timer delivered before its due time')
        event = {'event_id': 'activity-timer:'+timer_id, 'occurred_at': now.isoformat()}
        delay = int(reminder['activity_delay_seconds'])
        elapsed = f'{delay // 60} minutes' if delay % 60 == 0 else f'{delay} seconds'
        reminder = {**reminder, 'body': f"{elapsed} after the detected {reminder['activity'].lower()} start. {reminder['title']}"}
        notification, created = automation._fire_reminder(uid, reminder, event, now, 'ACTIVITY_START_DELAY')
        if notification:
            def complete(tx=None):
                latest = (ref.get(transaction=tx) if tx else ref.get()).to_dict() or {}
                if latest.get('timer_id') != timer_id:
                    return
                if tx:
                    tx.set(ref, {'status': 'COMPLETED'}, merge=True)
                else:
                    ref.set({'status': 'COMPLETED'}, merge=True)
            if hasattr(self.cloud._db, 'transaction'):
                firestore.transactional(complete)(self.cloud._db.transaction())
            else:
                complete()
        return created
