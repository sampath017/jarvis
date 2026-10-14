"""Local notification outbox, read by the Android polling worker."""
import hashlib
import logging
from datetime import datetime, timezone
from src.services.sqlite_store import AlreadyExists
from .record_store import RecordStore

logger = logging.getLogger(__name__)

class PushNotifications:
    def __init__(self):
        self.fs = RecordStore()

    def wake_context(self, uid, request_id, expires_at):
        # Android provides current context with requests; no remote push wake.
        return 0

    def queue_chat(self, uid, request_id, thread_id, response):
        needs_input = response.get('needs_user_input', False)
        identifier = 'chat_' + hashlib.sha256(request_id.encode()).hexdigest()
        text = response.get('message') or response.get('error') or 'Your response is ready.'
        title = 'Jarvis needs your input' if needs_input else 'Jarvis has replied'
        record = {'id': identifier, 'uid': uid, 'title': title, 'body': text.encode('utf-8')[:2400].decode('utf-8', errors='ignore'),
            'kind': 'chat_question' if needs_input else 'chat_reply', 'thread_id': thread_id,
            'request_id': request_id, 'status': 'PENDING', 'created_at': datetime.now(timezone.utc).isoformat()}
        # Retried task delivery must not reset a delivered alert to pending.
        try:
            self.fs.sql.create('notifications', identifier, record, uid=uid)
        except AlreadyExists:
            pass

    def deliver(self, uid):
        # Android's existing worker fetches and acknowledges pending alerts.
        return None
