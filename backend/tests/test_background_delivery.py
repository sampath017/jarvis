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

def test_task_is_durable_authenticated_and_idempotent(monkeypatch):
    configure(monkeypatch)
    session=Mock(); session.post.return_value.status_code=409
    transport=Mock(); transport.__enter__=Mock(return_value=session); transport.__exit__=Mock(return_value=False)
    monkeypatch.setattr(tasks.google.auth,'default',lambda **_: (None,None))
    monkeypatch.setattr(tasks,'AuthorizedSession',lambda _: transport)
    worker=tasks.BackgroundTasks()
    worker.enqueue('command',{'uid':'u','request_id':'one'},'same-key')
    first=session.post.call_args.kwargs['json']['task']
    worker.enqueue('command',{'uid':'u','request_id':'one'},'same-key')
    assert first['name']==session.post.call_args.kwargs['json']['task']['name']
    assert first['dispatchDeadline']=='900s'
    assert first['httpRequest']['oidcToken']['audience']=='https://service.example'
    assert json.loads(base64.b64decode(first['httpRequest']['body']))['request_id']=='one'
    session.post.return_value.raise_for_status.assert_not_called()

def test_internal_task_rejects_untrusted_identity(monkeypatch):
    configure(monkeypatch)
    with pytest.raises(HTTPException): tasks.verify_task_identity(None)
    monkeypatch.setattr(tasks.id_token,'verify_oauth2_token',lambda *a,**k: {'email':'other','email_verified':True})
    with pytest.raises(HTTPException) as error: tasks.verify_task_identity('Bearer token')
    assert error.value.status_code==403
    monkeypatch.setattr(tasks.id_token,'verify_oauth2_token',lambda *a,**k: {'email':'worker@p.iam.gserviceaccount.com','email_verified':True})
    tasks.verify_task_identity('Bearer token')

def test_future_reminder_schedules_bounded_wakeup_and_inactive_does_not(monkeypatch):
    configure(monkeypatch)
    worker=tasks.BackgroundTasks(); worker.enqueue=Mock()
    reminder={'id':'r','status':'ACTIVE','due_at':(datetime.now(timezone.utc)+timedelta(days=60)).isoformat()}
    worker.schedule_reminder('u',reminder)
    assert worker.enqueue.call_args.args[0]=='reminder'
    assert worker.enqueue.call_args.args[3] < datetime.now(timezone.utc)+timedelta(days=29)
    worker.enqueue.reset_mock()
    worker.schedule_reminder('u',{**reminder,'status':'COMPLETED'})
    worker.enqueue.assert_not_called()
