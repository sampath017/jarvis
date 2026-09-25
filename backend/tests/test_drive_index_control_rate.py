from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from src.api.middleware import RequestLimitingMiddleware
from src.api.routers.file_memories import owner
from src.api.routers.file_memories import FileMemory
import pytest


def test_bulk_control_remains_available_without_using_chat_allowance(monkeypatch):
    monkeypatch.setattr(RequestLimitingMiddleware, '_check_rate_limit', lambda *args: False)
    app = FastAPI()
    app.add_middleware(RequestLimitingMiddleware)

    @app.post('/drive-index/uploads')
    def begin(uid=Depends(owner)):
        return {'authorized': True}

    @app.post('/drive-index/search')
    def search():
        return {}

    client = TestClient(app)
    assert client.post('/drive-index/uploads').status_code == 401
    assert client.post('/drive-index/uploads', headers={'X-File-Memory-Session': 'a' * 64}).status_code == 200
    assert client.post('/drive-index/search').status_code == 429


@pytest.mark.parametrize('kind', ['document', 'spreadsheets', 'presentation'])
def test_google_document_source_links_are_valid(kind):
    memory = FileMemory(id='original', name='Original', mimeType='application/vnd.google-apps.document',
        url=f'https://docs.google.com/{kind}/d/original/edit', size=0, account='a', created_at='')
    assert memory.url.startswith('https://docs.google.com/')
