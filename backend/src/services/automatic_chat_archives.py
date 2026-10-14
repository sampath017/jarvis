"""Daily, bounded archiving of inactive chats using paired cloud Google access."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import gzip
import json
import time
import uuid

from fastapi import HTTPException
from src.services import sqlite_documents as documents
from src.services.sqlite_documents import FieldFilter

from .chat_archive_drive import DriveChatArchiveStore, FOLDER_NAME
from .chat_archive_format import Archive, MAX_EXPANDED, MAX_COMPRESSED, verify
from .chat_archive_policy import INACTIVE_DAYS, timestamp, last_activity, inactive, activity_fingerprint
from .chat_archive_retirement import retire
from .runtime_power import RuntimePower
from .server_google_auth import ServerGoogleAuth


class AutomaticChatArchives:
    def __init__(self, db, *, now=None, power=None):
        self.db = db
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.power = power or RuntimePower()

    def user_ref(self, uid, name, record):
        return self.db.collection('users').document(uid).collection(name).document(record)

    def policy_ref(self, uid):
        return self.user_ref(uid, 'chat_archive_policy', 'settings')

    def policy(self, uid):
        saved = self.policy_ref(uid).get().to_dict() or {}
        return {'enabled': saved.get('enabled', True), 'inactive_days': INACTIVE_DAYS,
                'folder_name': FOLDER_NAME, 'last_run_at': saved.get('last_run_at'),
                'last_result': saved.get('last_result')}

    def set_enabled(self, uid, enabled):
        self.policy_ref(uid).set({'enabled': enabled, 'updated_at': self.now()}, merge=True)
        return self.policy(uid)

    def touch(self, uid, thread_id):
        ref = self.db.collection('chat_sessions').document(thread_id)
        now = self.now()

        @documents.transactional
        def commit(tx):
            current = ref.get(transaction=tx).to_dict() or {}
            if current.get('uid') != uid:
                raise HTTPException(404, 'Conversation not found')
            previous = timestamp(current.get('last_used_at'))
            if previous and previous > now - timedelta(hours=1):
                return
            tx.set(ref, {**current, 'last_used_at': now,
                         'archive_activity_at': max(last_activity(current) or now, now)})

        commit(self.db.transaction())
        return {'tracked': True}

    def active_thread(self, uid, tx=None):
        control = self.user_ref(uid, 'command_control', 'active').get(transaction=tx).to_dict() or {}
        request_id = control.get('request_id')
        if not request_id:
            return None
        until = timestamp(control.get('until'))
        if until and until <= self.now():
            return None
        if not until:
            return '*'  # An uncertain lease is never a reason to archive.
        run = self.user_ref(uid, 'command_runs', sha256(request_id.encode()).hexdigest()).get(transaction=tx).to_dict() or {}
        if run.get('status') == 'complete':
            return None
        return run.get('thread_id') or (run.get('payload') or {}).get('thread_id') or '*'

    def previous_archive(self, current, thread_id, connection, drive):
        if not current.get('archive_drive_id'):
            return None
        if current.get('archive_connection') != connection:
            raise HTTPException(403, 'Use the Google connection that owns this archive')
        raw = drive.read(current['archive_drive_id'])
        if sha256(raw).hexdigest() != current.get('archive_sha256'):
            raise HTTPException(409, 'The previous Drive backup changed; cloud messages were kept')
        try:
            archive = verify(raw)
        except (ValueError, OSError, EOFError) as exc:
            raise HTTPException(409, 'The previous Drive backup could not be verified') from exc
        ids = [message.id for message in archive.session.messages]
        if archive.session.id != thread_id or len(ids) != len(set(ids)):
            raise HTTPException(409, 'The previous Drive backup is incomplete')
        return archive

    def _guard(self, uid, thread_id, initial, digest, *, automatic, cutoff=None):
        fingerprint = activity_fingerprint(initial)

        def guard(tx, current):
            self.power.require_enabled()
            if self.active_thread(uid, tx) in ('*', thread_id):
                raise HTTPException(409, 'This conversation has an ongoing command; try again when it finishes')
            if current.get('archive_sha256') not in (initial.get('archive_sha256'), digest):
                raise HTTPException(409, 'Another backup replaced this conversation; retry from its latest archive')
            if automatic:
                policy = self.policy_ref(uid).get(transaction=tx).to_dict() or {}
                if not policy.get('enabled', True):
                    raise HTTPException(409, 'Automatic archiving was disabled')
                if activity_fingerprint(current) != fingerprint or not inactive(current, cutoff):
                    raise HTTPException(409, 'The conversation was recently used; automatic archiving was stopped')
        return guard

    def archive_bytes(self, uid, thread_id, connection, raw, drive, *, automatic=False, cutoff=None, initial=None, previous=None):
        self.power.require_enabled()
        current = initial or self.db.collection('chat_sessions').document(thread_id).get().to_dict() or {}
        if current.get('uid') != uid:
            raise HTTPException(404, 'Conversation not found')
        try:
            archive = verify(raw)
        except (ValueError, OSError, EOFError) as exc:
            raise HTTPException(422, 'Invalid backup; cloud messages were kept') from exc
        ids = [message.id for message in archive.session.messages]
        if archive.session.id != thread_id or len(ids) != len(set(ids)):
            raise HTTPException(422, 'Backup contains duplicate IDs or a different conversation')
        digest = sha256(raw).hexdigest()
        guard = self._guard(uid, thread_id, current, digest, automatic=automatic, cutoff=cutoff)
        guard(None, current)  # Avoid uploading when the chat is already in use.
        previous = previous or self.previous_archive(current, thread_id, connection, drive)
        if previous and not {message.id for message in previous.session.messages}.issubset(ids):
            raise HTTPException(409, 'The backup is missing older archived messages; restore them and retry')
        key = sha256((connection + ':' + thread_id + ':' + digest).encode()).hexdigest()
        attempt_ref = self.user_ref(uid, 'chat_archive_uploads', key)
        attempt = attempt_ref.get().to_dict() or {}
        file_id = attempt.get('file_id') or drive.allocate_file_id()
        attempt_ref.set({'file_id': file_id, 'thread_id': thread_id, 'sha256': digest, 'updated_at': self.now()}, merge=True)
        uploaded = drive.upload(thread_id, raw, file_id)
        self.power.require_enabled()
        result = retire(self.db, uid, thread_id, archive, file_id, digest, connection, uploaded['email'],
                        guard=guard,
                        reason='automatic' if automatic else 'manual')
        # Keep the receipt small for safe retries; the Drive object is immutable.
        attempt_ref.set({'completed': True, 'updated_at': self.now()}, merge=True)
        return {**result, 'folder_name': FOLDER_NAME}

    def _backfill(self, uid, state):
        """One bounded metadata migration; subsequent saves maintain the index."""
        if state.get('migration_complete'):
            return
        query = self.db.collection('chat_sessions').where(filter=FieldFilter('uid', '==', uid)).order_by('__name__')
        if state.get('migration_after'):
            query = query.start_after({'__name__': self.db.collection('chat_sessions').document(state['migration_after'])})
        rows = list(query.limit(201).stream())
        for row in rows[:200]:
            ref = row.reference

            @documents.transactional
            def migrate(tx):
                current = ref.get(transaction=tx).to_dict() or {}
                if current.get('uid') != uid or ('archive_activity_at' in current and 'archive_pending' in current):
                    return
                activity = last_activity(current)
                if activity is None:
                    return
                tx.set(ref, {**current, 'archive_activity_at': activity,
                             'archive_pending': current.get('archive_pending', True)})
            migrate(self.db.transaction())
        state['migration_complete'] = len(rows) <= 200
        if rows:
            state['migration_after'] = rows[min(len(rows), 200) - 1].id

    def _automatic_one(self, uid, thread_id, current, connection, drive, cutoff):
        if not inactive(current, cutoff) or self.active_thread(uid) in ('*', thread_id):
            return False
        rows = list(self.db.collection('chat_messages').where(filter=FieldFilter('thread_id', '==', thread_id)).limit(20001).stream())
        if not rows:
            # Fully archived chats should not repeatedly occupy the candidate page.
            ref = self.db.collection('chat_sessions').document(thread_id)
            @documents.transactional
            def clear(tx):
                latest = ref.get(transaction=tx).to_dict() or {}
                messages = list(self.db.collection('chat_messages').where(filter=FieldFilter('thread_id', '==', thread_id)).limit(1).stream(transaction=tx))
                if not messages and latest.get('uid') == uid:
                    tx.set(ref, {**latest, 'archive_pending': False})
            clear(self.db.transaction())
            return False
        if len(rows) > 20000:
            raise HTTPException(413, 'Conversation exceeds the archive message limit')
        previous = self.previous_archive(current, thread_id, connection, drive)
        messages = {m.id: m.model_dump(mode='json') for m in previous.session.messages} if previous else {}
        for row in rows:
            value = row.to_dict() or {}
            observed = timestamp(value.get('timestamp'))
            if value.get('uid') != uid or observed is None:
                raise HTTPException(409, 'Conversation ownership or timestamps could not be verified')
            if observed > cutoff:
                # Also protect legacy sessions whose last-message stamp is newer
                # than their old session metadata. No body is retired in this run.
                self.touch(uid, thread_id)
                return False
            executed = value.get('executed_records') or []
            if isinstance(executed, str):
                executed = json.loads(executed)
            messages[row.id] = {'id': row.id, 'text': value.get('content', ''),
                                'is_user': value.get('role', 'user') == 'user', 'timestamp': observed,
                                'run_id': value.get('run_id'), 'executed_records': executed,
                                'duration_ms': value.get('duration_ms')}
        if len(messages) > 20000:
            raise HTTPException(413, 'Conversation exceeds the archive message limit')
        ordered = sorted(messages.values(), key=lambda m: (timestamp(m['timestamp']), not m['is_user'], m['id']))
        earliest = min(timestamp(m['timestamp']) for m in ordered)
        archive = Archive.model_validate({'kind': 'jarvis_chat_backup', 'version': 1, 'session': {
            'id': thread_id, 'title': current.get('title') or 'Saved chat',
            'created_at': timestamp(current.get('created_at')) or (previous.session.created_at if previous else earliest),
            'updated_at': last_activity(current), 'messages': ordered}})
        expanded = archive.model_dump_json().encode()
        if len(expanded) > MAX_EXPANDED:
            raise HTTPException(413, 'Conversation exceeds the expanded archive limit')
        raw = gzip.compress(expanded, mtime=0)
        if len(raw) > MAX_COMPRESSED:
            raise HTTPException(413, 'Conversation exceeds the compressed archive limit')
        self.archive_bytes(uid, thread_id, connection, raw, drive, automatic=True, cutoff=cutoff, initial=current, previous=previous)
        return True

    def run_daily(self, uid, connection, *, drive=None):
        self.power.require_enabled()
        if not self.policy(uid)['enabled']:
            return {'status': 'disabled', 'archived': 0}
        if not connection:
            return {'status': 'not_connected', 'archived': 0}
        control = self.user_ref(uid, 'chat_archive_control', 'daily')
        now, operation = self.now(), uuid.uuid4().hex
        day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date().isoformat()

        @documents.transactional
        def claim(tx):
            previous = control.get(transaction=tx).to_dict() or {}
            if previous.get('completed_day') == day:
                return None
            if (timestamp(previous.get('lease_until')) or now) > now:
                return None
            state = {**previous, 'operation': operation, 'lease_until': now + timedelta(minutes=14)}
            tx.set(control, state)
            return state

        state = claim(self.db.transaction())
        if state is None:
            return {'status': 'already_checked', 'archived': 0}
        auth = None
        deadline = time.monotonic() + 12 * 60
        try:
            if drive is None:
                auth = ServerGoogleAuth(db=self.db)
                drive = DriveChatArchiveStore(auth, connection)
            try:
                drive.status()
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                result = {'status': 'not_connected', 'archived': 0}
                state.update(completed_day=day, last_result=result)
                self.policy_ref(uid).set({'last_run_at': self.now(), 'last_result': result}, merge=True)
                return result
            drive.ensure_folder()
            self._backfill(uid, state)
            cutoff = now - timedelta(days=INACTIVE_DAYS)
            query = (self.db.collection('chat_sessions').where(filter=FieldFilter('uid', '==', uid))
                     .where(filter=FieldFilter('archive_pending', '==', True))
                     .where(filter=FieldFilter('archive_activity_at', '<=', cutoff))
                     .order_by('archive_activity_at'))
            if state.get('candidate_after_id') and state.get('candidate_after_at'):
                query = query.start_after({'archive_activity_at': state['candidate_after_at'],
                                          '__name__': self.db.collection('chat_sessions').document(state['candidate_after_id'])})
            rows = list(query.limit(21).stream())
            result = {'status': 'checked', 'archived': 0, 'examined': 0, 'deferred': 0, 'errors': 0}
            for row in rows[:20]:
                if time.monotonic() >= deadline:
                    result['status'] = 'partial'
                    break
                self.power.require_enabled()
                result['examined'] += 1
                try:
                    if self._automatic_one(uid, row.id, row.to_dict(), connection, drive, cutoff):
                        result['archived'] += 1
                    else:
                        result['deferred'] += 1
                except (HTTPException, ValueError, OSError):
                    result['errors'] += 1  # Retry on the next daily run; preserve bodies.
                state['candidate_after_id'] = row.id
                state['candidate_after_at'] = row.to_dict()['archive_activity_at']
            if len(rows) <= 20 and result['status'] != 'partial':
                state.update(candidate_after_id=None, candidate_after_at=None)
            state.update(completed_day=day, lease_until=self.now(), last_result=result)
            self.policy_ref(uid).set({'last_run_at': self.now(), 'last_result': result}, merge=True)
            return result
        finally:
            # Do not erase a disabled policy or a newer worker's lease.
            @documents.transactional
            def release(tx):
                saved = control.get(transaction=tx).to_dict() or {}
                if saved.get('operation') == operation:
                    tx.set(control, {**state, 'lease_until': self.now()})
            release(self.db.transaction())
            if auth:
                auth.client.close()
