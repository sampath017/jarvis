"""Real SQLite persistence and cache-reset regressions; no cloud SDK or mocks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from src.services import sqlite_documents as records
from src.services.record_store import RecordStore
from src.services.sync_change_feed import SyncChangeFeed


def test_records_survive_reopen_and_filter_before_paging(tmp_path):
    path = tmp_path / 'records.db'
    db = records.Client(path)
    for number in range(15):
        db.collection('notes').document(f'{number:02}').set({'uid': 'u' if number % 2 else 'other', 'number': number})
    reopened = records.Client(path)
    query = reopened.collection('notes').where(filter=records.FieldFilter('uid', '==', 'u')).order_by('number')
    first = list(query.limit(3).stream())
    second = list(query.start_after({'number': first[-1].to_dict()['number']}).limit(3).stream())
    assert [r.to_dict()['number'] for r in first + second] == [1, 3, 5, 7, 9, 11]
    assert reopened.generation == db.generation
    assert query.count().get()[0][0].value == 7


def test_nested_dates_increments_and_transaction_rollback(tmp_path):
    db = records.Client(tmp_path / 'records.db')
    ref = db.collection('leases').document('one')
    now = datetime.now(timezone.utc)
    ref.set({'at': now, 'days': {'today': 1}, 'keep': True})
    ref.set({'days': {'today': records.Increment(2)}}, merge=True)
    assert ref.get().to_dict() == {'at': now, 'days': {'today': 3}, 'keep': True}
    assert len(list(db.collection('leases').where('at', '>=', now).stream())) == 1

    @records.transactional
    def fail(tx):
        tx.update(ref, {'keep': False})
        tx.set(db.collection('leases').document('two'), {'created': True})
        raise ValueError('rollback')

    with pytest.raises(ValueError, match='rollback'):
        fail(db.transaction())
    assert ref.get().to_dict()['keep'] is True
    assert not db.collection('leases').document('two').get().exists


def test_concurrent_claims_across_clients_have_one_owner(tmp_path):
    path = tmp_path / 'records.db'
    records.Client(path)

    def claim(index):
        db = records.Client(path)
        ref = db.collection('claims').document('one')

        @records.transactional
        def commit(tx):
            if ref.get(transaction=tx).exists:
                return False
            tx.set(ref, {'owner': index})
            return True
        return commit(db.transaction())

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(12))) == 1


def test_record_store_roundtrip_and_sync_deletes(tmp_path):
    service = object.__new__(RecordStore)
    service._db = records.Client(tmp_path / 'records.db')
    assert service.save_note('n', {'uid': 'u', 'title': 'Offline note', 'content': 'Keep me'})
    assert service.get_notes('u')[0]['content'] == 'Keep me'
    assert service.get_notes('other') == []
    feed = SyncChangeFeed(service._db)
    page = feed.pull('u')
    while page.get('bootstrap'):
        page = feed.pull('u', page['cursor'])
    cursor = page['cursor']
    assert service.delete_note('n')
    changes = feed.pull('u', cursor)
    assert changes['events'][0]['deleted'] is True
    assert service.get_notes('u') == []


def test_recreated_api_cache_rejects_old_cursor_even_at_same_revision(tmp_path):
    original = SyncChangeFeed(records.Client(tmp_path / 'old.db'))
    page = original.pull('u')
    while page.get('bootstrap'):
        page = original.pull('u', page['cursor'])
    replacement = SyncChangeFeed(records.Client(tmp_path / 'new.db'))
    with pytest.raises(ValueError, match='rehydrate'):
        replacement.pull('u', page['cursor'])


def test_notification_outbox_deduplicates_and_never_calls_push(tmp_path, monkeypatch):
    from src.services import push_notifications
    service = object.__new__(RecordStore)
    service._db = records.Client(tmp_path / 'records.db')
    monkeypatch.setattr(push_notifications, 'RecordStore', lambda: service)
    outbox = push_notifications.PushNotifications()
    outbox.queue_chat('u', 'request', 'thread', {'message': 'Ready'})
    outbox.queue_chat('u', 'request', 'thread', {'message': 'Ready'})
    assert len(service.get_notifications('u', 'PENDING')) == 1
    assert outbox.wake_context('u', 'request', '') == 0


def test_retired_routes_are_not_registered():
    from src.api.main import app
    paths = [route.path for route in app.routes if hasattr(route, 'path')]
    assert not any(path.startswith('/desktop') for path in paths)
    assert '/devices/push-token' not in paths
    assert not any(path.startswith('/session-library/recordings') for path in paths)


@pytest.mark.asyncio
async def test_local_index_upload_is_owned_bounded_and_retry_safe(tmp_path, monkeypatch):
    from starlette.requests import Request
    from fastapi import HTTPException
    from src.api.routers import drive_index
    from src.services import drive_index_queue as queue

    monkeypatch.setenv('JARVIS_LOCAL_DB_PATH', str(tmp_path / 'index.db'))
    db = records.Client(tmp_path / 'index.db')
    monkeypatch.setattr(queue, 'db', lambda: db)
    monkeypatch.setattr(queue, 'kick', lambda: None)
    monkeypatch.setattr(drive_index.service, 'configured', lambda: True)
    upload = queue.begin('u', {'id': 'file', 'account': 'a', 'mimeType': 'text/plain'})
    job = upload['job_id']
    assert upload['upload_url'].startswith('/drive-index/uploads/')

    def request(body, span):
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        return Request({'type': 'http', 'method': 'PUT', 'path': '/',
                        'headers': [(b'content-range', span.encode())]}, receive)

    with pytest.raises(HTTPException) as denied:
        await drive_index.upload_content(job, request(b'abc', 'bytes 0-2/*'), 'other')
    assert denied.value.status_code == 404
    first = await drive_index.upload_content(job, request(b'abc', 'bytes 0-2/*'), 'u')
    assert first.status_code == 308
    await drive_index.upload_content(job, request(b'abc', 'bytes 0-2/*'), 'u')
    with pytest.raises(HTTPException) as mismatch:
        await drive_index.upload_content(job, request(b'bad', 'bytes 0-2/*'), 'u')
    assert mismatch.value.status_code == 409
    last = await drive_index.upload_content(job, request(b'def', 'bytes 3-5/6'), 'u')
    assert last.status_code == 200
    value = queue.jobs().document(job).get().to_dict()
    assert queue.bucket().blob(value['object']).path.read_bytes() == b'abcdef'
    with pytest.raises(HTTPException) as oversized:
        await drive_index.upload_content(job, request(b'', 'bytes 0-9000000/*'), 'u')
    assert oversized.value.status_code == 413
    assert queue.finish('u', job, 6, 'text/plain')['status'] == 'queued'


def test_vector_index_preserves_existing_chroma_configuration(monkeypatch):
    from src.services import drive_index
    import chromadb
    from unittest.mock import Mock
    for name,value in {'CHROMA_HOST':'existing.host','CHROMA_API_KEY':'test-key','CHROMA_TENANT':'existing-tenant','CHROMA_DATABASE':'existing-db','EMBEDDING_URL':'https://existing.compute'}.items():
        monkeypatch.setenv(name,value)
    client=Mock();factory=Mock(return_value=client)
    monkeypatch.setattr(chromadb,'CloudClient',factory)
    drive_index.index.cache_clear()
    try:
        assert drive_index.configured()
        drive_index.index()
        factory.assert_called_once_with(api_key='test-key',tenant='existing-tenant',database='existing-db',cloud_host='existing.host')
        assert client.get_or_create_collection.call_args.args[0]=='jarvis-drive-eg2-768-v1'
    finally:drive_index.index.cache_clear()
