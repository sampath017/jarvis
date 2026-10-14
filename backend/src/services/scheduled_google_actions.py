"""Durable, explicitly requested Google actions; no model or phone at execution."""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from src.services import sqlite_documents as documents
from src.services.sqlite_documents import FieldFilter

from .background_tasks import BackgroundTasks
from .server_google_auth import ServerGoogleAuth
from .server_google_actions import ServerGoogleActions, event_payload

ALLOWED = {'create', 'update', 'delete', 'file_save', 'file_analyze', 'file_memory_search'}
logger = logging.getLogger(__name__)


def validate_action(action):
    if not isinstance(action, dict) or action.get('operation') not in ALLOWED:
        raise ValueError('Choose a supported Calendar or Drive action.')
    fields = {'operation', 'calendar_id', 'event_id', 'event', 'whole_series', 'file_id', 'question',
              'query', 'content_query', 'read_contents'}
    if set(action) - fields or len(json.dumps(action)) > 16000:
        raise ValueError('Unsupported or oversized scheduled action.')
    operation = action['operation']
    if operation in {'create', 'update'}:
        event_payload(action.get('event', {}), partial=operation == 'update')
    if operation in {'update', 'delete'} and not action.get('event_id'):
        raise ValueError('An existing event ID is required; search before scheduling this change.')
    if operation in {'file_save', 'file_analyze'} and not action.get('file_id'):
        raise ValueError('An existing Drive file ID is required.')
    if operation == 'file_analyze' and not action.get('question'):
        raise ValueError('A file analysis question is required.')
    return dict(action)


