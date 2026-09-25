"""Durable request IDs keep reconnects from repeating tool side effects."""
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from google.cloud import firestore
from .firestore_service import FirestoreService
from ..backend.command_execution import MAX_COMMAND_SECONDS

RUN_LEASE_SECONDS = MAX_COMMAND_SECONDS + 180

class CommandRunStore:
    def __init__(self):
        self.db = FirestoreService()._db
        if self.db is None:
            raise HTTPException(503, 'Cannot safely start a request while request storage is unavailable.')

    def ref(self, uid, request_id):
        key = hashlib.sha256(request_id.encode()).hexdigest()
        return self.db.collection('users').document(uid).collection('command_runs').document(key)

    def control(self, uid):
        return self.db.collection('users').document(uid).collection('command_control').document('active')

    def claim(self, uid, request, calendar_key=None):
        ref, control = self.ref(uid, request.request_id), self.control(uid)
        key_hash = hashlib.sha256(calendar_key.encode()).hexdigest() if calendar_key else None
        fingerprint = hashlib.sha256((json.dumps(request.model_dump(mode='json'), sort_keys=True) + str(key_hash)).encode()).hexdigest()
        now = datetime.now(timezone.utc)
        @firestore.transactional
        def claim(transaction):
            existing = ref.get(transaction=transaction).to_dict()
            active = control.get(transaction=transaction).to_dict() or {}
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'This request ID belongs to a different message.')
                return False
            if active.get('until', now) > now:
                raise HTTPException(409, 'Jarvis is still processing another request. Wait for it to finish or stop it first.')
            transaction.set(ref, {
                'fingerprint': fingerprint, 'request_id': request.request_id,
                'thread_id': request.thread_id, 'status': 'queued', 'payload': request.model_dump(mode='json'), 'cancel_requested': False,
                'started_at': now, 'updated_at': now, 'message': 'Request received',
                'steps': [], 'sequence': 0, 'response': None,
                'expires_at': now + timedelta(days=7),
                'calendar_key_hash': key_hash,
            })
            transaction.set(control, {'request_id': request.request_id, 'until': now + timedelta(seconds=RUN_LEASE_SECONDS)})
            return True
        return claim(self.db.transaction())

    @staticmethod
    def authorize(data, key):
        expected = data.get('calendar_key_hash')
        if expected and (not key or not secrets.compare_digest(expected, hashlib.sha256(key.encode()).hexdigest())):
            raise HTTPException(403, 'This calendar request belongs to another device session.')

    def calendar_action(self, uid, request_id, action, check):
        action = {**action, 'action_id': secrets.token_hex(16), 'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=180)).isoformat()}
        ref = self.ref(uid, request_id)
        ref.update({'calendar_action': action, 'calendar_result': None})
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                check()
                data = self.get(uid, request_id)
                if data.get('calendar_result') is not None:
                    return data['calendar_result']
                time.sleep(1)
            return {'status': 'not_executed', 'message': 'No approval or device response received in time. Keep Jarvis open and try again.'}
        finally:
            ref.update({'calendar_action': None})

    def calendar_result(self, uid, request_id, action_id, result, key):
        ref = self.ref(uid, request_id)
        @firestore.transactional
        def save(transaction):
            data = ref.get(transaction=transaction).to_dict() or {}
            self.authorize(data, key)
            if not data.get('calendar_key_hash'):
                raise HTTPException(403, 'No calendar device session')
            if data.get('calendar_result_id') == action_id:
                return  # A lost HTTP acknowledgement may be safely retried.
            if data.get('status') == 'complete' or data.get('cancel_requested') or (data.get('calendar_action') or {}).get('action_id') != action_id:
                raise HTTPException(409, 'This calendar proposal is no longer active.')
            if datetime.now(timezone.utc) > datetime.fromisoformat(data['calendar_action']['expires_at']):
                raise HTTPException(409, 'This approval proposal has expired.')
            transaction.update(ref, {'calendar_result': result, 'calendar_result_id': action_id})
        save(self.db.transaction())

    def start_execution(self, uid, request_id):
        ref = self.ref(uid, request_id)
        @firestore.transactional
        def start(transaction):
            data = ref.get(transaction=transaction).to_dict()
            if not data or data['status'] == 'complete': return None
            age = (datetime.now(timezone.utc) - data['started_at']).total_seconds()
            if age > RUN_LEASE_SECONDS or (data['status'] == 'queued' and age > MAX_COMMAND_SECONDS):
                active = self.control(uid).get(transaction=transaction).to_dict() or {}
                transaction.update(ref, {'status': 'complete', 'response': {
                    'status': 'error', 'error': 'Processing was interrupted or could not start in time. Check saved changes before sending a new request.'}})
                if active.get('request_id') == request_id: transaction.delete(self.control(uid))
                return None
            if data['status'] == 'running':
                # An uncertain worker retry must never repeat side effects.
                if self.public(data)['status'] == 'complete':
                    return None
                raise HTTPException(503, 'This request already has an active worker')
            transaction.update(ref, {'status': 'running', 'updated_at': datetime.now(timezone.utc)})
            return data['payload']
        return start(self.db.transaction())

    def get(self, uid, request_id):
        data = self.ref(uid, request_id).get().to_dict()
        if not data:
            raise HTTPException(404, 'Request not found')
        return data

    def progress(self, uid, request_id, message):
        ref = self.ref(uid, request_id)
        @firestore.transactional
        def update(transaction):
            data = ref.get(transaction=transaction).to_dict()
            if not data or data['status'] not in ('queued', 'running'): return
            previous = data['message']
            if previous == message: return
            steps = (data.get('steps', []) + [previous])[-4:]
            transaction.update(ref, {'message': message, 'steps': steps,
                'sequence': data['sequence'] + 1, 'updated_at': datetime.now(timezone.utc)})
        update(self.db.transaction())

    def cancel(self, uid, request_id):
        self.get(uid, request_id)
        self.ref(uid, request_id).update({'cancel_requested': True})

    def finish(self, uid, request_id, response):
        ref, control = self.ref(uid, request_id), self.control(uid)
        @firestore.transactional
        def finish(transaction):
            active = control.get(transaction=transaction).to_dict() or {}
            transaction.update(ref, {'status': 'complete', 'response': response,
                'updated_at': datetime.now(timezone.utc)})
            if active.get('request_id') == request_id:
                transaction.delete(control)
        finish(self.db.transaction())

    @staticmethod
    def public(data):
        elapsed = max(0, int((datetime.now(timezone.utc) - data['started_at']).total_seconds()))
        response = data.get('response')
        if not response and elapsed > RUN_LEASE_SECONDS:
            response = {'status': 'error', 'error': 'Processing was interrupted. Check any saved changes before sending a new request.'}
        return {'request_id': data['request_id'], 'status': 'complete' if response else 'running',
            'message': 'Stopping after the current operation' if data.get('cancel_requested') and not response else data['message'],
            'steps': data.get('steps', []), 'elapsed_seconds': elapsed,
            'sequence': data.get('sequence', 0), 'response': response}
