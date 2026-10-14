"""Private, bounded Drive storage for verified conversation archives."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import secrets
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .chat_archive_format import MAX_COMPRESSED

FOLDER_NAME = 'Jarvis/Chat Archives'
ROOT_FIELD = 'jarvis_root_folder_id'
CACHE_FIELD = 'jarvis_upload_cache_folder_id'
SAVED_FIELD = 'jarvis_saved_files_folder_id'
FOLDER_FIELD = 'chat_archive_folder_id'
FOLDER_MIME = 'application/vnd.google-apps.folder'
FILES_URL = 'https://www.googleapis.com/drive/v3/files'
METADATA_FIELDS = 'id,name,mimeType,trashed,ownedByMe,shared,parents,appProperties'


class DriveChatArchiveStore:
    """The caller owns auth and its HTTP client; OAuth is fetched lazily."""

    def __init__(self, auth, connection):
        self.auth = auth
        self.connection = connection
        self._token = None

    def status(self):
        status = self.auth.status(self.connection)
        if not status.get('connected'):
            raise HTTPException(409, 'Connect cloud Google access before archiving')
        return status.get('email', '')

    def _headers(self):
        if self._token is None:
            self._token = self.auth.token(self.connection)
        return {'Authorization': 'Bearer ' + self._token}

    def _request(self, method, url, **kwargs):
        try:
            return self.auth.client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'Google Drive is temporarily unavailable; cloud messages were kept') from exc

    @staticmethod
    def _data(response):
        if not 200 <= response.status_code < 300:
            raise HTTPException(503 if response.status_code >= 500 else 409,
                                'Google Drive could not confirm the archive; cloud messages were kept')
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, 'Google Drive returned invalid archive metadata') from exc
        if not isinstance(data, dict):
            raise HTTPException(503, 'Google Drive returned invalid archive metadata')
        return data

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
            raise HTTPException(422, 'Invalid Drive archive ID')
        return value

    @staticmethod
    def _private(metadata, *, folder=False):
        if metadata.get('ownedByMe') is not True or metadata.get('shared') is not False:
            raise HTTPException(409, 'The Jarvis archive location must be owned by you and private')
        if metadata.get('trashed') is not False:
            raise HTTPException(409, 'The Jarvis archive location is unavailable')
        if folder and metadata.get('mimeType') != FOLDER_MIME:
            raise HTTPException(409, 'The saved Jarvis archive location is not a folder')
        return DriveChatArchiveStore._id(metadata.get('id'))

    def _metadata(self, file_id):
        response = self._request('GET', FILES_URL + '/' + quote(self._id(file_id), safe=''),
                                 params={'fields': METADATA_FIELDS})
        return response

    def _place_folder(self, metadata, parent, name):
        folder_id = self._private(metadata, folder=True)
        parents = metadata.get('parents', [])
        changes = {}
        if metadata.get('name') != name:
            changes['name'] = name
        params = {'fields': METADATA_FIELDS}
        if parent not in parents:
            params['addParents'] = parent
        others = [value for value in parents if value != parent]
        if others:
            params['removeParents'] = ','.join(others)
        if changes or len(params) > 1:
            metadata = self._data(self._request('PATCH', FILES_URL + '/' + quote(folder_id, safe=''), params=params, json=changes))
            self._private(metadata, folder=True)
        return folder_id

    def _named_folder(self, field, name, parent, legacy_name=None):
        self.status()
        ref = self.auth.ref(self.connection)
        saved = (ref.get().to_dict() or {}).get(field)
        if isinstance(saved, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', saved):
            response = self._metadata(saved)
            if response.status_code != 404:
                metadata = self._data(response)
                if metadata.get('trashed') is not True:
                    return self._place_folder(metadata, parent, name)
        match = "('" + parent + "' in parents and name='" + name + "')"
        if legacy_name:
            match = '(' + match + " or ('root' in parents and name='" + legacy_name + "'))"
        query = "'me' in owners and trashed=false and mimeType='application/vnd.google-apps.folder' and " + match
        token = None
        while True:
            params = {'q': query, 'fields': 'nextPageToken,files(' + METADATA_FIELDS + ')', 'pageSize': 100, 'spaces': 'drive'}
            if token:
                params['pageToken'] = token
            data = self._data(self._request('GET', FILES_URL, params=params))
            for metadata in data.get('files', []):
                if (metadata.get('ownedByMe') is True and metadata.get('shared') is False
                        and metadata.get('trashed') is False and metadata.get('mimeType') == FOLDER_MIME):
                    folder_id = self._place_folder(metadata, parent, name)
                    ref.set({field: folder_id}, merge=True)
                    return folder_id
            token = data.get('nextPageToken')
            if not token:
                break
        metadata = self._data(self._request('POST', FILES_URL, params={'fields': METADATA_FIELDS},
            json={'name': name, 'mimeType': FOLDER_MIME, 'parents': [parent], 'appProperties': {'jarvisFolder': name}}))
        folder_id = self._private(metadata, folder=True)
        ref.set({field: folder_id}, merge=True)
        return folder_id

    def ensure_root(self):
        self.status()
        if not hasattr(self, '_my_drive_id'):
            self._my_drive_id = self._id(self._data(self._metadata('root'))['id'])
        return self._named_folder(ROOT_FIELD, 'Jarvis', self._my_drive_id)

    def ensure_folder(self):
        return self._named_folder(FOLDER_FIELD, 'Chat Archives', self.ensure_root(), 'Jarvis Chat Archives')

    def ensure_cache_folder(self):
        return self._named_folder(CACHE_FIELD, 'Upload Cache', self.ensure_root(), 'Jarvis Upload Cache')

    def ensure_saved_folder(self):
        return self._named_folder(SAVED_FIELD, 'Saved Files', self.ensure_root())

    def organize_managed_files(self):
        folders = {'Chat Archives': self.ensure_folder(), 'Upload Cache': self.ensure_cache_folder(), 'Saved Files': self.ensure_saved_folder()}
        moved, deferred, checked = 0, 0, 0
        # Only app-marked files are candidates. External documents selected for
        # reading keep their original user-chosen location.
        query = "'root' in parents and 'me' in owners and trashed=false and mimeType!='application/vnd.google-apps.folder' and "                 "(appProperties has { key='jarvisMemory' and value='true' } or appProperties has { key='jarvisChatArchive' and value='true' })"
        while checked < 200:
            data = self._data(self._request('GET', FILES_URL, params={'q': query, 'fields': 'nextPageToken,files(' + METADATA_FIELDS + ')', 'pageSize': 100}))
            files = data.get('files', [])
            if not files:
                break
            progress = 0
            for metadata in files[:200 - checked]:
                checked += 1
                if metadata.get('shared') is not False or metadata.get('ownedByMe') is not True:
                    deferred += 1
                    continue
                markers = metadata.get('appProperties') or {}
                if markers.get('jarvisChatArchive') == 'true' or (metadata.get('mimeType') == 'application/gzip' and str(metadata.get('name', '')).startswith('jarvis-chat-')):
                    target = folders['Chat Archives']
                elif markers.get('jarvisStorage') == 'cache':
                    target = folders['Upload Cache']
                else:
                    target = folders['Saved Files']
                file_id = self._id(metadata['id'])
                updated = self._data(self._request('PATCH', FILES_URL + '/' + quote(file_id, safe=''),
                    params={'addParents': target, 'removeParents': ','.join(metadata.get('parents', [])), 'fields': METADATA_FIELDS}, json={}))
                self._private(updated)
                moved += 1
                progress += 1
            if not progress:
                break
        return {'root_folder': self.ensure_root(), 'folders': folders, 'moved_files': moved, 'deferred_files': deferred, 'checked_files': checked}

    def allocate_file_id(self):
        data = self._data(self._request('GET', FILES_URL + '/generateIds',
                                       params={'count': 1, 'space': 'drive', 'type': 'files'}))
        ids = data.get('ids')
        if not isinstance(ids, list) or len(ids) != 1:
            raise HTTPException(503, 'Google Drive did not allocate an archive ID')
        return self._id(ids[0])

    def read(self, file_id):
        """Download without allowing a response to exceed the archive size bound."""
        raw = bytearray()
        try:
            with self.auth.client.stream('GET', FILES_URL + '/' + quote(self._id(file_id), safe=''),
                                         params={'alt': 'media'}, headers=self._headers()) as response:
                if response.status_code != 200:
                    raise HTTPException(503 if response.status_code >= 500 else 409,
                                        'The Drive backup could not be read; cloud messages were kept')
                size = response.headers.get('Content-Length')
                if size and size.isdigit() and int(size) > MAX_COMPRESSED:
                    raise HTTPException(413, 'Drive backup exceeds 8 MB')
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    if len(raw) + len(chunk) > MAX_COMPRESSED:
                        raise HTTPException(413, 'Drive backup exceeds 8 MB')
                    raw.extend(chunk)
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'Google Drive is temporarily unavailable; cloud messages were kept') from exc
        return bytes(raw)

    def upload(self, thread_id, raw, file_id):
        """Create at a preallocated ID and verify the downloaded bytes before use."""
        if not isinstance(raw, bytes) or not raw:
            raise HTTPException(422, 'An archive body is required')
        if len(raw) > MAX_COMPRESSED:
            raise HTTPException(413, 'Drive backup exceeds 8 MB')
        if not isinstance(thread_id, str) or not 1 <= len(thread_id) <= 256:
            raise HTTPException(422, 'Invalid conversation ID')
        file_id = self._id(file_id)
        email = self.status()
        folder_id = self.ensure_folder()
        digest = sha256(raw).hexdigest()
        safe_thread = re.sub(r'[^A-Za-z0-9_-]', '_', thread_id)[:80]
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        metadata = {
            'id': file_id,
            'name': f'jarvis-chat-{safe_thread}-{timestamp}.json.gz',
            'mimeType': 'application/gzip',
            'parents': [folder_id],
            'appProperties': {'jarvisChatArchive': 'true', 'jarvisArchiveSha256': digest,
                              'jarvisArchiveThread': sha256(thread_id.encode()).hexdigest()},
        }
        boundary = 'jarvis_archive_' + secrets.token_hex(24)
        delimiter = ('--' + boundary + '\r\n').encode()
        body = (delimiter + b'Content-Type: application/json; charset=UTF-8\r\n\r\n'
                + json.dumps(metadata, separators=(',', ':')).encode() + b'\r\n'
                + delimiter + b'Content-Type: application/gzip\r\n\r\n' + raw
                + ('\r\n--' + boundary + '--\r\n').encode())
        headers = {**self._headers(), 'Content-Type': 'multipart/related; boundary=' + boundary}
        try:
            response = self.auth.client.post('https://www.googleapis.com/upload/drive/v3/files',
                                             params={'uploadType': 'multipart', 'fields': 'id'},
                                             content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'Google Drive upload could not be confirmed; cloud messages were kept') from exc
        if response.status_code != 409:
            result = self._data(response)
            if result.get('id') != file_id:
                raise HTTPException(409, 'Google Drive returned a different archive ID; cloud messages were kept')
        # Includes a retry after an upload succeeded but the worker lost its response.
        # Ownership/privacy are checked again because Drive sharing can change.
        self._private(self._data(self._metadata(file_id)))
        if sha256(self.read(file_id)).hexdigest() != digest:
            raise HTTPException(409, 'Drive backup verification failed; cloud messages were kept')
        return {'file_id': file_id, 'sha256': digest, 'email': email, 'folder_name': FOLDER_NAME}
