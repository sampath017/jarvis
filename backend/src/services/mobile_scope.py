"""Disposable SQL workspace supplied by Android, with explicit entity-row deltas."""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
import json
import sqlite3
import threading
import uuid

current: ContextVar[MobileScope | None] = ContextVar('mobile_scope', default=None)
UI_TABLES = ('reminders', 'notes', 'places')
DOMAIN_TABLES = ('tasks', 'preferences', 'automations', 'context_rules', 'context_events',
                 'mobility_sessions', 'dynamic_reminder_state', 'context_trigger_state')
EXCLUDED_STATE_TABLES = frozenset({'activity_cache_state', 'command_runs', 'command_control',
    'notifications', 'ai_usage', 'runtime_control', 'file_memories', 'file_analyses',
    })


def mobile_only():
    """Android owns personal records; there is no legacy server-storage mode."""
    return True


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
        self.uid = 'jarvis_local_user'
        self.budget = None
        self.budget_before = {}
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
            try:
                self.db.execute(statement)
            except sqlite3.OperationalError:
                pass
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

    def _sql(self):
        from .sqlite_store import SqlStore
        return SqlStore()

    @staticmethod
    def _state_tables():
        from .sqlite_store import STATE_COLUMNS
        return set(STATE_COLUMNS) - EXCLUDED_STATE_TABLES

    def _import_domain(self, values, *, ignore_existing=False):
        if not isinstance(values, dict):
            raise ValueError('Invalid SQL domain state')
        for table, rows in values.items():
            if table not in DOMAIN_TABLES or not isinstance(rows, list) or len(rows) > 5000:
                raise ValueError('Invalid SQL domain state')
            columns = {r['name'] for r in self.db.execute(f'PRAGMA table_info("{table}")')}
            for row in rows:
                data = {k: v for k, v in row.items() if k in columns}
                if 'uid' in columns:
                    data['uid'] = self.uid
                if not data:
                    continue
                names = list(data)
                quoted = ','.join('"' + name + '"' for name in names)
                mode = 'IGNORE' if ignore_existing else 'REPLACE'
                self.db.execute(f'INSERT OR {mode} INTO "{table}" ({quoted}) VALUES ({",".join("?" for _ in names)})',
                    [json.dumps(data[k]) if isinstance(data[k], (dict, list)) else data[k] for k in names])

    def _import_state(self, sql, rows, *, ignore_existing=False):
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError('SQL state row limit exceeded')
        allowed = self._state_tables()
        for row in rows:
            table = row.get('table')
            if table not in allowed or not isinstance(row.get('data'), dict) or not row.get('id'):
                raise ValueError('Invalid SQL state record')
            identifier = str(row['id'])
            if ignore_existing and sql.get(table, identifier, uid=self.uid) is not None:
                continue
            sql.put(table, identifier, {**row['data'], 'uid': self.uid}, uid=self.uid, merge=False)

    def seed(self, value, uid='jarvis_local_user'):
        if not isinstance(value, dict):
            raise ValueError('Invalid mobile state')
        self.uid = uid
        records = value.get('records', {})
        if not isinstance(records, dict):
            raise ValueError('Invalid UI records')
        self.base_versions = {table: {str(row['id']): row.get('updated_at') for row in records.get(table, [])}
                              for table in UI_TABLES}
        sql = self._sql()
        agent = value.get('agent', {})
        if not isinstance(agent, dict) or set(agent) - {'domain', 'records'}:
            raise ValueError('Invalid SQL agent state')
        with sql.atomic():
            for table in UI_TABLES:
                rows = records.get(table, [])
                if not isinstance(rows, list) or len(rows) > 10000:
                    raise ValueError('Mobile record limit exceeded')
                for row in rows:
                    sql.put(table, str(row['id']), {**row, 'uid': uid}, uid=uid, merge=False)
            self._import_domain(agent.get('domain', {}))
            self._import_state(sql, agent.get('records', []))
        self.budget_before = value.get('budget') or {}
        self.baseline = self.snapshot()

    def import_read(self, value, uid='jarvis_local_user'):
        """Import tool-selected SQL baselines without overwriting earlier tool writes."""
        sql = self._sql()
        with self.lock:
            before = self.snapshot()
            with sql.atomic():
                for table in UI_TABLES:
                    for row in value.get('records', {}).get(table, []):
                        if sql.get(table, str(row['id']), uid=uid) is not None:
                            continue
                        sql.put(table, str(row['id']), {**row, 'uid': uid}, uid=uid, merge=False)
                        self.base_versions.setdefault(table, {})[str(row['id'])] = row.get('updated_at')
                agent = value.get('agent', {})
                if not isinstance(agent, dict) or set(agent) - {'domain', 'records'}:
                    raise ValueError('Invalid SQL agent state')
                self._import_domain(agent.get('domain', {}), ignore_existing=True)
                self._import_state(sql, agent.get('records', []), ignore_existing=True)
            after = self.snapshot()
            for table in (*UI_TABLES, *DOMAIN_TABLES):
                key = '__key' if table in DOMAIN_TABLES else 'id'
                prior = {r[key] for r in before.get(table, [])}
                baseline_keys = {r[key] for r in self.baseline.get(table, [])}
                self.baseline.setdefault(table, []).extend(r for r in after[table]
                    if r[key] not in prior and r[key] not in baseline_keys)
            prior = {self._state_key(r) for r in before['state_records']}
            baseline_keys = {self._state_key(r) for r in self.baseline.get('state_records', [])}
            self.baseline.setdefault('state_records', []).extend(r for r in after['state_records']
                if self._state_key(r) not in prior and self._state_key(r) not in baseline_keys)

    def row_key(self, table, row):
        columns = sorted((r for r in self.db.execute(f'PRAGMA table_info("{table}")') if r['pk']), key=lambda r: r['pk'])
        return json.dumps([row.get(column['name']) for column in columns], separators=(',', ':'))

    @staticmethod
    def _state_key(row):
        return row['table'], row['id'], row.get('uid', '')

    def snapshot(self):
        from .sqlite_store import TABLES
        sql = self._sql()
        result = {}
        with self.connection() as db:
            for table in UI_TABLES:
                result[table] = [{k: v for k, v in row.items() if k != '_key'} for row in sql.list(table, uid=self.uid)]
            for table in DOMAIN_TABLES:
                result[table] = [{**dict(row), '__key': self.row_key(table, dict(row))}
                                 for row in db.execute(f'SELECT * FROM "{table}" WHERE uid=?', (self.uid,))]
            result['state_records'] = sql.export_records(exclude_tables=EXCLUDED_STATE_TABLES & TABLES)
            result['state_records'] = [r for r in result['state_records'] if r['table'] in self._state_tables() and r['uid'] == self.uid]
            result['notifications'] = sql.list('notifications', uid=self.uid)
        return result

    def changes(self):
        now = self.snapshot()
        records, deleted, domain, domain_deleted = {}, {}, {}, {}
        for table in UI_TABLES:
            before = {r['id']: r for r in self.baseline.get(table, [])}
            after = {r['id']: r for r in now[table]}
            records[table] = [r for key, r in after.items() if before.get(key) != r]
            deleted[table] = list(set(before) - set(after))
        for table in DOMAIN_TABLES:
            before = {r['__key']: r for r in self.baseline.get(table, [])}
            after = {r['__key']: r for r in now[table]}
            domain[table] = [r for key, r in after.items() if before.get(key) != r]
            domain_deleted[table] = list(set(before) - set(after))
        before = {self._state_key(r): r for r in self.baseline.get('state_records', [])}
        after = {self._state_key(r): r for r in now['state_records']}
        changed = [r for key, r in after.items() if before.get(key) != r]
        removed = [{'table': key[0], 'id': key[1], 'uid': key[2]} for key in set(before) - set(after)]
        old_alerts = {r['id']: r for r in self.baseline.get('notifications', [])}
        alerts = [{k: v for k, v in r.items() if k != '_key'} for r in now['notifications']
                  if old_alerts.get(r['id']) != r]
        budget = {}
        if self.budget is not None:
            budget = {'day': self.budget.day.isoformat(), **{
                key: max(0, getattr(self.budget, key) - self.budget_before.get(key, 0))
                for key in ('cost_nanos', 'call_count', 'estimated_tokens')}}
        return {'operation_id': self.operation_id, 'records': records, 'deleted': deleted,
                'base_versions': self.base_versions,
                'agent': {'domain': domain, 'records': changed, 'removed': removed, 'domain_deleted': domain_deleted},
                'notifications': alerts, 'budget': budget}
