import copy
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from src.services.server_google_auth import ServerGoogleAuth, capability_owner, SCOPES
from src.services.server_google_actions import ServerGoogleActions, event_payload
from src.services.scheduled_google_actions import ScheduledGoogleActions, validate_action
from src.backend.command_execution import CommandExecution, execution
from src.cloud.calendar_tools import calendar_tools
from src.cloud.file_memory_tools import file_memory_tools

KEY = 'a' * 64
OWNER = hashlib.sha256(KEY.encode()).hexdigest()
EVENT = {'summary': 'Lokesh meet', 'start': {'dateTime': '2026-12-01T16:00:00+05:30'},
         'end': {'dateTime': '2026-12-01T17:00:00+05:30'}}


class Ref:
    def __init__(self, db, path): self.db, self.path = db, path
    def collection(self, name): return Ref(self.db, self.path + '/' + name)
    def document(self, name): return Ref(self.db, self.path + '/' + name)
    def get(self, transaction=None):
        return SimpleNamespace(to_dict=lambda: copy.deepcopy(self.db.rows.get(self.path)))
    def set(self, data): self.db.rows[self.path] = copy.deepcopy(data)
    def update(self, data): self.db.rows[self.path].update(copy.deepcopy(data))


class DB:
    def __init__(self): self.rows = {}
    def collection(self, name): return Ref(self, name)
    def transaction(self):
        return SimpleNamespace(set=lambda ref, data: ref.set(data), update=lambda ref, data: ref.update(data),
                               delete=lambda ref: self.rows.pop(ref.path, None))


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for name, value in {'JARVIS_GOOGLE_CLIENT_ID': 'demo-client', 'JARVIS_GOOGLE_CLIENT_SECRET': 'demo-secret',
                        'JARVIS_GOOGLE_TOKEN_KEY': Fernet.generate_key().decode(), 'JARVIS_SERVICE_URL': 'https://example.com',
                        'JARVIS_GOOGLE_ALLOWED_EMAIL': 'owner@example.com', 'JARVIS_GOOGLE_OWNER_HASH': OWNER}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr('src.services.sqlite_documents.transactional', lambda fn: lambda tx: fn(tx))


def auth_stub(db):
    return SimpleNamespace(db=db, ref=lambda owner: db.collection('google_connections').document(owner),
                           status=lambda owner: {'connected': True, 'email': 'owner@example.com'}, token=lambda owner: 'demo-access')


def test_private_pairing_cannot_use_fixed_uid_or_another_capability():
    assert capability_owner(KEY) == OWNER
    for key in ('jarvis_local_user', '', 'b' * 64):
        with pytest.raises(HTTPException): capability_owner(key)


def test_oauth_pkce_offline_grant_encrypted_and_state_one_use():
    db = DB()
    def handler(request):
        if request.url.host == 'oauth2.googleapis.com':
            assert b'code_verifier=' in request.content
            return httpx.Response(200, json={'access_token': 'demo-access', 'refresh_token': 'private-refresh', 'scope': ' '.join(SCOPES)})
        return httpx.Response(200, json={'email': 'owner@example.com', 'email_verified': True})
    auth = ServerGoogleAuth(db, httpx.Client(transport=httpx.MockTransport(handler)))
    link = auth.start(OWNER)
    query = parse_qs(urlparse(link['authorization_url']).query)
    assert query['access_type'] == ['offline'] and query['code_challenge_method'] == ['S256']
    assert 'code_verifier' not in query
    state = query['state'][0]
    auth.complete(state, 'one-use-code')
    record = auth.ref(OWNER).get().to_dict()
    assert 'private-refresh' not in str(record)
    assert auth.cipher().decrypt(record['encrypted_refresh_token'].encode()) == b'private-refresh'
    assert 'token' not in str(auth.status(OWNER))
    with pytest.raises(HTTPException): auth.complete(state, 'one-use-code')


