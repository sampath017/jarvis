import base64
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from src.services import background_tasks as tasks

def configure(monkeypatch):
    monkeypatch.setenv('JARVIS_TASK_QUEUE','projects/p/locations/l/queues/q')
    monkeypatch.setenv('JARVIS_SERVICE_URL','https://service.example')
    monkeypatch.setenv('JARVIS_TASK_SERVICE_ACCOUNT','worker@p.iam.gserviceaccount.com')

def test_cloud_task_dispatch_is_disabled_even_with_legacy_environment(monkeypatch):
    configure(monkeypatch)
    worker = tasks.BackgroundTasks()
    assert worker.configured is False
    with pytest.raises(RuntimeError, match='removed'):
        worker.enqueue('command', {'uid': 'u'}, 'same-key')


def test_internal_task_rejects_untrusted_identity(monkeypatch):
    configure(monkeypatch)
    with pytest.raises(HTTPException): tasks.verify_task_identity(None)
    monkeypatch.setattr(tasks.id_token,'verify_oauth2_token',lambda *a,**k: {'email':'other','email_verified':True})
    with pytest.raises(HTTPException) as error: tasks.verify_task_identity('Bearer token')
    assert error.value.status_code==403
    monkeypatch.setattr(tasks.id_token,'verify_oauth2_token',lambda *a,**k: {'email':'worker@p.iam.gserviceaccount.com','email_verified':True})
    tasks.verify_task_identity('Bearer token')

def test_reminders_do_not_enqueue_cloud_wakeups(monkeypatch):
    configure(monkeypatch)
    worker = tasks.BackgroundTasks()
    worker.enqueue = Mock()
    reminder = {'id': 'r', 'status': 'ACTIVE', 'due_at': (datetime.now(timezone.utc)+timedelta(days=60)).isoformat()}
    worker.schedule_reminder('u', reminder)
    worker.enqueue.assert_not_called()
