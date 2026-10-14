from collections import Counter

from src.services.record_store import RecordStore


class Snapshot:
    def __init__(self, row):
        self.id, self.row = row['id'], row

    def to_dict(self):
        return dict(self.row)


class Query:
    def __init__(self, db, name, filters=(), cap=None):
        self.db, self.name, self.filters, self.cap = db, name, filters, cap

    def where(self, *args, filter=None):
        condition = (filter.field_path, filter.op_string, filter.value) if filter else args
        return Query(self.db, self.name, self.filters + (condition,), self.cap)

    def limit(self, cap):
        return Query(self.db, self.name, self.filters, cap)

    def order_by(self, *args, **kwargs):
        return self

    def document(self, uid):
        return User(self.db, self.name + '/' + uid)

    def stream(self):
        rows = self.db.rows.get(self.name, [])
        for field, op, value in self.filters:
            assert op in ('==', 'in')
            rows = [row for row in rows if (row.get(field) == value if op == '==' else row.get(field) in value)]
        rows = rows[:self.cap] if self.cap is not None else rows
        self.db.scans[self.name] += 1
        self.db.reads[self.name] += len(rows)
        return [Snapshot(row) for row in rows]


class User:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def collection(self, name):
        return Query(self.db, self.path + '/' + name)


class Database:
    def __init__(self, rows):
        self.rows, self.reads, self.scans = rows, Counter(), Counter()

    def collection(self, name):
        return Query(self, name)


def service(rows):
    fs = object.__new__(RecordStore)
    fs._db = Database(rows)
    return fs


def test_sync_reads_sessions_once_and_keeps_orphans_out():
    fs = service({
        'chat_sessions': [{'id': 'a', 'uid': 'alice'}, {'id': 'b', 'uid': 'bob'}],
        'chat_messages': [
            {'id': 'm1', 'uid': 'alice', 'thread_id': 'a'},
            {'id': 'orphan', 'uid': 'alice', 'thread_id': 'deleted'},
            {'id': 'm2', 'uid': 'bob', 'thread_id': 'b'},
        ],
    })
    result = fs.process_sync_pull('alice')
    assert [row['id'] for row in result['chat_messages']] == ['m1']
    assert fs._db.scans['chat_sessions'] == 1
    assert fs._db.reads['chat_sessions'] == 1
    assert fs._db.reads['chat_messages'] == 2  # Bob's data is never fetched.


def test_sync_without_sessions_skips_message_archive():
    fs = service({'chat_messages': [{'id': 'orphan', 'uid': 'alice', 'thread_id': 'deleted'}]})
    assert fs.process_sync_pull('alice')['chat_messages'] == []
    assert fs._db.scans['chat_messages'] == 0


def test_record_queries_filter_owner_before_streaming():
    fs = service({name: [{'id': 'a', 'uid': 'alice'}, {'id': 'b', 'uid': 'bob'}]
                  for name in ('reminders', 'notes', 'places')})
    for name, getter in [('reminders', fs.get_reminders), ('notes', fs.get_notes), ('places', fs.get_places)]:
        assert [row['id'] for row in getter('alice')] == ['a']
        assert fs._db.reads[name] == 1
        assert len(getter()) == 2  # Explicit unscoped administrative reads still work.


def test_pending_notifications_do_not_read_acknowledged_history():
    name = 'users/alice/notifications'
    fs = service({name: [{'id': 'pending', 'status': 'PENDING', 'created_at': '2026-01-01'}]
                  + [{'id': str(i), 'status': 'ACKNOWLEDGED', 'created_at': '2026-10-14'} for i in range(200)]})
    assert [row['id'] for row in fs.get_notifications('alice', 'PENDING')] == ['pending']
    assert fs._db.reads[name] == 1


def test_active_context_filters_skip_completed_history():
    mobility, semantic = 'users/alice/mobility_sessions', 'users/alice/semantic_contexts'
    fs = service({
        mobility: [{'id': 'open', 'status': 'ACTIVE'}] + [{'id': str(i), 'status': 'COMPLETED'} for i in range(100)],
        semantic: [{'id': 'open', 'active': True}] + [{'id': str(i), 'active': False} for i in range(100)],
    })
    assert [row['id'] for row in fs.get_mobility_sessions('alice', active_only=True)] == ['open']
    assert [row['id'] for row in fs.get_semantic_contexts('alice')] == ['open']
    assert fs._db.reads[mobility] == fs._db.reads[semantic] == 1
