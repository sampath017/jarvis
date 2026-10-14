"""Atomic SQLite receipts for active commands; Android owns durable app records."""
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from ..backend.command_execution import MAX_COMMAND_SECONDS

RUN_LEASE_SECONDS = MAX_COMMAND_SECONDS + 180


def _time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value


class CommandRunStore:
    def __init__(self, db=None):
        from .mobile_runs import database
        self.db = db if db is not None else database()

    @staticmethod
    def key(request_id):
        return hashlib.sha256(request_id.encode()).hexdigest()

    def claim(self, uid, request, calendar_key=None):
        key = self.key(request.request_id)
        key_hash = hashlib.sha256(calendar_key.encode()).hexdigest() if calendar_key else None
        fingerprint = hashlib.sha256((json.dumps(request.model_dump(mode='json'), sort_keys=True) + str(key_hash)).encode()).hexdigest()
        now = datetime.now(timezone.utc)
        with self.db.atomic():
            existing = self.db.get('command_runs', key, uid=uid)
            active = self.db.get('command_control', 'active', uid=uid) or {}
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'This request ID belongs to a different message.')
                return False
            if _time(active.get('until', now)) > now:
                raise HTTPException(409, 'Jarvis is still processing another request. Wait for it to finish or stop it first.')
            self.db.put('command_runs', key, {
                'fingerprint': fingerprint, 'request_id': request.request_id,
                'thread_id': request.thread_id, 'status': 'queued', 'payload': request.model_dump(mode='json'),
                'cancel_requested': False, 'started_at': now, 'updated_at': now,
                'message': 'Request received', 'steps': [], 'sequence': 0, 'response': None,
                'expires_at': now + timedelta(days=7), 'calendar_key_hash': key_hash,
            }, uid=uid, merge=False)
            self.db.put('command_control', 'active', {
                'request_id': request.request_id, 'until': now + timedelta(seconds=RUN_LEASE_SECONDS),
            }, uid=uid, merge=False)
        from .mobile_runs import accept
        accept(uid, request.request_id)
        return True

    @staticmethod
    def authorize(data, key):
        expected = data.get('calendar_key_hash')
        if expected and (not key or not secrets.compare_digest(expected, hashlib.sha256(key.encode()).hexdigest())):
            raise HTTPException(403, 'This calendar request belongs to another device session.')

    def calendar_action(self, uid, request_id, action, check):
        action = {**action, 'action_id': secrets.token_hex(16), 'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=180)).isoformat()}
        key = self.key(request_id)
        self.db.put('command_runs', key, {'calendar_action': action, 'calendar_result': None}, uid=uid)
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
            self.db.put('command_runs', key, {'calendar_action': None}, uid=uid)

    def calendar_result(self, uid, request_id, action_id, result, key):
        with self.db.atomic():
            data = self.get(uid, request_id)
            self.authorize(data, key)
            if not data.get('calendar_key_hash'):
                raise HTTPException(403, 'No calendar device session')
            if data.get('calendar_result_id') == action_id:
                return
            if data.get('status') == 'complete' or data.get('cancel_requested') or (data.get('calendar_action') or {}).get('action_id') != action_id:
                raise HTTPException(409, 'This calendar proposal is no longer active.')
            if datetime.now(timezone.utc) > _time(data['calendar_action']['expires_at']):
                raise HTTPException(409, 'This approval proposal has expired.')
            self.db.put('command_runs', self.key(request_id), {'calendar_result': result, 'calendar_result_id': action_id}, uid=uid)

    def start_execution(self, uid, request_id):
        key = self.key(request_id)
        with self.db.atomic():
            data = self.db.get('command_runs', key, uid=uid)
            if not data or data['status'] == 'complete':
                return None
            age = (datetime.now(timezone.utc) - _time(data['started_at'])).total_seconds()
            if age > RUN_LEASE_SECONDS or (data['status'] == 'queued' and age > MAX_COMMAND_SECONDS):
                self.db.put('command_runs', key, {'status': 'complete', 'response': {
                    'status': 'error', 'error': 'Processing was interrupted or could not start in time. Check saved changes before sending a new request.'}}, uid=uid)
                active = self.db.get('command_control', 'active', uid=uid) or {}
                if active.get('request_id') == request_id:
                    self.db.delete('command_control', 'active', uid=uid)
                return None
            if data['status'] == 'running':
                if self.public(data)['status'] == 'complete':
                    return None
                raise HTTPException(503, 'This request already has an active worker')
            self.db.put('command_runs', key, {'status': 'running', 'updated_at': datetime.now(timezone.utc)}, uid=uid)
            return data['payload']

    def get(self, uid, request_id):
        data = self.db.get('command_runs', self.key(request_id), uid=uid)
        if not data:
            raise HTTPException(404, 'Request not found')
        return data

    def progress(self, uid, request_id, message):
        key = self.key(request_id)
        with self.db.atomic():
            data = self.db.get('command_runs', key, uid=uid)
            if not data or data['status'] not in ('queued', 'running') or data['message'] == message:
                return
            self.db.put('command_runs', key, {'message': message,
                'steps': (data.get('steps', []) + [data['message']])[-4:],
                'sequence': data['sequence'] + 1, 'updated_at': datetime.now(timezone.utc)}, uid=uid)

    def cancel(self, uid, request_id):
        self.get(uid, request_id)
        self.db.put('command_runs', self.key(request_id), {'cancel_requested': True}, uid=uid)

    def finish(self, uid, request_id, response):
        from . import mobile_runs
        changes = mobile_runs.changes(uid, request_id)
        if changes is not None:
            response = {**response, '_mobile_changes': changes}
        with self.db.atomic():
            active = self.db.get('command_control', 'active', uid=uid) or {}
            self.db.put('command_runs', self.key(request_id), {'status': 'complete', 'response': response,
                'updated_at': datetime.now(timezone.utc)}, uid=uid)
            if active.get('request_id') == request_id:
                self.db.delete('command_control', 'active', uid=uid)
        mobile_runs.finish(uid, request_id)

    @staticmethod
    def public(data):
        elapsed = max(0, int((datetime.now(timezone.utc) - _time(data['started_at'])).total_seconds()))
        response = data.get('response')
        if not response and elapsed > RUN_LEASE_SECONDS:
            response = {'status': 'error', 'error': 'Processing was interrupted. Check any saved changes before sending a new request.'}
        return {'request_id': data['request_id'], 'status': 'complete' if response else 'running',
            'message': 'Stopping after the current operation' if data.get('cancel_requested') and not response else data['message'],
            'steps': data.get('steps', []), 'elapsed_seconds': elapsed,
            'sequence': data.get('sequence', 0), 'response': response}
