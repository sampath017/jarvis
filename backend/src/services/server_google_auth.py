"""Capability-bound offline Google grants. Tokens never enter agent state or sync."""
import base64
import hashlib
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from src.services import sqlite_documents as documents

from .record_store import RecordStore

SCOPES = ['openid', 'email', 'https://www.googleapis.com/auth/calendar.events',
          'https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/drive.readonly', 'https://www.googleapis.com/auth/drive.file',
          'https://www.googleapis.com/auth/forms.responses.readonly']
_access_tokens = {}
_token_lock = threading.Lock()


def capability_owner(key):
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        raise HTTPException(403, 'A private Jarvis connection is required.')
    owner = hashlib.sha256(key.encode()).hexdigest()
    expected = os.getenv('JARVIS_GOOGLE_OWNER_HASH')
    if expected and not secrets.compare_digest(owner, expected):
        raise HTTPException(403, 'This phone is not paired with cloud Google access.')
    return owner


def configured():
    return all(os.getenv(k) for k in ('JARVIS_GOOGLE_CLIENT_ID', 'JARVIS_GOOGLE_CLIENT_SECRET',
                                     'JARVIS_GOOGLE_TOKEN_KEY', 'JARVIS_SERVICE_URL', 'JARVIS_GOOGLE_ALLOWED_EMAIL',
                                     'JARVIS_GOOGLE_OWNER_HASH'))


