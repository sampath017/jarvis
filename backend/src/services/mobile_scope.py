"""A disposable in-memory working view supplied by Android for one operation.

Android owns every durable record. SQL is used here only as an implementation
detail of existing agent tools; no database or personal log file is opened.
"""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
import json
import os
import sqlite3
import threading
import uuid

current: ContextVar[MobileScope | None] = ContextVar('mobile_scope', default=None)
UI_TABLES = ('reminders', 'notes', 'places')
DOMAIN_TABLES = ('tasks', 'preferences', 'automations', 'context_rules', 'context_events', 'mobility_sessions', 'dynamic_reminder_state', 'context_trigger_state')
EXCLUDED_DOCS = {'chat_messages', 'chat_sessions', 'sync_state', 'sync_changes',
                 'activity_cache_state', 'command_runs', 'command_control', 'notifications'}


def mobile_only():
    return os.getenv('JARVIS_STORAGE_MODE', 'mobile') == 'mobile'


class MobileScope:
    def __init__(self):
        from .database.schema import SCHEMA_SQL
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.refs = 1
        self.closed = False
        self.record_store = None
        self.operation_id = uuid.uuid4().hex
        self.budget = None
        self.budget_before = None
        self.db.executescript(SCHEMA_SQL)
        for statement in (
            "ALTER TABLE reminders ADD COLUMN dynamic_policy TEXT",
            "ALTER TABLE reminders ADD COLUMN activity_delay_seconds INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reminders ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'notification'",
            "ALTER TABLE notes ADD COLUMN deleted_at TEXT",
            "ALTER TABLE reminders ADD COLUMN previous_status TEXT",
            "ALTER TABLE reminders ADD COLUMN deleted_at TEXT",
            "ALTER TABLE places ADD COLUMN notes TEXT DEFAULT ''",
            "ALTER TABLE places ADD COLUMN tags TEXT DEFAULT '[]'",
            "ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'",
        ):
            try: self.db.execute(statement)
            except sqlite3.OperationalError: pass
        self.db.commit()
        self.baseline = {}
        self.base_versions = {}

    @contextmanager
    def connection(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('Mobile operation has finished')
            yield self.db

    def retain(self):
        with self.lock:
            self.refs += 1

    def release(self):
        with self.lock:
            self.refs -= 1
            if self.refs == 0 and not self.closed:
                self.closed = True
                self.db.close()

    def seed(self, value, uid='jarvis_local_user'):
        from . import sqlite_documents as docs
        if not isinstance(value, dict):
            raise ValueError('Invalid mobile state')
        records = value.get('records', {})
        self.base_versions = {table: {str(row['id']): row.get('updated_at') for row in records.get(table, [])}
                              for table in UI_TABLES}
        from .database import DatabaseService
        domain = DatabaseService()
        client = docs.Client()
        for table in UI_TABLES:
            rows = records.get(table, [])
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError('Mobile record limit exceeded')
            for row in rows:
                data = {**row, 'uid': uid}
                getattr(domain, {'notes': 'create_note', 'reminders': 'create_reminder', 'places': 'create_place'}[table])(uid, data)
                client.collection(table).document(str(row['id'])).set(data)
        agent = value.get('agent', {})
        for table, rows in agent.get('domain', {}).items():
            if table not in DOMAIN_TABLES or not isinstance(rows, list) or len(rows) > 5000:
                raise ValueError('Invalid mobile domain state')
            columns = {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}
            for row in rows:
                data = {k: v for k, v in row.items() if k in columns}
                if 'uid' in columns:
                    data['uid'] = uid
                if data:
                    names = list(data)
                    self.db.execute(f'INSERT OR REPLACE INTO {table} ({",".join(names)}) VALUES ({",".join("?" for _ in names)})',
                                    [json.dumps(data[k]) if isinstance(data[k], (dict, list)) else data[k] for k in names])
        for row in agent.get('documents', []):
            collection = row.get('collection', '')
            parts = collection.split('/')
            if len(parts) != 3 or parts[0] != 'users' or parts[2] in EXCLUDED_DOCS:
                raise ValueError('Invalid mobile document state')
            data = json.loads(json.dumps(row['data']), object_hook=docs._decode)
            client.collection(f'users/{uid}/{parts[2]}').document(row['id']).set(data)
        self.db.commit()
        self.budget_before = value.get('budget') or {}
        self.baseline = self.snapshot()

    def import_read(self, value, uid='jarvis_local_user'):
        # Add only tool-requested records. Never overwrite changes already made
        # by an earlier tool in this operation.
        from .database import DatabaseService
        from . import sqlite_documents as docs
        domain = DatabaseService()
        client = docs.Client()
        with self.lock:
            before_docs = {(r['collection'], r['id']) for r in self.snapshot()['documents']}
            imported_docs = set()
            for table in UI_TABLES:
                for row in value.get('records', {}).get(table, []):
                    if any(r['id'] == row['id'] for r in self.snapshot()[table]):
                        continue
                    data = {**row, 'uid': uid}
                    getattr(domain, {'notes':'create_note','reminders':'create_reminder','places':'create_place'}[table])(uid,data)
                    client.collection(table).document(str(row['id'])).set(data)
                    imported_docs.add((table, str(row['id'])))
                    self.base_versions.setdefault(table,{})[str(row['id'])]=row.get('updated_at')
                    self.baseline.setdefault(table,[]).extend(r for r in self.snapshot()[table] if r['id']==row['id'])
            for row in value.get('agent',{}).get('documents',[]):
                parts=row['collection'].split('/')
                if len(parts)!=3 or parts[0]!='users' or parts[2] in EXCLUDED_DOCS: continue
                collection=f'users/{uid}/{parts[2]}'
                ref=client.collection(collection).document(row['id'])
                if ref.get().exists: continue
                ref.set(json.loads(json.dumps(row['data']),object_hook=docs._decode))
                imported_docs.add((collection, str(row['id'])))
            for table, rows in value.get('agent', {}).get('domain', {}).items():
                if table not in DOMAIN_TABLES or len(rows) > 5000:
                    raise ValueError('Invalid mobile domain read')
                columns = {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}
                before = {r['__key'] for r in self.snapshot()[table]}
                for row in rows:
                    data = {k: v for k, v in row.items() if k in columns}
                    if 'uid' in columns: data['uid'] = uid
                    if self.row_key(table, data) in before: continue
                    names = list(data)
                    self.db.execute(f'INSERT OR IGNORE INTO {table} ({",".join(names)}) VALUES ({",".join("?" for _ in names)})',
                        [json.dumps(data[k]) if isinstance(data[k], (dict, list)) else data[k] for k in names])
                self.baseline.setdefault(table, []).extend(r for r in self.snapshot()[table] if r['__key'] not in before)
            # Newly read documents are a baseline, rather than app mutations.
            existing={(r['collection'],r['id']) for r in self.baseline.get('documents',[])}
            self.baseline.setdefault('documents',[]).extend(r for r in self.snapshot()['documents']
                if (r['collection'],r['id']) not in existing and (r['collection'],r['id']) in imported_docs
                and (r['collection'],r['id']) not in before_docs)
            self.db.commit()

    def row_key(self, table, row):
        columns = sorted((r for r in self.db.execute(f'PRAGMA table_info({table})') if r['pk']), key=lambda r:r['pk'])
        return json.dumps([row.get(r['name']) for r in columns], separators=(',', ':'))

    def snapshot(self):
        result = {}
        with self.connection() as db:
            for table in (*UI_TABLES, *DOMAIN_TABLES):
                result[table] = [dict(row) for row in db.execute(f'SELECT * FROM {table}')]
                if table in DOMAIN_TABLES:
                    result[table] = [{**row, '__key': self.row_key(table, row)} for row in result[table]]
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='document_records'").fetchone()
            result['documents'] = [dict(row) for row in db.execute('SELECT * FROM document_records')] if exists else []
        return result

    def changes(self):
        from . import sqlite_documents as docs
        now = self.snapshot()
        records, deleted, domain, documents = {}, {}, {}, []
        for table in UI_TABLES:
            before = {r['id']: r for r in self.baseline.get(table, [])}
            after = {r['id']: r for r in now[table]}
            # Tools may update either repository; use document values where changed.
            for row in now['documents']:
                if row['collection'] == table:
                    previous = next((r['payload'] for r in self.baseline.get('documents', [])
                                     if r['collection'] == table and r['id'] == row['id']), None)
                    if row['payload'] != previous:
                        after[row['id']] = json.loads(row['payload'], object_hook=docs._decode)
            records[table] = [r for key, r in after.items() if before.get(key) != r]
            doc_ids = {r['id'] for r in now['documents'] if r['collection'] == table}
            old_doc_ids = {r['id'] for r in self.baseline.get('documents', []) if r['collection'] == table}
            deleted[table] = list((set(before) - set(after)) | (old_doc_ids - doc_ids))
        domain_deleted = {}
        for table in DOMAIN_TABLES:
            before = {r['__key']: r for r in self.baseline.get(table, [])}
            after = {r['__key']: r for r in now[table]}
            domain[table] = [r for key, r in after.items() if before.get(key) != r]
            domain_deleted[table] = list(set(before) - set(after))
        old_docs = {(r['collection'], r['id']): r['payload'] for r in self.baseline.get('documents', [])}
        notifications = []
        for row in now['documents']:
            parts = row['collection'].split('/')
            if len(parts) != 3 or parts[0] != 'users':
                continue
            if parts[2] == 'notifications':
                notifications.append(json.loads(row['payload']))
            elif parts[2] not in EXCLUDED_DOCS and old_docs.get((row['collection'], row['id'])) != row['payload']:
                documents.append({'collection': row['collection'], 'id': row['id'], 'data': json.loads(row['payload'])})
        budget = {}
        if self.budget is not None:
            budget = {'day': self.budget.day.isoformat(),
                      'cost_nanos': max(0, self.budget.cost_nanos - self.budget_before.get('cost_nanos', 0)),
                      'call_count': max(0, self.budget.call_count - self.budget_before.get('call_count', 0)),
                      'estimated_tokens': max(0, self.budget.estimated_tokens - self.budget_before.get('estimated_tokens', 0))}
        return {'operation_id': self.operation_id, 'records': records, 'deleted': deleted,
                'base_versions': self.base_versions, 'agent': {'domain': domain, 'documents': documents, 'domain_deleted': domain_deleted},
                'notifications': notifications, 'budget': budget}