class ScheduledGoogleActions:
    def __init__(self, auth=None, tasks=None, executor_factory=None):
        self.auth = auth or ServerGoogleAuth()
        self.tasks = tasks or BackgroundTasks()
        self.executor_factory = executor_factory or (lambda owner: ServerGoogleActions(owner, auth=self.auth))

    def ref(self, owner, action_id):
        return self.auth.ref(owner).collection('scheduled_actions').document(action_id)

    def enqueue(self, owner, record):
        now = datetime.now(timezone.utc)
        due = datetime.fromisoformat(record['execute_at'])
        segment = max(0, int((due-now).total_seconds() // (28*86400)))
        when = min(due, now + timedelta(days=28))
        self.tasks.enqueue('google-action', {'owner': owner, 'action_id': record['id']},
                           f"google:{owner}:{record['id']}:{segment}", max(now, when))
        ref = self.ref(owner, record['id'])
        @documents.transactional
        def queued(tx):
            current = ref.get(transaction=tx).to_dict() or {}
            if current.get('status') in {'pending_queue', 'queued'}:
                tx.update(ref, {'status': 'queued'})
        queued(self.auth.db.transaction())

    def create(self, owner, operation_id, action, execute_at, title='Scheduled Google action', thread_id='cloud_actions'):
        if not self.tasks.configured:
            raise HTTPException(503, 'Durable cloud scheduling is not configured.')
        connection = self.auth.status(owner)
        if not connection['connected']:
            raise HTTPException(409, 'Connect cloud Google access before scheduling an unattended action.')
        action = validate_action(action)
        due = datetime.fromisoformat(execute_at.replace('Z', '+00:00'))
        if due.tzinfo is None or due <= datetime.now(timezone.utc):
            raise ValueError('Choose an explicit future execution time with a timezone offset.')
        due = due.astimezone(timezone.utc)
        action_id = hashlib.sha256(operation_id.encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps([action, due.isoformat()], sort_keys=True).encode()).hexdigest()
        ref = self.ref(owner, action_id)
        @documents.transactional
        def save(tx):
            old = ref.get(transaction=tx).to_dict()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'This schedule ID already belongs to another action.')
                return old
            record = {'id': action_id, 'owner': owner, 'fingerprint': fingerprint, 'title': title[:200],
                      'action': action, 'account_email': connection['email'].lower(), 'execute_at': due.isoformat(), 'status': 'pending_queue',
                      'thread_id': thread_id, 'created_at': datetime.now(timezone.utc).isoformat()}
            tx.set(ref, record)
            return record
        record = save(self.auth.db.transaction())
        if record['status'] == 'pending_queue':
            try:
                self.enqueue(owner, record)
            except Exception as exc:
                raise HTTPException(503, 'The action is saved but scheduling is pending. Its status will show when it is queued.') from exc
            record['status'] = 'queued'
        return {'status': 'ok', 'schedule': self.public(record),
                'message': 'Saved for server execution; no phone response is required at the due time.'}

    @staticmethod
    def public(record):
        return {k: record[k] for k in ('id', 'title', 'action', 'execute_at', 'status', 'result', 'error') if k in record}

    def list(self, owner):
        records = [d.to_dict() for d in self.auth.ref(owner).collection('scheduled_actions').order_by('execute_at', direction=documents.Query.DESCENDING).limit(50).stream()]
        return {'status': 'ok', 'schedules': [self.public(r) for r in records]}

    def cancel(self, owner, action_id):
        ref = self.ref(owner, action_id)
        @documents.transactional
        def cancel(tx):
            data = ref.get(transaction=tx).to_dict()
            if not data:
                raise HTTPException(404, 'Scheduled action not found.')
            if data['status'] not in {'pending_queue', 'queued'}:
                raise HTTPException(409, 'This action has already started or finished; cancellation cannot undo it.')
            tx.update(ref, {'status': 'cancelled'})
        cancel(self.auth.db.transaction())
        return {'status': 'ok', 'cancelled': action_id}

    def execute(self, owner, action_id):
        from .runtime_power import RuntimePower
        RuntimePower().require_enabled()
        ref = self.ref(owner, action_id)
        @documents.transactional
        def claim(tx):
            record = ref.get(transaction=tx).to_dict()
            if not record or record['status'] in {'cancelled', 'complete', 'failed', 'running'}:
                return None
            if datetime.fromisoformat(record['execute_at']) > datetime.now(timezone.utc):
                return record
            # A repeated callback reconciles only through the executor's durable receipt.
            tx.update(ref, {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat()})
            return record
        record = claim(self.auth.db.transaction())
        if not record:
            return {'status': 'ignored'}
        if datetime.fromisoformat(record['execute_at']) > datetime.now(timezone.utc):
            if datetime.fromisoformat(record['execute_at']) - datetime.now(timezone.utc) < timedelta(days=1):
                # An early final callback must retry this task, rather than trying
                # to recreate its currently executing deterministic task name.
                raise HTTPException(503, 'This scheduled action is not due yet.')
            self.enqueue(owner, record)
            return {'status': 'rescheduled'}
        executor = self.executor_factory(owner)
        try:
            connection = self.auth.status(owner)
            if not connection['connected'] or connection.get('email', '').lower() != record.get('account_email'):
                raise ValueError('The scheduled Google account is disconnected or changed. No action was executed.')
            result = executor.dispatch(record['action'], 'schedule:' + action_id)
            if result.get('status') != 'ok':
                raise ValueError(result.get('message', 'The scheduled action did not complete.'))
            ref.update({'status': 'complete', 'result': result, 'notification_pending': True, 'finished_at': datetime.now(timezone.utc).isoformat()})
            self.notify(owner, action_id)
            return {'status': 'complete'}
        except Exception as exc:
            # Never blindly replay an external write after uncertain delivery.
            message = str(getattr(exc, 'detail', exc))[:1000]
            ref.update({'status': 'failed', 'error': message, 'notification_pending': True, 'finished_at': datetime.now(timezone.utc).isoformat()})
            self.notify(owner, action_id)
            return {'status': 'failed'}
        finally:
            if hasattr(executor, 'client'):
                executor.client.close()

    def notify(self, owner, action_id):
        try:
            from .push_notifications import PushNotifications
            from .record_store import RecordStore
            record = self.ref(owner, action_id).get().to_dict()
            text = f"{record['title']}: " + ('completed.' if record['status'] == 'complete' else record.get('error', 'could not complete.'))
            result = record.get('result', {})
            if record['status'] == 'complete':
                if result.get('answer'):
                    text += '\n\n' + result['answer']
                elif result.get('event', {}).get('htmlLink'):
                    text += '\n' + result['event']['htmlLink']
                elif result.get('files'):
                    text += '\n\n' + '\n'.join(f.get('name', 'Drive file') for f in result['files'][:20])
            uid, thread = 'jarvis_local_user', record.get('thread_id') or 'cloud_actions'
            fs = RecordStore()
            if thread == 'cloud_actions':
                fs.save_chat_session(thread, {'uid': uid, 'title': 'Cloud actions', 'updated_at': datetime.now(timezone.utc).isoformat()})
            fs.save_chat_message(uid, thread, {'id': 'scheduled_' + action_id, 'role': 'assistant',
                'content': text, 'timestamp': datetime.now(timezone.utc).isoformat()})
            PushNotifications().queue_chat(uid, 'scheduled_' + action_id, thread, {'status': 'ok', 'message': text})
            self.ref(owner, action_id).update({'notification_pending': False})
        except Exception:
            logger.info('Scheduled Google result notification remains pending')

    def reconcile(self):
        # Called by an authenticated periodic task. Failed enqueue attempts retain
        # their durable record rather than being acknowledged as queued.
        count = 0
        owner = os.getenv('JARVIS_GOOGLE_OWNER_HASH')
        if not owner:
            return {'queued': 0, 'paired': False}
        collection = self.auth.ref(owner).collection('scheduled_actions')
        for snapshot in collection.where(filter=FieldFilter('status', '==', 'pending_queue')).limit(30).stream():
            record = snapshot.to_dict()
            try:
                self.enqueue(record['owner'], record)
                count += 1
            except Exception:
                continue
        for snapshot in collection.where(filter=FieldFilter('notification_pending', '==', True)).limit(30).stream():
            record = snapshot.to_dict()
            self.notify(record['owner'], record['id'])
        for snapshot in collection.where(filter=FieldFilter('status', '==', 'running')).limit(30).stream():
            record = snapshot.to_dict()
            if datetime.fromisoformat(record['started_at']) < datetime.now(timezone.utc) - timedelta(minutes=15):
                self.ref(record['owner'], record['id']).update({'status': 'failed', 'notification_pending': True,
                    'error': 'Execution was interrupted. Check Google for an already completed change; an uncertain write was not repeated.'})
        return {'queued': count}
