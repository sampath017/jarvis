"""Legacy task authentication; new work uses the active API process/local alarms."""
import os
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from fastapi import HTTPException

class BackgroundTasks:
    @property
    def configured(self):
        return False

    def enqueue(self, kind, payload, key, schedule_time=None):
        raise RuntimeError('Cloud task scheduling was removed; use Android local alarms.')

    def schedule_reminder(self, uid, reminder):
        # Android schedules persisted local reminders through AlarmManager.
        return None


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
