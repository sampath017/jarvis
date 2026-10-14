"""Ordered, atomic changes for mobile records; existing clients keep full sync."""
import base64
import hashlib
import json
from datetime import datetime, timezone

from src.services import sqlite_documents as documents
from src.services.sqlite_documents import FieldFilter

COLLECTIONS = ('reminders', 'notes', 'places', 'chat_sessions', 'chat_messages')


class SyncChangeFeed:
    def __init__(self, db):
        self.db = db
        self.generation = getattr(db, 'generation', None)

    def _token(self, uid, **state):
        if self.generation is not None:
            state['generation'] = self.generation
        return self.token(uid, **state)

    def refs(self, uid):
        user = self.db.collection('users').document(uid)
        return user.collection('sync_state').document('records'), user.collection('sync_changes')

    def append(self, tx, uid, collection, record_id, data):
        """Call after other reads, before any transaction writes."""
        state, changes = self.refs(uid)
        revision = int((state.get(transaction=tx).to_dict() or {}).get('revision', 0)) + 1
        tx.set(state, {'revision': revision})
        tx.set(changes.document(f'{revision:020d}'), {
            'revision': revision, 'collection': collection, 'id': record_id,
            'deleted': data is None,
            'thread_id': data.get('thread_id') if data and collection == 'chat_messages' else None,
        })

    def write(self, collection, record_id, data=None, *, delete=False):
        ref = self.db.collection(collection).document(record_id)

        @documents.transactional
        def commit(tx):
            previous = ref.get(transaction=tx).to_dict() or {}
            if delete and not previous:
                return
            current = None if delete else {**previous, **data, 'id': record_id}
            uid = (previous if delete else current).get('uid') or 'jarvis_local_user'
            if previous.get('uid') and not delete and previous['uid'] != uid:
                raise ValueError('Record belongs to another user')
            if not delete and current == previous:
                return
            parent_ref, parent_value = None, None
            if not delete and collection == 'chat_sessions':
                from .chat_archive_policy import last_activity
                activity = last_activity(current)
                if activity:
                    current['archive_activity_at'] = activity
                current['archive_pending'] = True
            elif not delete and collection == 'chat_messages' and current.get('thread_id'):
                # A new message and its age marker commit together. Automatic
                # archive transactions conflict with either kind of activity.
                from .chat_archive_policy import last_activity
                parent_ref = self.db.collection('chat_sessions').document(current['thread_id'])
                parent = parent_ref.get(transaction=tx).to_dict() or {}
                if parent.get('uid') == uid:
                    parent_value = {**parent, 'archive_pending': True,
                                    'archive_activity_at': max(last_activity(parent) or datetime.min.replace(tzinfo=timezone.utc),
                                                               datetime.now(timezone.utc))}
            self.append(tx, uid, collection, record_id, current)
            if delete:
                tx.delete(ref)
            else:
                tx.set(ref, current)
                if parent_value is not None:
                    tx.set(parent_ref, parent_value)

        commit(self.db.transaction())

    @staticmethod
    def token(uid, **state):
        value = {'v': 1, 'owner': hashlib.sha256(uid.encode()).hexdigest(), **state}
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode()

    @staticmethod
    def decode(uid, cursor):
        try:
            value = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
            if (value.get('v') != 1 or value.get('owner') != hashlib.sha256(uid.encode()).hexdigest()
                    or type(value.get('revision')) is not int or value['revision'] < 0
                    or value.get('phase') not in ('bootstrap', 'changes')):
                raise ValueError()
            if value['phase'] == 'bootstrap':
                if type(value.get('part')) is not int or not 0 <= value['part'] < len(COLLECTIONS):
                    raise ValueError()
                if not isinstance(value.get('after', ''), str) or '/' in value.get('after', ''):
                    raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('Invalid sync cursor; start a new bootstrap') from None

    def pull(self, uid, cursor=None, limit=100):
        if not 1 <= limit <= 200:
            raise ValueError('Invalid sync page size')
        state_ref, changes = self.refs(uid)
        if cursor:
            state = self.decode(uid, cursor)
            if self.generation is not None and state.get('generation') != self.generation:
                raise ValueError('API cache was recreated; rehydrate it from the phone')
        else:
            revision = int((state_ref.get().to_dict() or {}).get('revision', 0))
            state = {'phase': 'bootstrap', 'part': 0, 'after': '', 'revision': revision}
        if state['phase'] == 'bootstrap':
            name = COLLECTIONS[state['part']]
            query = self.db.collection(name).where(filter=FieldFilter('uid', '==', uid)).order_by('__name__')
            if state['after']:
                query = query.start_after({'__name__': self.db.collection(name).document(state['after'])})
            rows = list(query.limit(limit + 1).stream())
            selected = rows[:limit]
            events = [{'collection': name, 'id': row.id, 'deleted': False,
                       'data': {**row.to_dict(), 'id': row.id}} for row in selected]
            if len(rows) > limit:
                next_state = {**state, 'after': selected[-1].id}
                done = False
            elif state['part'] + 1 < len(COLLECTIONS):
                next_state = {**state, 'part': state['part'] + 1, 'after': ''}
                done = False
            else:
                next_state = {'phase': 'changes', 'revision': state['revision']}
                done = True
            return {'events': events, 'cursor': self._token(uid, **next_state),
                    'has_more': True, 'bootstrap': True, 'bootstrap_complete': done}
        head = int((state_ref.get().to_dict() or {}).get('revision', 0))
        if state['revision'] > head:
            raise ValueError('Sync cursor is ahead of the server; start a new bootstrap')
        if head == state['revision']:
            return {'events': [], 'cursor': cursor, 'has_more': False, 'bootstrap': False}
        query = changes.order_by('__name__').start_after({
            '__name__': changes.document(f"{state['revision']:020d}")})
        rows = list(query.limit(limit + 1).stream())
        selected = rows[:limit]
        if not selected:
            raise RuntimeError('Sync history unavailable; cursor was not advanced')
        events = []
        parents = {}
        latest = {}
        for row in selected:
            event = row.to_dict()
            latest[(event['collection'], event['id'])] = event
        for event in latest.values():
            if event['deleted']:
                events.append({**event, 'data': None})
                continue
            value = self.db.collection(event['collection']).document(event['id']).get().to_dict()
            if value:
                if value.get('uid') != uid:
                    raise RuntimeError('Sync record ownership changed; cursor was not advanced')
                events.append({**event, 'data': {**value, 'id': event['id']}})
            else:
                thread = event.get('thread_id')
                if thread and event['collection'] == 'chat_messages':
                    if thread not in parents:
                        parents[thread] = self.db.collection('chat_sessions').document(thread).get().to_dict() or {}
                    if parents[thread].get('uid') == uid and parents[thread].get('archive_drive_id'):
                        continue  # Archived body is on Drive; keep phone originals.
                events.append({**event, 'deleted': True, 'data': None})
        return {'events': events,
                'cursor': self._token(uid, phase='changes', revision=selected[-1].to_dict()['revision']),
                'has_more': len(rows) > limit, 'bootstrap': False}
