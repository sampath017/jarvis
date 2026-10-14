"""Manual and daily inactivity archives, with verified Drive restoration."""
from hashlib import sha256
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .server_google import owner
from ..auth import get_current_user, DEFAULT_UID
from ...services.automatic_chat_archives import AutomaticChatArchives
from ...services.background_tasks import verify_task_identity
from ...services.chat_archive_drive import DriveChatArchiveStore
from ...services.chat_archive_format import verify, MAX_COMPRESSED
from ...services.chat_archive_retirement import retire, comparable  # Public regression-test compatibility.
from ...services.record_store import RecordStore
from ...services.server_google_auth import ServerGoogleAuth

router = APIRouter(prefix='/chat-archives', tags=['chat-archives'])
background_router = APIRouter(tags=['chat-archives'])


class DriveArchive(BaseModel):
    file_id: str = Field(min_length=1, max_length=200, pattern=r'^[\w-]+$')


class ArchivePolicyUpdate(BaseModel):
    enabled: bool


def service():
    fs = RecordStore()
    if not fs.is_available:
        raise HTTPException(503, 'Cloud archive is unavailable')
    return AutomaticChatArchives(fs._db)


def validate_thread(thread_id):
    if not 1 <= len(thread_id) <= 256 or '/' in thread_id:
        raise HTTPException(422, 'Invalid conversation ID')


def read_drive(connection, file_id):
    auth = ServerGoogleAuth()
    try:
        drive = DriveChatArchiveStore(auth, connection)
        return drive.read(file_id), drive.status()
    finally:
        auth.client.close()


@router.get('/policy')
def policy(uid: Annotated[str, Depends(get_current_user)], connection: Annotated[str, Depends(owner)]):
    return service().policy(uid)


@router.put('/policy')
def update_policy(value: ArchivePolicyUpdate, uid: Annotated[str, Depends(get_current_user)],
                  connection: Annotated[str, Depends(owner)]):
    return service().set_enabled(uid, value.enabled)


@router.post('/{thread_id}/use')
def use_chat(thread_id: str, uid: Annotated[str, Depends(get_current_user)],
             connection: Annotated[str, Depends(owner)]):
    validate_thread(thread_id)
    return service().touch(uid, thread_id)


@router.post('/{thread_id}/backup')
async def upload_backup(thread_id: str, request: Request, uid: Annotated[str, Depends(get_current_user)],
                        connection: Annotated[str, Depends(owner)]):
    validate_thread(thread_id)
    if request.headers.get('content-type', '').split(';')[0] != 'application/gzip':
        raise HTTPException(415, 'Send a compressed conversation backup')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_COMPRESSED:
            raise HTTPException(413, 'Drive backup exceeds 8 MB')
        raw.extend(chunk)
    from starlette.concurrency import run_in_threadpool
    def upload():
        manager = service()
        auth = ServerGoogleAuth(db=manager.db)
        try:
            return manager.archive_bytes(uid, thread_id, connection, bytes(raw), DriveChatArchiveStore(auth, connection))
        finally:
            auth.client.close()
    return await run_in_threadpool(upload)


@router.post('/{thread_id}')
def archive_chat(thread_id: str, value: DriveArchive, uid: Annotated[str, Depends(get_current_user)],
                 connection: Annotated[str, Depends(owner)]):
    """Keep the already-uploaded-file route for older installed phone versions."""
    validate_thread(thread_id)
    manager = service()
    auth = ServerGoogleAuth(db=manager.db)
    try:
        drive = DriveChatArchiveStore(auth, connection)
        current = manager.db.collection('chat_sessions').document(thread_id).get().to_dict() or {}
        if current.get('uid') != uid:
            raise HTTPException(404, 'Conversation not found')
        raw = drive.read(value.file_id)
        email = drive.status()
        try:
            archive = verify(raw)
        except (ValueError, OSError, EOFError) as exc:
            raise HTTPException(422, 'Invalid Drive backup; cloud messages were kept') from exc
        previous = manager.previous_archive(current, thread_id, connection, drive)
        if previous and not {m.id for m in previous.session.messages}.issubset({m.id for m in archive.session.messages}):
            raise HTTPException(409, 'Restore older archived messages before making a new backup')
        digest = sha256(raw).hexdigest()
        return retire(manager.db, uid, thread_id, archive, value.file_id, digest, connection, email,
                      guard=manager._guard(uid, thread_id, current, digest, automatic=False))
    finally:
        auth.client.close()


@router.get('/{thread_id}')
def restore_chat(thread_id: str, uid: Annotated[str, Depends(get_current_user)],
                 connection: Annotated[str, Depends(owner)]):
    validate_thread(thread_id)
    manager = service()
    data = manager.db.collection('chat_sessions').document(thread_id).get().to_dict() or {}
    if data.get('uid') != uid or not data.get('archive_drive_id'):
        raise HTTPException(404, 'No archived history for this conversation')
    if data.get('archive_connection') != connection:
        raise HTTPException(403, 'Use the Google connection that owns this archive')
    raw, _ = read_drive(connection, data['archive_drive_id'])
    if sha256(raw).hexdigest() != data['archive_sha256']:
        raise HTTPException(409, 'Drive backup changed; the local conversation was preserved')
    manager.touch(uid, thread_id)
    return Response(raw, media_type='application/gzip', headers={'Cache-Control': 'private, no-store'})


@background_router.post('/internal/background/chat-archive-daily')
def daily_archives(authorization: Annotated[str | None, Header()] = None):
    verify_task_identity(authorization)
    return service().run_daily(DEFAULT_UID, os.getenv('JARVIS_GOOGLE_OWNER_HASH'))


@background_router.post('/internal/background/jarvis-drive-organize')
def organize_jarvis_drive(authorization: Annotated[str | None, Header()] = None):
    verify_task_identity(authorization)
    from ...services.runtime_power import RuntimePower
    RuntimePower().require_enabled()
    auth = ServerGoogleAuth()
    try:
        drive = DriveChatArchiveStore(auth, os.getenv('JARVIS_GOOGLE_OWNER_HASH'))
        return drive.organize_managed_files()
    finally:
        auth.client.close()
