from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import gzip
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.services.automatic_chat_archives import AutomaticChatArchives
from src.services.chat_archive_format import verify
from src.services.chat_archive_policy import inactive, timestamp
from src.services.sync_change_feed import SyncChangeFeed
from test_incremental_sync import Database, Query, Ref, Snapshot, Transaction, db as transaction_patch


class ArchiveRef(Ref):
    def collection(self, name):
        return ArchiveQuery(self.db, self.path + '/' + name)

    def set(self, data, merge=False):
        self.db.rows[self.path] = {**(self.db.rows.get(self.path, {}) if merge else {}), **deepcopy(data)}


class ArchiveQuery(Query):
    def __init__(self, db, path, filters=(), after='', cap=None, ordering='__name__'):
        super().__init__(db, path, filters, after, cap)
        self.ordering = ordering

    def document(self, name):
        return ArchiveRef(self.db, self.path + '/' + name)

    def where(self, *args, filter=None):
        if filter is None:
            from src.services.sqlite_documents import FieldFilter
            filter = FieldFilter(*args)
        return ArchiveQuery(self.db, self.path, (*self.filters, filter), self.after, self.cap, self.ordering)

    def order_by(self, field):
        return ArchiveQuery(self.db, self.path, self.filters, self.after, self.cap, field)

    def start_after(self, value):
        return ArchiveQuery(self.db, self.path, self.filters, value['__name__'].id, self.cap, self.ordering)

    def limit(self, cap):
        return ArchiveQuery(self.db, self.path, self.filters, self.after, cap, self.ordering)

    def stream(self, transaction=None):
        if transaction and transaction.writes:
            raise AssertionError('All reads precede transaction writes')
        rows = [(p, d) for p, d in sorted(self.db.rows.items())
                if p.rsplit('/', 1)[0] == self.path and p.rsplit('/', 1)[1] > self.after]
        for f in self.filters:
            if f.op_string == '==':
                rows = [(p, d) for p, d in rows if d.get(f.field_path) == f.value]
            else:
                assert f.op_string == '<='
                rows = [(p, d) for p, d in rows if d.get(f.field_path) is not None and d[f.field_path] <= f.value]
        if self.ordering != '__name__':
            rows.sort(key=lambda row: row[1][self.ordering])
        if self.cap is not None:
            rows = rows[:self.cap]
        return [Snapshot(ArchiveRef(self.db, p), d) for p, d in rows]


class ArchiveDb(Database):
    def collection(self, name):
        return ArchiveQuery(self, name)


class Drive:
    def __init__(self):
        self.files = {}
        self.uploads = 0
        self.before_upload = None

    def status(self):
        return 'owner@example.com'

    def ensure_folder(self):
        return 'private-folder'

    def allocate_file_id(self):
        return 'file-' + str(self.uploads + 1)

    def read(self, file_id):
        return self.files[file_id]

    def upload(self, thread_id, raw, file_id):
        self.uploads += 1
        self.files[file_id] = raw
        if self.before_upload:
            self.before_upload()
        return {'file_id': file_id, 'sha256': sha256(raw).hexdigest(), 'email': self.status()}


@pytest.fixture
def setup(transaction_patch):
    store, drive = ArchiveDb(), Drive()
    clock = [datetime(2026, 10, 14, 8, tzinfo=timezone.utc)]
    manager = AutomaticChatArchives(store, now=lambda: clock[0], power=SimpleNamespace(require_enabled=lambda: None))
    return store, drive, clock, manager


def seed(store, thread='old', at='2026-09-01T08:00:00Z'):
    store.rows['chat_sessions/' + thread] = {'id': thread, 'uid': 'alice', 'title': thread,
        'created_at': at, 'updated_at': at, 'archive_activity_at': timestamp(at), 'archive_pending': True}
    store.rows['chat_messages/' + thread] = {'id': thread, 'uid': 'alice', 'thread_id': thread,
        'content': 'remember this', 'role': 'user', 'timestamp': at}


def test_inactivity_uses_latest_timestamp_and_fails_closed():
    cutoff = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    assert inactive({'updated_at': '2026-09-14T13:30:00+05:30'}, cutoff)
    assert not inactive({'updated_at': '2026-09-01T08:00:00Z', 'last_used_at': '2026-10-01T08:00:00Z'}, cutoff)
    for bad in ('2026-09-01T08:00:00', 'bad', '2027-01-01T08:00:00Z'):
        assert not inactive({'updated_at': bad}, cutoff)


def test_daily_only_archives_idle_chats_and_does_not_repeat_uploads(setup):
    store, drive, clock, manager = setup
    seed(store)
    seed(store, 'recent', '2026-10-01T08:00:00Z')
    result = manager.run_daily('alice', 'owner', drive=drive)
    assert result['archived'] == 1 and drive.uploads == 1
    assert 'chat_messages/old' not in store.rows and 'chat_messages/recent' in store.rows
    assert store.rows['chat_sessions/old']['archive_pending'] is False
    assert manager.run_daily('alice', 'owner', drive=drive)['status'] == 'already_checked'
    clock[0] += timedelta(days=1)
    assert manager.run_daily('alice', 'owner', drive=drive)['archived'] == 0
    assert drive.uploads == 1