class ServerGoogleAuth:
    def __init__(self, db=None, client=None):
        self.db = db if db is not None else RecordStore()._db
        self.client = client or httpx.Client(timeout=25, follow_redirects=False)

    def ref(self, owner):
        if self.db is None:
            raise HTTPException(503, 'Cloud authorization storage is unavailable.')
        if not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise HTTPException(403, 'Invalid cloud connection.')
        expected = os.getenv('JARVIS_GOOGLE_OWNER_HASH')
        if expected and not secrets.compare_digest(owner, expected):
            raise HTTPException(403, 'This connection is not paired with cloud Google access.')
        return self.db.collection('google_connections').document(owner)

    def cipher(self):
        if not configured():
            raise HTTPException(503, 'Cloud Google access needs server OAuth configuration first.')
        try:
            return Fernet(os.environ['JARVIS_GOOGLE_TOKEN_KEY'].encode())
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, 'Cloud Google token encryption is not configured.') from exc

    def status(self, owner):
        if not configured():
            ready_to_pair = all(os.getenv(k) for k in ('JARVIS_GOOGLE_CLIENT_ID', 'JARVIS_GOOGLE_CLIENT_SECRET', 'JARVIS_GOOGLE_TOKEN_KEY'))
            return {'configured': False, 'connected': False, 'setup_identifier': owner,
                    'message': 'Copy your cloud setup identifier to finish pairing.' if ready_to_pair else 'Server Google OAuth setup is required before connecting.'}
        data = self.ref(owner).get().to_dict() or {}
        usable = self.usable(data)
        return {'configured': True, 'connected': usable,
                'email': data.get('email', ''), 'needs_reconnect': bool(data.get('encrypted_refresh_token')) and not usable}

    @staticmethod
    def usable(data):
        return (data.get('status') == 'connected' and
                data.get('email', '').lower() == os.getenv('JARVIS_GOOGLE_ALLOWED_EMAIL', '').lower() and
                (set(SCOPES) - {'openid', 'email'}).issubset(set(data.get('scopes', '').split())))

    def start(self, owner, file_owner=None):
        self.ref(owner)
        self.cipher()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        self.db.collection('google_oauth_states').document(hashlib.sha256(state.encode()).hexdigest()).set({
            'owner': owner, 'file_owner': file_owner, 'verifier': verifier, 'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10)})
        params = {'client_id': os.environ['JARVIS_GOOGLE_CLIENT_ID'], 'redirect_uri': self.redirect_uri,
                  'response_type': 'code', 'scope': ' '.join(SCOPES), 'access_type': 'offline',
                  'prompt': 'consent', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
                  'login_hint': os.environ['JARVIS_GOOGLE_ALLOWED_EMAIL']}
        return {'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)}

    @property
    def redirect_uri(self):
        return os.environ['JARVIS_SERVICE_URL'].rstrip('/') + '/google-server/callback'

    def complete(self, state, code):
        self.cipher()
        ref = self.db.collection('google_oauth_states').document(hashlib.sha256(state.encode()).hexdigest())
        @documents.transactional
        def consume(tx):
            data = ref.get(transaction=tx).to_dict() or {}
            if not data or data['expires_at'] <= datetime.now(timezone.utc):
                raise HTTPException(400, 'This Google connection link expired. Connect again in Jarvis.')
            tx.delete(ref)
            return data
        data = consume(self.db.transaction())
        response = self.client.post('https://oauth2.googleapis.com/token', data={
            'grant_type': 'authorization_code', 'code': code, 'code_verifier': data['verifier'],
            'client_id': os.environ['JARVIS_GOOGLE_CLIENT_ID'],
            'client_secret': os.environ['JARVIS_GOOGLE_CLIENT_SECRET'], 'redirect_uri': self.redirect_uri})
        if response.status_code != 200:
            raise HTTPException(400, 'Google authorization did not complete. Connect again in Jarvis.')
        grant = response.json()
        identity = self.client.get('https://openidconnect.googleapis.com/v1/userinfo',
                                   headers={'Authorization': 'Bearer ' + grant['access_token']})
        user = identity.json() if identity.status_code == 200 else {}
        if (user.get('email_verified') is not True or
                user.get('email', '').lower() != os.environ['JARVIS_GOOGLE_ALLOWED_EMAIL'].lower()):
            raise HTTPException(403, 'Connect the Google account configured for this personal Jarvis.')
        required = set(SCOPES) - {'openid', 'email'}
        if not grant.get('refresh_token') or not required.issubset(set(grant.get('scope', '').split())):
            raise HTTPException(400, 'Offline Calendar and Drive permissions are required. Connect again and grant them.')
        encrypted = self.cipher().encrypt(grant['refresh_token'].encode()).decode()
        self.ref(data['owner']).set({'status': 'connected', 'email': user['email'], 'encrypted_refresh_token': encrypted,
                                     'scopes': grant['scope'], 'file_owner': data.get('file_owner'), 'updated_at': datetime.now(timezone.utc)})

    def token(self, owner):
        cipher = self.cipher()
        data = self.ref(owner).get().to_dict() or {}
        if not self.usable(data):
            raise HTTPException(409, 'Connect cloud Google access in Jarvis Settings before using unattended actions.')
        fingerprint = hashlib.sha256((data['encrypted_refresh_token'] + os.environ['JARVIS_GOOGLE_CLIENT_ID'] + os.environ['JARVIS_GOOGLE_TOKEN_KEY']).encode()).hexdigest()
        with _token_lock:
            cached = _access_tokens.get(owner)
            if cached and cached[0] == fingerprint and cached[2] > time.monotonic():
                return cached[1]
            refresh = cipher.decrypt(data['encrypted_refresh_token'].encode()).decode()
            response = self.client.post('https://oauth2.googleapis.com/token', data={
                'grant_type': 'refresh_token', 'refresh_token': refresh,
                'client_id': os.environ['JARVIS_GOOGLE_CLIENT_ID'], 'client_secret': os.environ['JARVIS_GOOGLE_CLIENT_SECRET']})
            if response.status_code == 400:
                self.ref(owner).update({'status': 'reconnect_required'})
                _access_tokens.pop(owner, None)
                raise HTTPException(409, 'Google authorization needs reconnection. No action was executed.')
            if response.status_code != 200:
                raise HTTPException(503, 'Google authorization is temporarily unavailable.')
            token = response.json()
            _access_tokens[owner] = (fingerprint, token['access_token'], time.monotonic() + max(0, int(token.get('expires_in', 300)) - 60))
            return token['access_token']

    def disconnect(self, owner):
        data = self.ref(owner).get().to_dict() or {}
        # Disable the grant first, even if Google's revocation service is unreachable.
        self.ref(owner).set({'status': 'disconnected', 'updated_at': datetime.now(timezone.utc)})
        with _token_lock:
            _access_tokens.pop(owner, None)
        if data.get('encrypted_refresh_token'):
            refresh = self.cipher().decrypt(data['encrypted_refresh_token'].encode()).decode()
            try:
                self.client.post('https://oauth2.googleapis.com/revoke', data={'token': refresh})
            except httpx.HTTPError:
                pass
        return {'connected': False}
