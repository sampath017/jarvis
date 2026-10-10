"""Bounded backend-to-phone wake requests with an explicit observation receipt."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import time

from .push_notifications import PushNotifications
from .firestore_service import FirestoreService


def dispatch_device_action(uid, action, fallback, check):
    if action.get('operation') == 'location_read':
        try:
            result = DeviceContext().request_and_wait(uid, check=check)
        except Exception:
            result = {'status': 'unavailable'}
        check()
        if result.get('status') == 'ok':
            return result
    return fallback()


class DeviceContext:
    def __init__(self):
        self.fs = FirestoreService()

    def request(self, uid):
        now = datetime.now(timezone.utc)
        request_id = str(uuid4())
        record = {'request_id': request_id, 'status': 'PENDING', 'created_at': now.isoformat(),
                  'expires_at': (now + timedelta(minutes=2)).isoformat()}
        self.fs._user_collection(uid, 'context_requests').document(request_id).set(record)
        count = PushNotifications().wake_context(uid, request_id, record['expires_at'])
        if not count:
            record['status'] = 'UNAVAILABLE'
            self.fs._user_collection(uid, 'context_requests').document(request_id).update({'status': 'UNAVAILABLE'})
        return {**record, 'devices_notified': count}

    def status(self, uid, request_id):
        record = self.fs._user_collection(uid, 'context_requests').document(request_id).get()
        return record.to_dict() if record.exists else None

    def receive(self, uid, event):
        request_id = event.get('context_request_id')
        if not request_id:
            return
        ref = self.fs._user_collection(uid, 'context_requests').document(request_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return
        request = snapshot.to_dict()
        now = datetime.now(timezone.utc)
        if now > datetime.fromisoformat(request['expires_at']):
            return
        # Report a receipt even if GPS failed; never replace a missing fix with history.
        gps = event.get('location')
        if gps:
            observed = datetime.fromisoformat(str(gps.get('timestamp', '')).replace('Z', '+00:00'))
            if not 0 <= (now - observed).total_seconds() <= 120:
                gps = None
        ref.update({'status': 'COMPLETED', 'received_at': now.isoformat(), 'gps': gps,
                    'location_status': event.get('location_status'), 'event_id': event.get('event_id')})

    def request_and_wait(self, uid, timeout=25, check=lambda: None):
        request = self.request(uid)
        deadline = time.monotonic() + timeout
        while request['status'] == 'PENDING' and time.monotonic() < deadline:
            check()
            time.sleep(1)
            request = self.status(uid, request['request_id']) or request
        if request.get('gps'):
            return {'status': 'ok', 'gps': request['gps'], 'observed_at': request['gps']['timestamp']}
        return {'status': 'unavailable', 'message': 'The background phone request did not return a fresh location.',
                'request_id': request['request_id']}
