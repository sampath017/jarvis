"""Cloud Google connection controls require a private capability, not fixed UID."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...services.background_tasks import verify_task_identity
from ...services.server_google_auth import ServerGoogleAuth, capability_owner
import hashlib
import re
from ...services.scheduled_google_actions import ScheduledGoogleActions

router = APIRouter(tags=['cloud-google-actions'])


def owner(x_calendar_session: Annotated[str, Header()] = ''):
    return capability_owner(x_calendar_session)


def scheduler_service():
    auth = ServerGoogleAuth()
    try:
        yield ScheduledGoogleActions(auth=auth)
    finally:
        auth.client.close()


@router.get('/google-server/status')
def status(connection: Annotated[str, Depends(owner)]):
    auth = ServerGoogleAuth()
    try:
        return auth.status(connection)
    finally:
        auth.client.close()


@router.post('/google-server/connect')
def connect(connection: Annotated[str, Depends(owner)], x_file_memory_session: Annotated[str, Header()] = ''):
    auth = ServerGoogleAuth()
    try:
        file_owner = hashlib.sha256(x_file_memory_session.encode()).hexdigest() if re.fullmatch(r'[a-f0-9]{64}', x_file_memory_session) else None
        return auth.start(connection, file_owner)
    finally:
        auth.client.close()


@router.get('/google-server/callback', response_class=HTMLResponse)
def callback(state: Annotated[str, Query(min_length=20, max_length=200)], code: Annotated[str, Query(min_length=1, max_length=4096)]):
    auth = ServerGoogleAuth()
    try:
        auth.complete(state, code)
        return '<h1>Jarvis cloud access connected</h1><p>You can return to Jarvis. Authorized cloud actions can now run while your phone is offline.</p>'
    finally:
        auth.client.close()


@router.delete('/google-server/connection')
def disconnect(connection: Annotated[str, Depends(owner)]):
    auth = ServerGoogleAuth()
    try:
        return auth.disconnect(connection)
    finally:
        auth.client.close()


class ScheduledActionRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    title: str = Field(default='Scheduled Google action', max_length=200)
    execute_at: str = Field(min_length=1, max_length=80)
    action: dict = Field(default_factory=dict)


@router.get('/google-server/schedules')
def schedules(connection: Annotated[str, Depends(owner)], service: Annotated[ScheduledGoogleActions, Depends(scheduler_service)]):
    return service.list(connection)


@router.post('/google-server/schedules')
def schedule(body: ScheduledActionRequest, connection: Annotated[str, Depends(owner)], service: Annotated[ScheduledGoogleActions, Depends(scheduler_service)]):
    try:
        return service.create(connection, body.request_id, body.action, body.execute_at, body.title)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete('/google-server/schedules/{action_id}')
def cancel(action_id: str, connection: Annotated[str, Depends(owner)], service: Annotated[ScheduledGoogleActions, Depends(scheduler_service)]):
    return service.cancel(connection, action_id)


@router.post('/internal/background/google-action')
def execute(body: dict, service: Annotated[ScheduledGoogleActions, Depends(scheduler_service)], authorization: Annotated[str | None, Header()] = None):
    verify_task_identity(authorization)
    return service.execute(body['owner'], body['action_id'])


@router.post('/internal/background/google-reconcile')
def reconcile(service: Annotated[ScheduledGoogleActions, Depends(scheduler_service)], authorization: Annotated[str | None, Header()] = None):
    verify_task_identity(authorization)
    return service.reconcile()
