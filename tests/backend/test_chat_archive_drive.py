from email import policy
from email.parser import BytesParser
from hashlib import sha256
import json

import httpx
import pytest
from fastapi import HTTPException

from src.services.chat_archive_drive import DriveChatArchiveStore, FOLDER_FIELD, FOLDER_MIME, FOLDER_NAME, ROOT_FIELD
from src.services.chat_archive_format import MAX_COMPRESSED


def folder(file_id='folder', **patch):
    return {'id': file_id, 'name': 'Chat Archives', 'mimeType': FOLDER_MIME, 'ownedByMe': True, 'shared': False,
            'trashed': False, 'parents': ['jarvis-root'], **patch}


def archive_file(file_id='archive', **patch):
    return {'id': file_id, 'mimeType': 'application/gzip', 'ownedByMe': True,
            'shared': False, 'trashed': False, 'parents': ['folder'], **patch}


class Ref:
    def __init__(self, value):
        self.value = value
        self.writes = []

    def get(self):
        return self

    def to_dict(self):
        return dict(self.value)

    def set(self, value, merge=False):
        assert merge is True
        self.writes.append(value)
        self.value.update(value)


class Drive:
    def __init__(self):
        self.calls = []
        self.metadata = {'root': folder('root', name='My Drive', parents=[])}
        self.bodies = {}
        self.listed = []
        self.uploaded = []
        self.upload_status = 200
        self.download_override = None

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == '/drive/v3/files/generateIds':
            assert request.method == 'GET'
            assert dict(request.url.params) == {'count': '1', 'space': 'drive', 'type': 'files'}
            return httpx.Response(200, json={'ids': ['archive']})
        if path == '/drive/v3/files':
            if request.method == 'GET':
                assert "'me' in owners" in request.url.params['q']
                if "mimeType!='application/vnd.google-apps.folder'" in request.url.params['q']:
                    values = [metadata for metadata in self.metadata.values() if 'root' in metadata.get('parents', [])
                              and metadata.get('mimeType') != FOLDER_MIME and any(metadata.get('appProperties', {}).get(key) == 'true'
                                  for key in ('jarvisMemory', 'jarvisChatArchive'))]
                    return httpx.Response(200, json={'files': values})
                if "name='Jarvis'" in request.url.params['q']:
                    return httpx.Response(200, json={'files': []})
                return httpx.Response(200, json={'files': self.listed})
            metadata = json.loads(request.content)
            assert metadata['mimeType'] == FOLDER_MIME
            file_id = 'jarvis-root' if metadata['name'] == 'Jarvis' else 'folder'
            created = folder(file_id, **metadata)
            self.metadata[file_id] = created
            return httpx.Response(200, json=created)
        if path == '/upload/drive/v3/files':
            assert request.method == 'POST'
            assert request.url.params['uploadType'] == 'multipart'
            header = ('Content-Type: ' + request.headers['Content-Type']
                      + '\r\nMIME-Version: 1.0\r\n\r\n').encode()
            message = BytesParser(policy=policy.default).parsebytes(header + request.content)
            parts = list(message.iter_parts())
            assert len(parts) == 2
            assert parts[0].get_content_type() == 'application/json'
            assert parts[1].get_content_type() == 'application/gzip'
            metadata = json.loads(parts[0].get_payload(decode=True))
            raw = parts[1].get_payload(decode=True)
            self.uploaded.append((metadata, raw))
            if self.upload_status == 200:
                self.metadata[metadata['id']] = archive_file(metadata['id'])
                self.bodies[metadata['id']] = raw
            return httpx.Response(self.upload_status, json={'id': metadata['id']})
        file_id = path.rsplit('/', 1)[1]
        if request.method == 'PATCH' and file_id in self.metadata:
            metadata = self.metadata[file_id]
            metadata.update(json.loads(request.content))
            if request.url.params.get('addParents'):
                metadata['parents'] = [request.url.params['addParents']]
            return httpx.Response(200, json=metadata)
        if request.url.params.get('alt') == 'media':
            if file_id not in self.bodies:
                return httpx.Response(404)
            raw = self.download_override if self.download_override is not None else self.bodies[file_id]
            return httpx.Response(200, content=raw)
        metadata = self.metadata.get(file_id)
        return httpx.Response(200, json=metadata) if metadata else httpx.Response(404)


class Auth:
    def __init__(self, drive, saved=None, *, connected=True):
        self.client = httpx.Client(transport=httpx.MockTransport(drive))
        self.record = Ref({FOLDER_FIELD: saved} if saved else {})
        self.connected = connected
        self.token_calls = 0

    def status(self, connection):
        assert connection == 'connection'
        return {'connected': self.connected, 'email': 'owner@example.com'}

    def token(self, connection):
        assert connection == 'connection'
        self.token_calls += 1
        return 'test-access-token'

    def ref(self, connection):
        assert connection == 'connection'
        return self.record


