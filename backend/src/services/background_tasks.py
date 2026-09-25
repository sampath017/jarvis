"""Authenticated Cloud Tasks keep work alive independently of the phone connection."""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import id_token
from fastapi import HTTPException

class BackgroundTasks:
    @property
    def configured(self):
        return bool(os.getenv('JARVIS_TASK_QUEUE'))

    def enqueue(self, kind, payload, key, schedule_time=None):
        queue = os.getenv('JARVIS_TASK_QUEUE', '')
        base = os.getenv('JARVIS_SERVICE_URL', '').rstrip('/')
        account = os.getenv('JARVIS_TASK_SERVICE_ACCOUNT', '')
        if not queue or not base or not account:
            raise RuntimeError('Background task delivery is not configured')
        task_id = hashlib.sha256(key.encode()).hexdigest()
        task = {
            'name': queue + '/tasks/' + task_id,
            'dispatchDeadline': '900s',
            'httpRequest': {'httpMethod': 'POST', 'url': base + '/internal/background/' + kind,
                'headers': {'Content-Type': 'application/json'},
                'body': base64.b64encode(json.dumps(payload).encode()).decode(),
                'oidcToken': {'serviceAccountEmail': account, 'audience': base}},
        }
        if schedule_time and schedule_time > datetime.now(timezone.utc):
            task['scheduleTime'] = schedule_time.isoformat()
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        with AuthorizedSession(credentials) as session:
            response = session.post('https://cloudtasks.googleapis.com/v2/' + queue + '/tasks', json={'task': task}, timeout=15)
            if response.status_code != 409:
                response.raise_for_status()

    def schedule_reminder(self, uid, reminder):
        if not self.configured or reminder.get('status', 'ACTIVE') != 'ACTIVE' or not reminder.get('due_at'):
            return
        due = datetime.fromisoformat(str(reminder['due_at']).replace('Z', '+00:00'))
        if due.tzinfo is None:
            raise ValueError('Reminder time needs a timezone')
        # Wake at least every 28 days for reminders outside Tasks' scheduling horizon.
        now = datetime.now(timezone.utc)
        segment = max(0, int((due - now).total_seconds() // (28 * 86400)))
        scheduled = min(due, now + timedelta(days=28))
        key = f"due:{uid}:{reminder['id']}:{reminder['due_at']}:{reminder.get('updated_at', '')}:{segment}"
        self.enqueue('reminder', {'uid': uid, 'reminder_id': reminder['id']}, key, scheduled)



def verify_task_identity(authorization):
    account = os.getenv('JARVIS_TASK_SERVICE_ACCOUNT')
    audience = os.getenv('JARVIS_SERVICE_URL', '').rstrip('/')
    if not account or not audience or not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Authenticated background task required')
    try:
        claims = id_token.verify_oauth2_token(authorization[7:], Request(), audience=audience)
    except Exception as error:
        raise HTTPException(401, 'Invalid background task token') from error
    if claims.get('email') != account or not claims.get('email_verified'):
        raise HTTPException(403, 'Background task identity not allowed')
