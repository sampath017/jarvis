"""Real direct-SQL persistence and request-memory regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from src.services.sqlite_store import SqlStore
from src.services.record_store import RecordStore


def test_records_survive_reopen_and_filter_before_paging(tmp_path):
    path = tmp_path / 'records.db'
    db = SqlStore(path)
    for number in range(15):
        db.put('notes', f'{number:02}', {'content': str(number), 'number': number},
               uid='u' if number % 2 else 'other')
    reopened = SqlStore(path)
    first = reopened.list('notes', uid='u', order_by=['id'], limit=3)
    second = reopened.list('notes', uid='u', order_by=['id'], after_id=first[-1]['id'], limit=3)
    assert [row['number'] for row in first + second] == [1, 3, 5, 7, 9, 11]
    assert len(reopened.list('notes', uid='u')) == 7


def test_nested_dates_and_transaction_rollback(tmp_path):
    db = SqlStore(tmp_path / 'records.db')
    now = datetime.now(timezone.utc)
    db.put('command_control', 'one', {'until': now, 'days': {'today': 1}, 'keep': True}, uid='u')
    with db.atomic():
        row = db.get('command_control', 'one', uid='u')
        db.put('command_control', 'one', {'days': {'today': row['days']['today'] + 2}}, uid='u')
    assert db.get('command_control', 'one', uid='u')['days']['today'] == 3
    assert len(db.list('command_control', uid='u', filters=[('until', '>=', now)])) == 1
    with pytest.raises(ValueError, match='rollback'):
        with db.atomic():
            db.put('command_control', 'one', {'keep': False}, uid='u')
            db.put('command_control', 'two', {'created': True}, uid='u')
            raise ValueError('rollback')
    assert db.get('command_control', 'one', uid='u')['keep'] is True
    assert db.get('command_control', 'two', uid='u') is None


def test_concurrent_claims_across_clients_have_one_owner(tmp_path):
    path = tmp_path / 'records.db'
    SqlStore(path)
    def claim(index):
        db = SqlStore(path)
        with db.atomic():
            if db.get('command_control', 'active', uid='u'):
                return False
            db.put('command_control', 'active', {'worker': index}, uid='u')
            return True
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(12))) == 1


def test_record_store_roundtrip_and_owner_isolated_deletes(tmp_path):
    path = tmp_path / 'records.db'
    service = RecordStore.from_sql(SqlStore(path))
    assert service.save_note('n', {'uid': 'u', 'title': 'Offline note', 'content': 'Keep me'})
    assert service.save_note('other', {'uid': 'other', 'content': 'Private'})
    assert service.get_notes('u')[0]['content'] == 'Keep me'
    assert service.delete_all_notes('u')
    reopened = RecordStore.from_sql(SqlStore(path))
    assert reopened.get_notes('u') == []
    assert reopened.get_notes('other')[0]['content'] == 'Private'


def test_request_coordination_memory_does_not_become_a_server_database():
    first = SqlStore(':memory:')
    first.put('command_runs', 'run', {'status': 'running'}, uid='u')
    second = SqlStore(':memory:')
    assert second.get('command_runs', 'run', uid='u') is None
    assert first.get('command_runs', 'run', uid='u')['status'] == 'running'


def test_notification_outbox_deduplicates_and_never_calls_push(tmp_path, monkeypatch):
    from src.services import push_notifications
    service = RecordStore.from_sql(SqlStore(tmp_path / 'records.db'))
    monkeypatch.setattr(push_notifications, 'RecordStore', lambda: service)
    outbox = push_notifications.PushNotifications()
    outbox.queue_chat('u', 'request', 'thread', {'message': 'Ready'})
    outbox.queue_chat('u', 'request', 'thread', {'message': 'Ready'})
    assert len(service.get_notifications('u', 'PENDING')) == 1
    assert outbox.wake_context('u', 'request', '') == 0


def test_retired_routes_are_not_registered():
    from src.api.main import create_app
    paths = create_app().openapi()['paths']
    assert not any(path.startswith('/desktop') for path in paths)
    assert '/devices/push-token' not in paths
    assert '/sync/push' not in paths
    assert not any(path.startswith('/drive-index/uploads') for path in paths)
    assert not any(path.startswith('/session-library/recordings') for path in paths)


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
