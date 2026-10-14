"""SQLite document records for the API's existing domain repositories.

No network client is involved. Transactions use BEGIN IMMEDIATE, including
across processes, and queries filter/page in SQLite rather than loading a store.
The Android database remains the durable copy when the API runs on Cloud Run.
"""
from __future__ import annotations

import copy
import functools
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace


class AlreadyExists(Exception):
    pass


class NotFound(Exception):
    pass


@dataclass(frozen=True)
class FieldFilter:
    field_path: str
    op_string: str
    value: object


@dataclass(frozen=True)
class Increment:
    value: int


def _encode(value):
    if isinstance(value, datetime):
        return {'__jarvis_datetime__': value.isoformat()}
    raise TypeError(f'Unsupported record value: {type(value).__name__}')


def _decode(value):
    if set(value) == {'__jarvis_datetime__'}:
        return datetime.fromisoformat(value['__jarvis_datetime__'])
    return value


def _merge(previous, incoming):
    result = copy.deepcopy(previous)
    for field, value in incoming.items():
        target = result
        parts = field.split('.')
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        key = parts[-1]
        if isinstance(value, Increment):
            target[key] = target.get(key, 0) + value.value
        elif isinstance(value, dict):
            target[key] = _merge(target.get(key, {}) if isinstance(target.get(key), dict) else {}, value)
        else:
            target[key] = copy.deepcopy(value)
    return result


class Client:
    def __init__(self, path=None):
        from .mobile_scope import current
        self._scope = current.get() if path is None else None
        if self._scope is not None:
            self.path = ':memory:'
            self._local = threading.local()
            self._initialize()
            return
        from .database.connection import get_db_path
        self.path = str(path or get_db_path())
        self._local = threading.local()
        self._initialize()

    def _initialize(self):
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS document_records (
                    collection TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(collection, id));
                CREATE INDEX IF NOT EXISTS idx_document_owner
                    ON document_records(collection,
                        COALESCE(json_extract(payload, '$.uid.__jarvis_datetime__'), json_extract(payload, '$.uid')), id);
                CREATE INDEX IF NOT EXISTS idx_document_time
                    ON document_records(collection,
                        COALESCE(json_extract(payload, '$.timestamp.__jarvis_datetime__'), json_extract(payload, '$.timestamp')), id);
                CREATE INDEX IF NOT EXISTS idx_document_thread
                    ON document_records(collection,
                        COALESCE(json_extract(payload, '$.thread_id.__jarvis_datetime__'), json_extract(payload, '$.thread_id')), id);
                CREATE TABLE IF NOT EXISTS document_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO document_metadata VALUES (?, ?)', ('generation', uuid.uuid4().hex))
            self.generation = db.execute("SELECT value FROM document_metadata WHERE key='generation'").fetchone()[0]

    @contextmanager
    def connection(self):
        active = getattr(self._local, 'connection', None)
        if active is not None:
            yield active
            return
        if self._scope is not None:
            with self._scope.connection() as db:
                with db:
                    yield db
            return
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def collection(self, name):
        return Collection(self, name)

    def transaction(self):
        return Transaction(self)

    def batch(self):
        return Batch(self)


class Snapshot:
    def __init__(self, reference, value):
        self.reference = reference
        self.id = reference.id
        self.exists = value is not None
        self._value = value

    def to_dict(self):
        return copy.deepcopy(self._value)


class Document:
    def __init__(self, client, collection, identifier):
        self._client = client
        self.collection_path = collection
        self.id = identifier
        self.path = f'{collection}/{identifier}'

    def collection(self, name):
        return Collection(self._client, f'{self.path}/{name}')

    def get(self, transaction=None, **kwargs):
        with self._client.connection() as db:
            row = db.execute('SELECT payload FROM document_records WHERE collection=? AND id=?',
                             (self.collection_path, self.id)).fetchone()
        return Snapshot(self, json.loads(row[0], object_hook=_decode) if row else None)

    def set(self, value, merge=False):
        @transactional
        def save(tx):
            current = self.get().to_dict() or {} if merge else {}
            payload = json.dumps(_merge(current, value), default=_encode, separators=(',', ':'))
            with self._client.connection() as db:
                db.execute('INSERT INTO document_records VALUES (?, ?, ?) '
                           'ON CONFLICT(collection,id) DO UPDATE SET payload=excluded.payload',
                           (self.collection_path, self.id, payload))
        save(self._client.transaction())

    def create(self, value):
        @transactional
        def save(tx):
            if self.get().exists:
                raise AlreadyExists(self.path)
            self.set(value)
        save(self._client.transaction())

    def update(self, value):
        @transactional
        def save(tx):
            if not self.get().exists:
                raise NotFound(self.path)
            self.set(value, merge=True)
        save(self._client.transaction())

    def delete(self):
        with self._client.connection() as db:
            db.execute('DELETE FROM document_records WHERE collection=? AND id=?', (self.collection_path, self.id))