def test_recent_view_during_upload_prevents_retirement(setup):
    store, drive, clock, manager = setup
    seed(store)
    drive.before_upload = lambda: manager.touch('alice', 'old')
    result = manager.run_daily('alice', 'owner', drive=drive)
    assert result['archived'] == 0 and result['errors'] == 1
    assert 'chat_messages/old' in store.rows
    assert 'archive_drive_id' not in store.rows['chat_sessions/old']


def test_live_command_defers_without_uploading(setup):
    store, drive, clock, manager = setup
    seed(store)
    store.rows['users/alice/command_control/active'] = {'request_id': 'run', 'until': clock[0] + timedelta(minutes=2)}
    store.rows['users/alice/command_runs/' + sha256(b'run').hexdigest()] = {'status': 'running', 'thread_id': 'old'}
    assert manager.run_daily('alice', 'owner', drive=drive)['deferred'] == 1
    assert drive.uploads == 0 and 'chat_messages/old' in store.rows


def test_policy_disable_during_upload_protects_cloud_rows(setup):
    store, drive, clock, manager = setup
    seed(store)
    drive.before_upload = lambda: manager.set_enabled('alice', False)
    assert manager.run_daily('alice', 'owner', drive=drive)['errors'] == 1
    assert 'chat_messages/old' in store.rows
    assert manager.policy('alice')['enabled'] is False


def test_rearchive_merges_older_drive_history_with_new_live_messages(setup):
    store, drive, clock, manager = setup
    seed(store)
    assert manager.run_daily('alice', 'owner', drive=drive)['archived'] == 1
    original_file = store.rows['chat_sessions/old']['archive_drive_id']
    store.rows['chat_messages/new'] = {'id': 'new', 'uid': 'alice', 'thread_id': 'old',
        'content': 'continued later', 'role': 'assistant', 'timestamp': '2026-10-15T08:00:00Z', 'duration_ms': 10}
    store.rows['chat_sessions/old'].update(archive_pending=True, updated_at='2026-10-15T08:00:00Z',
                                         archive_activity_at=timestamp('2026-10-15T08:00:00Z'))
    clock[0] = datetime(2026, 11, 18, 8, tzinfo=timezone.utc)
    assert manager.run_daily('alice', 'owner', drive=drive)['archived'] == 1
    new_file = store.rows['chat_sessions/old']['archive_drive_id']
    assert new_file != original_file and original_file in drive.files
    messages = verify(drive.read(new_file)).session.messages
    assert [m.id for m in messages] == ['old', 'new'] and messages[1].duration_ms == 10


def test_manual_archive_remains_available_when_automatic_disabled(setup):
    store, drive, clock, manager = setup
    seed(store, at='2026-10-14T08:00:00Z')
    manager.set_enabled('alice', False)
    assert manager.run_daily('alice', 'owner', drive=drive)['status'] == 'disabled'
    raw = gzip.compress(b'{"kind":"jarvis_chat_backup","version":1,"session":{"id":"old","title":"old",'
        b'"created_at":"2026-10-14T08:00:00Z","updated_at":"2026-10-14T08:00:00Z",'
        b'"messages":[{"id":"old","text":"remember this","is_user":true,"timestamp":"2026-10-14T08:00:00Z"}]}}')
    assert manager.archive_bytes('alice', 'old', 'owner', raw, drive)['archived']


def test_legacy_session_backfill_and_new_message_activity_are_transactional(setup):
    store, drive, clock, manager = setup
    seed(store)
    store.rows['chat_sessions/old'].pop('archive_activity_at')
    store.rows['chat_sessions/old'].pop('archive_pending')
    assert manager.run_daily('alice', 'owner', drive=drive)['archived'] == 1
    SyncChangeFeed(store).write('chat_messages', 'new', {'uid': 'alice', 'thread_id': 'old', 'content': 'new'})
    assert store.rows['chat_sessions/old']['archive_pending'] is True
    assert store.rows['chat_sessions/old']['archive_activity_at'] > timestamp('2026-09-01T08:00:00Z')


def test_corrupt_prior_archive_and_failed_upload_preserve_live_copies(setup):
    store, drive, clock, manager = setup
    seed(store)
    store.rows['chat_sessions/old'].update(archive_drive_id='prior', archive_sha256='wrong', archive_connection='owner')
    drive.files['prior'] = b'corrupt'
    assert manager.run_daily('alice', 'owner', drive=drive)['errors'] == 1
    assert 'chat_messages/old' in store.rows and drive.uploads == 0


def test_wrong_owner_and_invalid_backup_never_upload(setup):
    store, drive, clock, manager = setup
    seed(store)
    with pytest.raises(HTTPException):
        manager.archive_bytes('bob', 'old', 'owner', b'bad', drive)
    with pytest.raises(HTTPException):
        manager.archive_bytes('alice', 'old', 'owner', b'bad', drive)
    assert drive.uploads == 0 and 'chat_messages/old' in store.rows


def test_bounded_daily_scan_advances_past_failed_backups(setup):
    store, drive, clock, manager = setup
    for n in range(25):
        seed(store, 'old%03d' % n)
    store.rows['chat_sessions/old000'].update(archive_drive_id='corrupt', archive_sha256='wrong', archive_connection='owner')
    drive.files['corrupt'] = b'corrupt'
    first = manager.run_daily('alice', 'owner', drive=drive)
    assert first['examined'] == 20 and first['errors'] == 1 and first['archived'] == 19
    clock[0] += timedelta(days=1)
    second = manager.run_daily('alice', 'owner', drive=drive)
    assert second['archived'] == 5 and 'chat_messages/old000' in store.rows