def test_expired_state_does_not_exchange_credentials():
    db = DB(); client = Mock()
    auth = ServerGoogleAuth(db, client)
    state = parse_qs(urlparse(auth.start(OWNER)['authorization_url']).query)['state'][0]
    ref = db.collection('google_oauth_states').document(hashlib.sha256(state.encode()).hexdigest())
    ref.update({'expires_at': datetime.now(timezone.utc) - timedelta(seconds=1)})
    with pytest.raises(HTTPException): auth.complete(state, 'code')
    client.post.assert_not_called()


def test_revoked_refresh_marks_reconnect_without_google_action():
    db = DB()
    auth = ServerGoogleAuth(db, httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400, json={'error': 'invalid_grant'}))))
    auth.ref(OWNER).set({'status': 'connected', 'email': 'owner@example.com', 'scopes': ' '.join(SCOPES),
                       'encrypted_refresh_token': auth.cipher().encrypt(b'demo-refresh').decode()})
    with pytest.raises(HTTPException): auth.token(OWNER)
    assert auth.status(OWNER)['needs_reconnect']


@pytest.mark.parametrize('event', [
    {**EVENT, 'end': EVENT['start']},
    {**EVENT, 'start': {'dateTime': '2026-12-01T16:00:00'}},
    {**EVENT, 'start': {'date': '2026-12-01'}, 'end': EVENT['end']},
    {**EVENT, 'attendees': [{'email': 'bad'}]},
    {**EVENT, 'unexpected': True},
])
def test_invalid_calendar_arguments_rejected_before_write(event):
    with pytest.raises(ValueError): event_payload(event)


def test_calendar_create_receipt_prevents_duplicate_and_binds_arguments():
    db = DB(); requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'id': 'created', 'summary': 'Lokesh meet'})
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    action = {'operation': 'create', 'event': EVENT}
    assert service.dispatch(action, 'same-operation')['status'] == 'ok'
    assert service.dispatch(action, 'same-operation')['status'] == 'ok'
    assert len(requests) == 1
    with pytest.raises(HTTPException): service.dispatch({**action, 'event': {**EVENT, 'summary': 'changed'}}, 'same-operation')


def test_uncertain_create_reconciles_verified_deterministic_google_id():
    db = DB(); saved = {}
    def handler(request):
        if request.method == 'POST':
            import json
            saved.update(json.loads(request.content))
            raise httpx.ReadTimeout('response lost')
        return httpx.Response(200, json=saved)
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    action = {'operation': 'create', 'event': EVENT}
    with pytest.raises(httpx.ReadTimeout): service.dispatch(action, 'op')
    assert service.dispatch(action, 'op')['reconciled'] is True
    assert all(c in '0123456789abcdefghijklmnopqrstuv' for c in saved['id'])


def test_calendar_edit_uses_etag_and_refuses_conflict():
    db = DB(); writes = []
    def handler(request):
        if request.method == 'GET': return httpx.Response(200, json={**EVENT, 'etag': 'original'})
        writes.append(request)
        return httpx.Response(412)
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(HTTPException): service.dispatch({'operation': 'update', 'event_id': 'event', 'event': {'summary': 'changed'}}, 'edit')
    assert writes[0].headers['If-Match'] == 'original'


