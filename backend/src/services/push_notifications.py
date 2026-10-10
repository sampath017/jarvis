"""FCM data notifications, delivered through the existing durable alert outbox."""
import hashlib
import logging
from datetime import datetime, timezone
from google.api_core.exceptions import AlreadyExists
import google.auth
from google.auth.transport.requests import AuthorizedSession
from .firestore_service import FirestoreService

logger = logging.getLogger(__name__)

class PushNotifications:
    def __init__(self):
        self.fs = FirestoreService()

    def register(self, uid, token):
        key = hashlib.sha256(token.encode()).hexdigest()
        self.fs._user_collection(uid, 'devices').document(key).set({'token': token, 'updated_at': datetime.now(timezone.utc).isoformat()})

    def wake_context(self, uid, request_id, expires_at):
        devices = list(self.fs._user_collection(uid, 'devices').stream())
        if not devices:
            return 0
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/firebase.messaging'])
        delivered = 0
        with AuthorizedSession(credentials) as session:
            for device in devices:
                token = (device.to_dict() or {}).get('token')
                if not token:
                    continue
                response = session.post('https://fcm.googleapis.com/v1/projects/jarvis-agent-61947/messages:send',
                    json={'message': {'token': token, 'data': {'kind': 'context_request', 'request_id': request_id,
                          'expires_at': expires_at}, 'android': {'priority': 'HIGH', 'ttl': '120s'}}}, timeout=15)
                if response.ok:
                    delivered += 1
                elif response.status_code == 404 and 'UNREGISTERED' in response.text:
                    device.reference.delete()
                else:
                    response.raise_for_status()
        return delivered

    def queue_chat(self, uid, request_id, thread_id, response):
        needs_input = response.get('needs_user_input', False)
        identifier = 'chat_' + hashlib.sha256(request_id.encode()).hexdigest()
        text = response.get('message') or response.get('error') or 'Your response is ready.'
        title = 'Jarvis needs your input' if needs_input else 'Jarvis has replied'
        record = {'id': identifier, 'uid': uid, 'title': title, 'body': text.encode('utf-8')[:2400].decode('utf-8', errors='ignore'),
            'kind': 'chat_question' if needs_input else 'chat_reply', 'thread_id': thread_id,
            'request_id': request_id, 'status': 'PENDING', 'created_at': datetime.now(timezone.utc).isoformat()}
        ref = self.fs._user_collection(uid, 'notifications').document(identifier)
        # Retried task delivery must not reset a delivered alert to pending.
        try:
            ref.create(record)
        except AlreadyExists:
            pass
        from .background_tasks import BackgroundTasks
        dispatcher = BackgroundTasks()
        if dispatcher.configured:
            dispatcher.enqueue('notification', {'uid': uid}, f'notification:{uid}:{identifier}')
        self.deliver(uid)

    def deliver(self, uid):
        if not self.fs.is_available: return
        devices = list(self.fs._user_collection(uid, 'devices').stream())
        if not devices: return
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/firebase.messaging'])
        with AuthorizedSession(credentials) as session:
            for record in self.fs.get_notifications(uid, 'PENDING'):
                # A successful FCM send waits for the phone's acknowledgement.
                # Allow a bounded resend after 5 minutes if it never arrived.
                sent = record.get('push_sent_at')
                if sent and (datetime.now(timezone.utc) - datetime.fromisoformat(sent)).total_seconds() < 300:
                    continue
                delivered = False
                for device in devices:
                    token = (device.to_dict() or {}).get('token')
                    if not token: continue
                    data = {k: str(record.get(k) or '') for k in ['id', 'title', 'body', 'kind', 'thread_id', 'request_id']}
                    payload = record.get('payload') or {}
                    data.update({k: str(payload.get(k) or '') for k in ['delivery_mode', 'reminder_id', 'alarm_due_at', 'occurred_at']})
                    response = session.post('https://fcm.googleapis.com/v1/projects/jarvis-agent-61947/messages:send',
                        json={'message': {'token': token, 'data': data, 'android': {'priority': 'HIGH', 'ttl': '86400s'}}}, timeout=15)
                    if response.ok:
                        delivered = True
                    elif response.status_code == 404 and 'UNREGISTERED' in response.text:
                        device.reference.delete()
                    else:
                        response.raise_for_status()
                if delivered:
                    self.fs._user_collection(uid, 'notifications').document(record['id']).set(
                        {'push_sent_at': datetime.now(timezone.utc).isoformat()}, merge=True)
