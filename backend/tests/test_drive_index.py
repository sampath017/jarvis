from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.services import drive_index as service
from src.api.routers.drive_index import router


def test_text_is_chunked_with_source_offsets():
    chunks = list(service.chunks(('hello ' * 1000).encode(), 'text/plain', 'Test'))
    assert len(chunks) == 2
    assert chunks[0][2] == 'characters 1-3500'
    assert chunks[1][2].startswith('characters 3001-')
    assert all(len(c[0]['text']) <= 3500 for c in chunks)


def test_index_replacement_preserves_old_version_when_embedding_fails(monkeypatch):
    coll = Mock()
    coll.get.return_value = {'ids': ['old'], 'metadatas': [{'digest': 'old'}]}
    monkeypatch.setattr(service, 'index', lambda: coll)
    monkeypatch.setattr(service, 'embed', Mock(side_effect=RuntimeError('offline')))
    with pytest.raises(RuntimeError):
        service.put_file('owner', {'account': 'a', 'id': 'f', 'name': 'test',
            'mimeType': 'text/plain', 'url': 'https://drive.google.com/file/d/f'}, b'hello')
    assert coll.delete.call_args.kwargs['where']['$and'][-1]['generation'] != 'old'
    coll.upsert.assert_not_called()


def test_index_search_is_owner_and_account_scoped_and_returns_no_raw_text(monkeypatch):
    coll = Mock()
    coll.query.return_value = {'metadatas': [[{'file_id': 'f'}]], 'distances': [[0.1]]}
    monkeypatch.setattr(service, 'index', lambda: coll)
    monkeypatch.setattr(service, 'embed', lambda *args: [[0.] * 768])
    result = service.search('owner-a', 'account-a', 'query')
    assert coll.query.call_args.kwargs['where'] == {'$and': [{'owner': 'owner-a'}, {'account': 'account-a'}, {'complete': True}]}
    assert 'documents' not in coll.query.call_args.kwargs['include']
    assert result['matches'][0]['file_id'] == 'f'


def test_index_routes_require_phone_capability():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get('/drive-index/status').status_code == 401
    assert client.post('/drive-index/search', json={'account': 'a', 'query': 'q'}).status_code == 401


def test_index_new_version_upserts_before_removing_stale_chunks(monkeypatch):
    coll = Mock()
    coll.get.return_value = {'ids': ['old'], 'metadatas': [{'digest': 'old'}]}
    monkeypatch.setattr(service, 'index', lambda: coll)
    monkeypatch.setattr(service, 'embed', lambda items: [[0.] * 768 for _ in items])
    def records(where, include=None, limit=None, offset=0):
        if offset:
            return {'ids': [], 'metadatas': []}
        if coll.upsert.called:
            values = coll.upsert.call_args.kwargs
            return {'ids': values['ids'], 'metadatas': values['metadatas']}
        return {'ids': ['old'], 'metadatas': [{'digest': 'old'}]}
    coll.get.side_effect = records
    result = service.put_file('owner', {'account': 'a', 'id': 'f', 'name': 'test',
        'mimeType': 'text/plain', 'source_version': '42', 'url': 'https://drive.google.com/file/d/f'}, b'hello')
    assert result == {'status': 'indexed', 'chunks': 1, 'coverage': 'content', 'issues': {}, 'reader_version': 2}
    assert coll.upsert.call_args.kwargs['metadatas'][0]['source_version'] == '42'
    assert all(len(id.encode()) <= 128 for id in coll.upsert.call_args.kwargs['ids'])
    assert coll.update.called
    assert '$ne' in coll.delete.call_args.kwargs['where']['$and'][-1]['generation']


def test_evidence_is_version_scoped_and_does_not_present_media_names_as_content(monkeypatch):
    coll = Mock()
    coll.query.return_value = {'documents': [['ORBIT-417', 'recording.mp4']], 'metadatas': [[
        {'locator': 'paragraph 1', 'unit_kind': 'text'},
        {'locator': 'seconds 0-10', 'unit_kind': 'video', 'name': 'recording.mp4'}]]}
    monkeypatch.setattr(service, 'index', lambda: coll)
    monkeypatch.setattr(service, 'embed', lambda *args: [[0.] * 768])
    result = service.evidence('owner', 'account', 'file', '7', 'question')
    assert {'source_version': '7'} in coll.query.call_args.kwargs['where']['$and']
    assert result['evidence'][0]['text'] == 'ORBIT-417'
    assert result['evidence'][1]['content_kind'] == 'media_reference'
    assert 'no transcript' in result['evidence'][1]['text']
