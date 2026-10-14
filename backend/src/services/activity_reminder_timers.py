"""Convert a verified activity start into an Android-owned one-shot clock alarm."""
from datetime import datetime, timedelta, timezone


class ActivityReminderTimers:
    def __init__(self, records):
        self.records = records

    def arm(self, uid, reminder, event, occurred_at):
        if not self.records or not self.records.is_available:
            raise RuntimeError('Activity timer records are unavailable')
        if (event.get('event_type') not in {'ACTIVITY_ENTER', 'ACTIVITY_TRANSITION'}
                or event.get('transition') != 'ENTER' or event.get('activity') != reminder.get('activity')):
            return
        now = datetime.now(timezone.utc)
        if not 0 <= (now - occurred_at).total_seconds() <= 300:
            return
        delay = int(reminder.get('activity_delay_seconds') or 0)
        if not 1 <= delay <= 86400 or not reminder.get('one_shot', True):
            return
        from .database import DatabaseService
        updated = {**reminder, 'due_at': (occurred_at + timedelta(seconds=delay)).isoformat(),
                   'activity': None, 'activity_delay_seconds': 0,
                   'latitude': None, 'longitude': None, 'location_name': None,
                   'updated_at': now.isoformat()}
        DatabaseService().create_reminder(uid, updated)
        if not self.records.save_reminder(reminder['id'], updated):
            raise RuntimeError('Activity countdown could not be returned to Android')