@pytest.fixture
def store():
    drive = Drive()
    auth = Auth(drive)
    yield DriveChatArchiveStore(auth, 'connection'), drive, auth
    auth.client.close()


def test_status_does_not_request_oauth_and_disconnected_blocks_folder(store):
    storage, drive, auth = store
    assert storage.status() == 'owner@example.com'
    assert auth.token_calls == 0
    assert not drive.calls
    auth.connected = False
    with pytest.raises(HTTPException) as failure:
        storage.ensure_folder()
    assert failure.value.status_code == 409
    assert not drive.calls


def test_creates_private_folder_and_saves_reference_with_merge(store):
    storage, drive, auth = store
    assert storage.ensure_folder() == 'folder'
    assert auth.record.writes == [{ROOT_FIELD: 'jarvis-root'}, {FOLDER_FIELD: 'folder'}]
    assert storage.ensure_folder() == 'folder'
    assert len([call for call in drive.calls if call.method == 'POST']) == 2
    assert auth.token_calls == 1
    assert not auth.client.is_closed


def test_reuses_only_owned_private_matching_root_folder(store):
    storage, drive, auth = store
    drive.listed = [folder('shared', shared=True), folder('foreign', ownedByMe=False), folder('private')]
    drive.metadata['private'] = folder('private')
    assert storage.ensure_folder() == 'private'
    assert auth.record.value[FOLDER_FIELD] == 'private'
    assert len([call for call in drive.calls if call.method == 'POST']) == 1  # The parent Jarvis folder.


@pytest.mark.parametrize('saved,metadata', [
    ('deleted', None), ('trashed', folder('trashed', trashed=True)), ('invalid/path', None),
])
def test_missing_trashed_or_invalid_saved_folder_is_recreated(store, saved, metadata):
    storage, drive, auth = store
    auth.record.value[FOLDER_FIELD] = saved
    if metadata:
        drive.metadata[saved] = metadata
    assert storage.ensure_folder() == 'folder'
    assert auth.record.value[FOLDER_FIELD] == 'folder'


@pytest.mark.parametrize('metadata', [folder(shared=True), folder(ownedByMe=False), archive_file('folder')])
def test_saved_shared_foreign_or_nonfolder_location_blocks_upload(store, metadata):
    storage, drive, auth = store
    auth.record.value[FOLDER_FIELD] = 'folder'
    drive.metadata['folder'] = metadata
    with pytest.raises(HTTPException) as failure:
        storage.upload('chat', b'private compressed content', 'archive')
    assert failure.value.status_code == 409
    assert not drive.uploaded
    assert auth.record.writes == [{ROOT_FIELD: 'jarvis-root'}]


def test_upload_uses_generated_id_private_folder_markers_and_download_verification(store):
    storage, drive, auth = store
    raw = b'\x1f\x8b\x00example compressed archive\xff\x00'
    file_id = storage.allocate_file_id()
    result = storage.upload('thread/with spaces', raw, file_id)
    assert result == {'file_id': 'archive', 'sha256': sha256(raw).hexdigest(),
                      'email': 'owner@example.com', 'folder_name': FOLDER_NAME}
    metadata, sent = drive.uploaded[0]
    assert sent == raw
    assert metadata['parents'] == ['folder']
    assert metadata['id'] == file_id
    assert metadata['name'].startswith('jarvis-chat-thread_with_spaces-')
    assert metadata['name'].endswith('.json.gz')
    assert metadata['appProperties'] == {
        'jarvisChatArchive': 'true', 'jarvisArchiveSha256': sha256(raw).hexdigest(),
        'jarvisArchiveThread': sha256(b'thread/with spaces').hexdigest(),
    }
    assert any(call.url.params.get('alt') == 'media' for call in drive.calls)
    assert auth.token_calls == 1


def test_upload_tampering_fails_before_backup_can_be_used(store):
    storage, drive, _ = store
    drive.download_override = b'tampered'
    with pytest.raises(HTTPException) as failure:
        storage.upload('chat', b'original', 'archive')
    assert failure.value.status_code == 409


@pytest.mark.parametrize('same_bytes', [True, False])
def test_preallocated_id_conflict_is_reused_only_for_identical_bytes(store, same_bytes):
    storage, drive, _ = store
    drive.upload_status = 409
    drive.metadata['archive'] = archive_file()
    drive.bodies['archive'] = b'original' if same_bytes else b'different'
    if same_bytes:
        assert storage.upload('chat', b'original', 'archive')['sha256'] == sha256(b'original').hexdigest()
    else:
        with pytest.raises(HTTPException) as failure:
            storage.upload('chat', b'original', 'archive')
        assert failure.value.status_code == 409
    assert len(drive.uploaded) == 1