class Query:
    ASCENDING = 'ASCENDING'
    DESCENDING = 'DESCENDING'

    def __init__(self, client, path, filters=(), orders=(), maximum=None, after=None):
        self._client, self.path = client, path
        self.filters, self.orders, self.maximum, self.after = filters, orders, maximum, after

    def _clone(self, **changes):
        values = dict(filters=self.filters, orders=self.orders, maximum=self.maximum, after=self.after)
        return Query(self._client, self.path, **{**values, **changes})

    def where(self, field_path=None, op_string=None, value=None, *, filter=None):
        condition = filter or FieldFilter(field_path, op_string, value)
        return self._clone(filters=(*self.filters, condition))

    def order_by(self, field, direction=ASCENDING):
        if direction not in (self.ASCENDING, self.DESCENDING):
            raise ValueError('Invalid ordering')
        return self._clone(orders=(*self.orders, (field, direction)))

    def limit(self, maximum):
        return self._clone(maximum=max(0, int(maximum)))

    def start_after(self, value):
        if isinstance(value, Snapshot):
            value = {**value.to_dict(), '__name__': value.reference}
        return self._clone(after=value)

    @staticmethod
    def _field(field):
        if field == '__name__':
            return 'id'
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*', field):
            raise ValueError('Invalid record field')
        path = '$.' + field
        return f"COALESCE(json_extract(payload, '{path}.__jarvis_datetime__'), json_extract(payload, '{path}'))"

    @staticmethod
    def _value(value):
        if isinstance(value, Document):
            return value.id
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _statement(self):
        clauses, args = ['collection=?'], [self.path]
        for condition in self.filters:
            field, operator, value = self._field(condition.field_path), condition.op_string, condition.value
            if operator in ('in', 'not-in'):
                values = list(value)
                clauses.append(f'{field} {"NOT IN" if operator == "not-in" else "IN"} ({",".join("?" for _ in values)})')
                args.extend(self._value(item) for item in values)
            elif operator == 'array_contains':
                clauses.append(f'EXISTS (SELECT 1 FROM json_each({field}) WHERE value=?)')
                args.append(self._value(value))
            elif operator in ('==', '!=', '<', '<=', '>', '>='):
                clauses.append(f'{field} {"IS" if operator == "==" and value is None else "IS NOT" if operator == "!=" and value is None else "=" if operator == "==" else operator} ?')
                args.append(self._value(value))
            else:
                raise ValueError(f'Unsupported query operator: {operator}')
        orders = self.orders or (('__name__', self.ASCENDING),)
        if self.after:
            alternatives = []
            for index, (name, direction) in enumerate(orders):
                equal = [f'{self._field(n)} = ?' for n, _ in orders[:index]]
                alternatives.append('(' + ' AND '.join([*equal, f'{self._field(name)} {"<" if direction == self.DESCENDING else ">"} ?']) + ')')
                args.extend(self._value(self.after[n]) for n, _ in orders[:index])
                args.append(self._value(self.after[name]))
            clauses.append('(' + ' OR '.join(alternatives) + ')')
        sql = 'SELECT id,payload FROM document_records WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY ' + ','.join(f'{self._field(n)} {"DESC" if d == self.DESCENDING else "ASC"}' for n, d in orders)
        if self.maximum is not None:
            sql += ' LIMIT ?'
            args.append(self.maximum)
        return sql, args

    def stream(self, transaction=None, **kwargs):
        sql, args = self._statement()
        with self._client.connection() as db:
            rows = db.execute(sql, args).fetchall()
        return iter(Snapshot(Document(self._client, self.path, identifier), json.loads(payload, object_hook=_decode)) for identifier, payload in rows)

    def get(self, **kwargs):
        return list(self.stream(**kwargs))

    def count(self):
        def get():
            sql, args = self._statement()
            with self._client.connection() as db:
                value = db.execute(f'SELECT COUNT(*) FROM ({sql})', args).fetchone()[0]
            return [[SimpleNamespace(value=value)]]
        return SimpleNamespace(get=get)


class Collection(Query):
    def document(self, identifier=None):
        identifier = identifier or uuid.uuid4().hex
        if not isinstance(identifier, str) or not identifier or '/' in identifier:
            raise ValueError('Invalid document identifier')
        return Document(self._client, self.path, identifier)


class Transaction:
    def __init__(self, client):
        self.client = client

    def set(self, ref, value, merge=False):
        ref.set(value, merge=merge)

    def update(self, ref, value):
        ref.update(value)

    def delete(self, ref):
        ref.delete()


def transactional(function):
    @functools.wraps(function)
    def execute(transaction, *args, **kwargs):
        client = transaction.client
        if getattr(client._local, 'connection', None) is not None:
            return function(transaction, *args, **kwargs)
        with client.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            client._local.connection = db
            try:
                return function(transaction, *args, **kwargs)
            finally:
                client._local.connection = None
    return execute


class Batch(Transaction):
    def __init__(self, client):
        super().__init__(client)
        self.operations = []

    def set(self, ref, value, merge=False):
        self.operations.append(lambda: ref.set(value, merge=merge))

    def update(self, ref, value):
        self.operations.append(lambda: ref.update(value))

    def delete(self, ref):
        self.operations.append(ref.delete)

    def commit(self):
        @transactional
        def apply(tx):
            for operation in self.operations:
                operation()
        apply(self.client.transaction())
        self.operations.clear()