def test_scheduled_action_runs_without_phone_and_duplicate_callback_is_noop():
    db = DB(); executor = Mock(); executor.dispatch.return_value = {'status': 'ok', 'event_id': 'event'}
    tasks = Mock(); tasks.configured = True
    schedules = ScheduledGoogleActions(auth_stub(db), tasks, lambda owner: executor)
    schedules.notify = Mock()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = schedules.create(OWNER, 'schedule-id', {'operation': 'create', 'event': EVENT}, future)
    identifier = result['schedule']['id']
    schedules.ref(OWNER, identifier).update({'execute_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})
    assert schedules.execute(OWNER, identifier)['status'] == 'complete'
    schedules.execute(OWNER, identifier)
    executor.dispatch.assert_called_once()
    schedules.notify.assert_called_once()


def test_failed_enqueue_is_durable_and_not_reported_as_queued():
    db = DB(); tasks = Mock(); tasks.configured = True; tasks.enqueue.side_effect = RuntimeError('offline')
    schedules = ScheduledGoogleActions(auth_stub(db), tasks)
    with pytest.raises(HTTPException):
        schedules.create(OWNER, 'schedule-id', {'operation': 'create', 'event': EVENT}, (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    assert next(iter(db.rows.values()))['status'] == 'pending_queue'


def test_cancelled_schedule_never_executes_and_running_cannot_be_cancelled():
    db = DB(); executor = Mock(); tasks = Mock(); tasks.configured = True
    schedules = ScheduledGoogleActions(auth_stub(db), tasks, lambda owner: executor)
    result = schedules.create(OWNER, 'id', {'operation': 'create', 'event': EVENT}, (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    identifier = result['schedule']['id']
    schedules.cancel(OWNER, identifier)
    assert schedules.execute(OWNER, identifier)['status'] == 'ignored'
    executor.dispatch.assert_not_called()
    schedules.ref(OWNER, identifier).update({'status': 'running'})
    with pytest.raises(HTTPException): schedules.cancel(OWNER, identifier)


def test_cloud_tools_prefer_server_without_calling_phone():
    cloud = Mock(return_value={'status': 'ok'}); phone = Mock()
    context = CommandExecution(lambda _: None, calendar_dispatch=phone, approval_dispatch=phone, server_google_dispatch=cloud)
    token = execution.set(context)
    try:
        tools = {t.name: t for t in calendar_tools() + file_memory_tools()}
        tools['create_calendar_event'].invoke({'event': EVENT})
        tools['search_file_memories'].invoke({'query': 'report'})
        phone.assert_not_called()
        assert cloud.call_count == 2
    finally: execution.reset(token)


def test_schedule_rejects_arbitrary_operations():
    for operation in ('location_read', 'http_request', 'shell', 'approval'):
        with pytest.raises(ValueError): validate_action({'operation': operation})


def test_early_due_callback_is_retried_without_executing_or_reenqueuing():
    db = DB(); executor = Mock(); tasks = Mock(); tasks.configured = True
    schedules = ScheduledGoogleActions(auth_stub(db), tasks, lambda owner: executor)
    created = schedules.create(OWNER, 'id', {'operation': 'create', 'event': EVENT},
        (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    tasks.enqueue.reset_mock()
    with pytest.raises(HTTPException) as exc:
        schedules.execute(OWNER, created['schedule']['id'])
    assert exc.value.status_code == 503
    executor.dispatch.assert_not_called()
    tasks.enqueue.assert_not_called()


def test_drive_reads_enforce_download_bound_when_size_header_is_missing(monkeypatch):
    db = DB()
    def handler(request):
        if request.url.params.get('alt') == 'media':
            return httpx.Response(200, content=b'x' * 20_000_001)
        return httpx.Response(200, json={'id': 'file', 'name': 'data.txt', 'mimeType': 'text/plain'})
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(HTTPException) as exc:
        service.dispatch({'operation': 'file_analyze', 'file_id': 'file', 'question': 'Read it'}, 'read')
    assert exc.value.status_code == 413


def test_drive_original_is_not_moved_or_duplicated_when_already_saved():
    db = DB(); methods = []
    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={'id': 'file', 'name': 'data.txt', 'mimeType': 'text/plain', 'parents': ['original-folder']})
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    result = service.dispatch({'operation': 'file_save', 'file_id': 'file'}, 'save')
    assert result['status'] == 'ok' and methods == ['GET']


@pytest.mark.asyncio
async def test_api_capability_enforced_and_unconfigured_status_has_no_credentials(monkeypatch):
    from fastapi import FastAPI
    from src.api.routers.server_google import router
    monkeypatch.delenv('JARVIS_GOOGLE_CLIENT_SECRET')
    monkeypatch.setattr('src.services.server_google_auth.RecordStore', lambda: SimpleNamespace(_db=None))
    app = FastAPI(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/google-server/status')).status_code == 403
        result = await client.get('/google-server/status', headers={'X-Calendar-Session': KEY})
    assert result.status_code == 200
    assert result.json()['configured'] is False and result.json()['connected'] is False
    assert KEY not in result.text


def test_running_duplicate_task_never_repeats_external_action():
    db = DB(); tasks = Mock(); tasks.configured = True; executor = Mock()
    schedules = ScheduledGoogleActions(auth_stub(db), tasks, lambda owner: executor)
    created = schedules.create(OWNER, 'id', {'operation': 'create', 'event': EVENT},
        (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    identifier = created['schedule']['id']
    schedules.ref(OWNER, identifier).update({'status': 'running'})
    assert schedules.execute(OWNER, identifier)['status'] == 'ignored'
    executor.dispatch.assert_not_called()


def test_server_form_reader_uses_google_apis_without_phone_and_reports_bound(monkeypatch):
    db = DB(); hosts = []
    def handler(request):
        hosts.append(request.url.host)
        if request.url.path.startswith('/drive/'):
            return httpx.Response(200, json={'id': 'form', 'name': 'Survey', 'mimeType': 'application/vnd.google-apps.form'})
        if request.url.path.endswith('/responses'):
            assert request.url.params['pageSize'] == '10'
            return httpx.Response(200, json={'responses': [{'responseId': 'answer'}], 'nextPageToken': 'more'})
        return httpx.Response(200, json={'info': {'title': 'Survey'}})
    service = ServerGoogleActions(OWNER, auth_stub(db), httpx.Client(transport=httpx.MockTransport(handler)))
    analyzed = Mock(return_value={'status': 'ok'})
    monkeypatch.setattr(service, 'analyze_text', analyzed)
    assert service.dispatch({'operation': 'file_analyze', 'file_id': 'form', 'question': 'Explain'}, 'form-read')['status'] == 'ok'
    assert hosts == ['www.googleapis.com', 'forms.googleapis.com', 'forms.googleapis.com']
    assert 'up to ten' in analyzed.call_args.args[2][1]['locator']


def test_access_token_cache_still_checks_durable_disconnect():
    db = DB(); requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'access_token': 'temporary-access', 'expires_in': 3600})
    auth = ServerGoogleAuth(db, httpx.Client(transport=httpx.MockTransport(handler)))
    auth.ref(OWNER).set({'status': 'connected', 'email': 'owner@example.com', 'scopes': ' '.join(SCOPES),
                       'encrypted_refresh_token': auth.cipher().encrypt(b'private-refresh').decode()})
    assert auth.token(OWNER) == auth.token(OWNER) == 'temporary-access'
    assert len(requests) == 1
    auth.ref(OWNER).update({'status': 'disconnected'})
    with pytest.raises(HTTPException): auth.token(OWNER)


def test_scheduled_action_cannot_switch_to_another_google_account():
    db = DB(); tasks = Mock(); tasks.configured = True; executor = Mock()
    auth = auth_stub(db)
    schedules = ScheduledGoogleActions(auth, tasks, lambda owner: executor)
    schedules.notify = Mock()
    result = schedules.create(OWNER, 'id', {'operation': 'create', 'event': EVENT},
        (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    identifier = result['schedule']['id']
    schedules.ref(OWNER, identifier).update({'execute_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})
    auth.status = lambda owner: {'connected': True, 'email': 'other@example.com'}
    assert schedules.execute(OWNER, identifier)['status'] == 'failed'
    executor.dispatch.assert_not_called()


@pytest.mark.parametrize('paired', [True, False])
def test_reconciliation_uses_only_paired_connection_and_no_group_index(monkeypatch, paired):
    auth = Mock(); collection = Mock()
    auth.ref.return_value.collection.return_value = collection
    collection.where.return_value.limit.return_value.stream.return_value = []
    if not paired:
        monkeypatch.delenv('JARVIS_GOOGLE_OWNER_HASH')
    assert ScheduledGoogleActions(auth=auth).reconcile()['queued'] == 0
    auth.db.collection_group.assert_not_called()
    if paired:
        auth.ref.assert_called_once_with(OWNER)
    else:
        auth.ref.assert_not_called()
