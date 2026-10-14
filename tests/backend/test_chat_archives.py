import gzip
import json

import pytest
from fastapi import HTTPException

from src.services.chat_archive_format import verify
from src.api.routers.chat_archives import retire, comparable
from src.services.sync_change_feed import SyncChangeFeed
from test_incremental_sync import db  # Same transaction simulator, no cloud calls.


def payload():
    return {'kind': 'jarvis_chat_backup', 'version': 1, 'session': {
        'id': 'chat', 'title': 'An old conversation',
        'created_at': '2026-01-01T10:00:00Z', 'updated_at': '2026-01-01T10:00:00Z',
        'messages': [{'id': 'm', 'text': 'remember this', 'is_user': True,
                      'timestamp': '2026-01-01T10:00:00Z', 'executed_records': []}],
    }}


def seed(db):
    db.rows['chat_sessions/chat'] = {'id': 'chat', 'uid': 'alice', 'title': 'An old conversation',
                                    'updated_at': '2026-01-01T10:00:00Z'}
    db.rows['chat_messages/m'] = {'id': 'm', 'uid': 'alice', 'thread_id': 'chat',
                                 'content': 'remember this', 'role': 'user',
                                 'timestamp': '2026-01-01T15:30:00+05:30', 'executed_records': '[]'}


def test_archive_verifies_content_and_keeps_conversation_summary(db):
    seed(db)
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    result = retire(db, 'alice', 'chat', archive, 'drive-file', 'digest', 'private-owner', 'user@example.com')
    assert result['cloud_messages_removed'] == 1
    assert 'chat_messages/m' not in db.rows
    assert db.rows['chat_sessions/chat']['archive_drive_id'] == 'drive-file'
    assert db.rows['chat_sessions/chat']['updated_at'] == '2026-01-01T10:00:00Z'
    assert not any('data' in value for path, value in db.rows.items() if '/sync_changes/' in path)


def test_incomplete_or_stale_backup_cannot_delete_messages(db):
    seed(db)
    db.rows['chat_messages/m']['content'] = 'a newer edit'
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    with pytest.raises(HTTPException) as failure:
        retire(db, 'alice', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    assert failure.value.status_code == 409
    assert db.rows['chat_messages/m']['content'] == 'a newer edit'
    assert 'archive_drive_id' not in db.rows['chat_sessions/chat']


def test_legacy_phone_timestamp_matches_utc_backup_before_retirement(db):
    seed(db)
    db.rows['chat_messages/m']['timestamp'] = '2026-01-01T15:30:00'
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    result = retire(db, 'alice', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    assert result['cloud_messages_removed'] == 1
    assert 'chat_messages/m' not in db.rows


def test_corrupt_cloud_timestamp_is_recoverable_conflict_not_internal_error(db):
    seed(db)
    db.rows['chat_messages/m']['timestamp'] = 'invalid'
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    with pytest.raises(HTTPException) as error:
        retire(db, 'alice', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    assert error.value.status_code == 409
    assert 'chat_messages/m' in db.rows


def test_uploaded_backup_must_use_explicit_timezone():
    data = payload()
    data['session']['messages'][0]['timestamp'] = '2026-01-01T10:00:00'
    with pytest.raises(ValueError):
        verify(gzip.compress(json.dumps(data).encode()))


def test_owner_and_thread_mismatch_preserve_originals(db):
    seed(db)
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    with pytest.raises(HTTPException):
        retire(db, 'bob', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    with pytest.raises(HTTPException):
        retire(db, 'alice', 'different', archive, 'file', 'digest', 'owner', 'user@example.com')
    assert 'chat_messages/m' in db.rows


def test_old_feed_entries_do_not_delete_phone_history_after_archive(db):
    feed = SyncChangeFeed(db)
    cursor = feed.token('alice', phase='changes', revision=0)
    feed.write('chat_sessions', 'chat', {'uid': 'alice', 'title': 'An old conversation'})
    feed.write('chat_messages', 'm', {'uid': 'alice', 'thread_id': 'chat', 'content': 'remember this',
                                     'role': 'user', 'timestamp': '2026-01-01T10:00:00Z'})
    archive = verify(gzip.compress(json.dumps(payload()).encode()))
    retire(db, 'alice', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    page = feed.pull('alice', cursor)
    assert all(e['collection'] != 'chat_messages' for e in page['events'])
    assert SyncChangeFeed.decode('alice', page['cursor'])['revision'] == 3
    feed.write('chat_messages', 'new', {'uid': 'alice', 'thread_id': 'chat', 'content': 'continue here'})
    assert feed.pull('alice', page['cursor'])['events'][0]['data']['content'] == 'continue here'


def test_corrupt_backup_and_decompression_bomb_are_rejected():
    with pytest.raises((ValueError, OSError, EOFError)):
        verify(b'not gzip')
    with pytest.raises(ValueError):
        verify(gzip.compress(b'x' * (32 * 1024 * 1024 + 1)))


def test_large_conversation_is_archived_in_bounded_transactions(db):
    seed(db)
    value = payload()
    for n in range(405):
        record = {**value['session']['messages'][0], 'id': 'm' + str(n)}
        value['session']['messages'].append(record)
        db.rows['chat_messages/' + record['id']] = {**db.rows['chat_messages/m'], 'id': record['id']}
    archive = verify(gzip.compress(json.dumps(value).encode()))
    result = retire(db, 'alice', 'chat', archive, 'file', 'digest', 'owner', 'user@example.com')
    assert result['cloud_messages_removed'] == 406
    assert not any(path.startswith('chat_messages/') for path in db.rows)
