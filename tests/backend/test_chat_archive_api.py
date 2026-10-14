from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import RequestLimitingMiddleware
from src.api.routers import chat_archives
from src.api.auth import get_current_user
from src.api.routers.server_google import owner


def client(monkeypatch):
    app = FastAPI()
    app.add_middleware(RequestLimitingMiddleware)
    app.include_router(chat_archives.router)
    app.include_router(chat_archives.background_router)
    app.dependency_overrides[get_current_user] = lambda: 'alice'
    app.dependency_overrides[owner] = lambda: 'private-owner'
    manager = SimpleNamespace(db=Mock(), archive_bytes=Mock(return_value={'sha256': 'digest'}),
                              policy=Mock(return_value={'enabled': True, 'inactive_days': 30}))
    monkeypatch.setattr(chat_archives, 'service', lambda: manager)
    auth = SimpleNamespace(client=Mock())
    monkeypatch.setattr(chat_archives, 'ServerGoogleAuth', lambda **kw: auth)
    return TestClient(app), manager


def test_gzip_backup_can_exceed_generic_request_limit(monkeypatch):
    api, manager = client(monkeypatch)
    raw = b'x' * 70000
    response = api.post('/chat-archives/chat/backup', content=raw, headers={'Content-Type': 'application/gzip'})
    assert response.status_code == 200
    assert manager.archive_bytes.call_args.args[3] == raw
    assert api.get('/chat-archives/policy').json()['inactive_days'] == 30


def test_chunked_backup_is_bounded_even_without_content_length(monkeypatch):
    api, manager = client(monkeypatch)
    monkeypatch.setattr(chat_archives, 'MAX_COMPRESSED', 8)
    response = api.post('/chat-archives/chat/backup', content=iter([b'1234', b'56789']),
                        headers={'Content-Type': 'application/gzip'})
    assert response.status_code == 413
    manager.archive_bytes.assert_not_called()


def test_unpaired_policy_and_unauthenticated_schedule_are_rejected(monkeypatch):
    app = FastAPI()
    app.include_router(chat_archives.router)
    app.include_router(chat_archives.background_router)
    api = TestClient(app)
    assert api.get('/chat-archives/policy').status_code == 403
    assert api.put('/chat-archives/policy', json={'enabled': False}).status_code == 403
    assert api.post('/internal/background/chat-archive-daily').status_code == 401
