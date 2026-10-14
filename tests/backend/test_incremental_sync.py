import copy
from collections import Counter

import pytest

from src.services.sync_change_feed import SyncChangeFeed


class Snapshot:
    def __init__(self, ref, data):
        self.reference, self.id, self.data = ref, ref.id, copy.deepcopy(data)
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self.data)


class Ref:
    def __init__(self, db, path):
        self.db, self.path = db, path
        self.id = path.split('/')[-1]

    def collection(self, name):
        return Query(self.db, self.path + '/' + name)

    def get(self, transaction=None):
        if transaction and transaction.writes:
            raise AssertionError('RecordStore reads must precede writes')
        self.db.reads[self.path] += 1
        return Snapshot(self, self.db.rows.get(self.path))


class Query:
    def __init__(self, db, path, filters=(), after='', cap=None):
        self.db, self.path, self.filters, self.after, self.cap = db, path, filters, after, cap

    def document(self, name):
        return Ref(self.db, self.path + '/' + name)

    def where(self, *args, filter=None):
        if filter is None:
            from src.services.sqlite_documents import FieldFilter
            filter = FieldFilter(*args)
        return Query(self.db, self.path, (*self.filters, filter), self.after, self.cap)

    def order_by(self, field):
        assert field == '__name__'
        return self

    def start_after(self, value):
        return Query(self.db, self.path, self.filters, value['__name__'].id, self.cap)

    def limit(self, cap):
        return Query(self.db, self.path, self.filters, self.after, cap)

    def stream(self, transaction=None):
        rows = [(p, d) for p, d in sorted(self.db.rows.items())
                if p.rsplit('/', 1)[0] == self.path and p.rsplit('/', 1)[1] > self.after]
        for f in self.filters:
            assert f.op_string == '=='
            rows = [(p, d) for p, d in rows if d.get(f.field_path) == f.value]
        if self.cap is not None:
            rows = rows[:self.cap]
        self.db.scans[self.path] += 1
        self.db.reads[self.path] += len(rows)
        return [Snapshot(Ref(self.db, p), d) for p, d in rows]


class Transaction:
    def __init__(self, db):
        self.db, self.writes = db, []

    def set(self, ref, data):
        self.writes.append((ref.path, copy.deepcopy(data)))

    def delete(self, ref):
        self.writes.append((ref.path, None))

    def commit(self):
        if self.db.fail:
            raise RuntimeError('Simulated commit failure')
        for path, data in self.writes:
            if data is None:
                self.db.rows.pop(path, None)
            else:
                self.db.rows[path] = data


class Database:
    def __init__(self):
        self.rows, self.reads, self.scans, self.fail = {}, Counter(), Counter(), False

    def collection(self, name):
        return Query(self, name)

    def transaction(self):
        return Transaction(self)


@pytest.fixture
def db(monkeypatch):
    def transactional(fn):
        def commit(tx):
            value = fn(tx)
            tx.commit()
            return value
        return commit
    monkeypatch.setattr('src.services.sync_change_feed.documents.transactional', transactional)
    return Database()


def finish_bootstrap(feed, uid, cursor=None, limit=1):
    seen = []
    while True:
        page = feed.pull(uid, cursor, limit)
        seen.extend(page['events'])
        cursor = page['cursor']
        if page.get('bootstrap_complete'):
            return cursor, seen


def test_bootstrap_is_paged_and_owner_scoped(db):
    for n in range(5):
        db.rows['chat_messages/m' + str(n)] = {'id': 'm' + str(n), 'uid': 'alice'}
    db.rows['chat_messages/bob'] = {'id': 'bob', 'uid': 'bob'}
    cursor, seen = finish_bootstrap(SyncChangeFeed(db), 'alice', limit=2)
    assert len(seen) == 5 and all(e['id'] != 'bob' for e in seen)
    assert SyncChangeFeed.decode('alice', cursor)['phase'] == 'changes'
    with pytest.raises(ValueError):
        SyncChangeFeed(db).pull('bob', cursor)


def test_multiple_updates_read_current_document_only_once(db):
    feed = SyncChangeFeed(db)
    cursor, _ = finish_bootstrap(feed, 'alice')
    for value in ['one', 'two', 'three']:
        feed.write('notes', 'n', {'uid': 'alice', 'content': value})
    db.reads.clear()
    page = feed.pull('alice', cursor)
    assert len(page['events']) == 1
    assert page['events'][0]['data']['content'] == 'three'
    assert db.reads['notes/n'] == 1
    assert SyncChangeFeed.decode('alice', page['cursor'])['revision'] == 3


def test_changes_during_bootstrap_are_replayed_including_deletion(db):
    db.rows['notes/old'] = {'id': 'old', 'uid': 'alice', 'content': 'before'}
    feed = SyncChangeFeed(db)
    first = feed.pull('alice')
    feed.write('notes', 'old', delete=True)
    feed.write('notes', 'new', {'uid': 'alice', 'content': 'new'})
    cursor, _ = finish_bootstrap(feed, 'alice', first['cursor'])
    delta = feed.pull('alice', cursor)
    assert [(e['id'], e['deleted']) for e in delta['events']] == [('old', True), ('new', False)]


def test_unchanged_poll_reads_only_watermark_not_archive(db):
    feed = SyncChangeFeed(db)
    cursor, _ = finish_bootstrap(feed, 'alice')
    db.reads.clear()
    db.scans.clear()
    page = feed.pull('alice', cursor)
    assert page['events'] == [] and not page['has_more']
    assert sum(db.reads.values()) == 1
    assert sum(db.scans.values()) == 0


def test_record_and_change_commit_together_and_retry_is_idempotent(db):
    feed = SyncChangeFeed(db)
    db.fail = True
    with pytest.raises(RuntimeError):
        feed.write('notes', 'n', {'uid': 'alice', 'content': 'hello'})
    assert db.rows == {}
    db.fail = False
    feed.write('notes', 'n', {'uid': 'alice', 'content': 'hello'})
    feed.write('notes', 'n', {'uid': 'alice', 'content': 'hello'})
    state, _ = feed.refs('alice')
    assert state.get().to_dict()['revision'] == 1


def test_replaying_cursor_returns_same_changes_without_skipping(db):
    feed = SyncChangeFeed(db)
    cursor, _ = finish_bootstrap(feed, 'alice')
    for n in range(3):
        feed.write('notes', str(n), {'uid': 'alice'})
    a = feed.pull('alice', cursor, 2)
    assert a == feed.pull('alice', cursor, 2) and a['has_more']
    b = feed.pull('alice', a['cursor'], 2)
    assert [e['id'] for e in b['events']] == ['2']


def test_failed_cloud_write_is_not_acknowledged(monkeypatch):
    import asyncio
    from src.api.routers import sync
    fs = type('FS', (), {'is_available': True, 'save_note': lambda *args: False})()
    db = type('DB', (), {'create_note': lambda *args: None})()
    monkeypatch.setattr(sync, 'RecordStore', lambda: fs)
    monkeypatch.setattr(sync, 'DatabaseService', lambda: db)
    result = asyncio.run(sync.push_offline_records(sync.SyncPushRequest(notes=[{'id': 'n'}]), 'alice'))
    assert result.synced['notes'] == []