def test_shared_existing_archive_is_not_reused_even_when_bytes_match(store):
    storage, drive, _ = store
    drive.upload_status = 409
    drive.metadata['archive'] = archive_file(shared=True)
    drive.bodies['archive'] = b'original'
    with pytest.raises(HTTPException) as failure:
        storage.upload('chat', b'original', 'archive')
    assert failure.value.status_code == 409
    assert not any(call.url.params.get('alt') == 'media' for call in drive.calls)


def test_overlarge_upload_is_rejected_before_any_drive_request(store):
    storage, drive, auth = store
    with pytest.raises(HTTPException) as failure:
        storage.upload('chat', b'x' * (MAX_COMPRESSED + 1), 'archive')
    assert failure.value.status_code == 413
    assert not drive.calls
    assert auth.token_calls == 0


def test_download_bound_checks_declared_and_streamed_sizes(store):
    storage, drive, _ = store
    drive.bodies['archive'] = b'x' * (MAX_COMPRESSED + 1)
    with pytest.raises(HTTPException) as failure:
        storage.read('archive')
    assert failure.value.status_code == 413

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(MAX_COMPRESSED // 65536 + 1):
                yield b'x' * 65536

    def streamed(request):
        return httpx.Response(200, stream=Chunks())

    storage.auth.client.close()
    storage.auth.client = httpx.Client(transport=httpx.MockTransport(streamed))
    with pytest.raises(HTTPException) as failure:
        storage.read('archive')
    assert failure.value.status_code == 413


def test_drive_transport_failures_do_not_expose_credentials(store):
    storage, _, _ = store

    def offline(request):
        raise httpx.ConnectError('internal transport failure', request=request)

    storage.auth.client.close()
    storage.auth.client = httpx.Client(transport=httpx.MockTransport(offline))
    with pytest.raises(HTTPException) as failure:
        storage.read('archive')
    assert failure.value.status_code == 503
    assert 'test-access-token' not in failure.value.detail


def test_organization_preserves_folder_and_file_ids_and_ignores_external_documents(store):
    from src.services.chat_archive_drive import CACHE_FIELD, SAVED_FIELD
    storage, drive, auth = store
    auth.record.value.update({ROOT_FIELD: 'jarvis-root', FOLDER_FIELD: 'archives', CACHE_FIELD: 'cache', SAVED_FIELD: 'saved',
                              'encrypted_refresh_token': 'existing-grant'})
    drive.metadata.update({'jarvis-root': folder('jarvis-root', name='Jarvis', parents=['root']),
                           'archives': folder('archives', name='Jarvis Chat Archives', parents=['root']),
                           'cache': folder('cache', name='Jarvis Upload Cache', parents=['root']),
                           'saved': folder('saved', name='Saved Files')})
    drive.metadata['old-backup'] = archive_file('old-backup', name='jarvis-chat-123.json.gz', parents=['root'],
                                               appProperties={'jarvisMemory': 'true', 'jarvisStorage': 'drive'})
    drive.metadata['saved-file'] = archive_file('saved-file', name='receipt.pdf', mimeType='application/pdf', parents=['root'],
                                               appProperties={'jarvisMemory': 'true', 'jarvisStorage': 'drive'})
    drive.metadata['external-original'] = archive_file('external-original', name='original.pdf', mimeType='application/pdf', parents=['root'])
    result = storage.organize_managed_files()
    assert result['moved_files'] == 2
    assert drive.metadata['archives']['name'] == 'Chat Archives' and drive.metadata['archives']['parents'] == ['jarvis-root']
    assert drive.metadata['cache']['name'] == 'Upload Cache' and drive.metadata['cache']['parents'] == ['jarvis-root']
    assert drive.metadata['old-backup']['parents'] == ['archives']
    assert drive.metadata['saved-file']['parents'] == ['saved']
    assert drive.metadata['external-original']['parents'] == ['root']
    assert auth.record.value['encrypted_refresh_token'] == 'existing-grant'
    assert not any(call.method == 'DELETE' for call in drive.calls)
    assert storage.organize_managed_files()['moved_files'] == 0


def test_actual_my_drive_root_id_does_not_trigger_a_duplicate_parent_move(store):
    storage, drive, auth = store
    auth.record.value[ROOT_FIELD] = 'jarvis-root'
    drive.metadata['root'] = folder('actual-root', name='My Drive', parents=[])
    drive.metadata['jarvis-root'] = folder('jarvis-root', name='Jarvis', parents=['actual-root'])
    assert storage.ensure_root() == 'jarvis-root'
    assert not any(call.method in ('POST', 'PATCH') for call in drive.calls)
