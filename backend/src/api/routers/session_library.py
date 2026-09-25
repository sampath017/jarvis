"""Durable display preferences and recording backups for the mobile library."""
from hashlib import sha256
from tempfile import TemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth import get_current_user
from ...services.firestore_service import FirestoreService

router = APIRouter(prefix="/session-library", tags=["session-library"])
MAX_RECORDING_BYTES = 128 * 1024 * 1024


def collection(uid: str, kind: str):
    fs = FirestoreService()
    if not fs.is_available:
        raise HTTPException(503, "Cloud storage is unavailable")
    return fs._db.collection("session_libraries").document(uid).collection(kind)


def key(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class Preference(BaseModel):
    id: str = Field(min_length=1, max_length=240)
    name: str | None = Field(default=None, max_length=60)
    archived: bool = False


@router.get("/preferences")
def preferences(uid: Annotated[str, Depends(get_current_user)]):
    return {"items": [d.to_dict() for d in collection(uid, "preferences").stream()]}


@router.put("/preferences")
def save_preference(value: Preference, uid: Annotated[str, Depends(get_current_user)]):
    collection(uid, "preferences").document(key(value.id)).set(value.model_dump())
    return {"saved": True}


class Recording(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    start_time: str
    end_time: str | None = None
    label: str = Field(max_length=160)
    mount_position: str = Field(default="", max_length=160)
    road_condition: str = Field(default="", max_length=160)
    sample_count: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    csv_size_bytes: int = Field(ge=0, le=MAX_RECORDING_BYTES)


def blob(uid: str, recording_id: str, kind: str):
    if kind not in {"csv", "json"}:
        raise HTTPException(422, "Unsupported recording file")
    from google.cloud import storage
    return storage.Client().bucket("jarvis-agent-61947-recordings").blob(
        f"{key(uid)}/{key(recording_id)}/{kind}")


@router.get("/recordings")
def recordings(uid: Annotated[str, Depends(get_current_user)]):
    return {"items": [d.to_dict() for d in collection(uid, "recordings").stream()]}


@router.put("/recordings/{recording_id}/files/{kind}")
async def upload(recording_id: str, kind: str, request: Request,
                 uid: Annotated[str, Depends(get_current_user)]):
    if not 1 <= len(recording_id) <= 160:
        raise HTTPException(422, "Invalid recording ID")
    target = blob(uid, recording_id, kind)
    with TemporaryFile() as file:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > (1024 * 1024 if kind == "json" else MAX_RECORDING_BYTES):
                raise HTTPException(413, "Recording exceeds the 128 MB backup limit")
            file.write(chunk)
        file.seek(0)
        if kind == "json":
            try:
                summary = Recording.model_validate_json(file.read())
                if summary.id != recording_id:
                    raise ValueError("Recording ID mismatch")
            except (ValidationError, ValueError) as exc:
                raise HTTPException(422, "Invalid recording summary") from exc
            file.seek(0)
        await run_in_threadpool(target.upload_from_file, file, size=total, timeout=300)
    return {"saved": True}


@router.put("/recordings")
def save_recording(value: Recording, uid: Annotated[str, Depends(get_current_user)]):
    csv = blob(uid, value.id, "csv")
    csv.reload()
    summary_blob = blob(uid, value.id, "json")
    if csv.size != value.csv_size_bytes or not summary_blob.exists():
        raise HTTPException(409, "Upload both recording files before completing backup")
    summary = Recording.model_validate_json(summary_blob.download_as_bytes(timeout=30))
    if summary.model_dump() != value.model_dump():
        raise HTTPException(409, "Recording summary does not match the uploaded files")
    collection(uid, "recordings").document(key(value.id)).set(value.model_dump())
    return {"saved": True}


@router.get("/recordings/{recording_id}/files/{kind}")
def download(recording_id: str, kind: str, uid: Annotated[str, Depends(get_current_user)]):
    if not collection(uid, "recordings").document(key(recording_id)).get().exists:
        raise HTTPException(404, "Recording not found")
    target = blob(uid, recording_id, kind)
    def chunks():
        with target.open("rb") as file:
            while chunk := file.read(256 * 1024):
                yield chunk
    return StreamingResponse(chunks(), media_type="application/octet-stream")


@router.delete("/recordings/{recording_id}")
def delete_recording(recording_id: str, uid: Annotated[str, Depends(get_current_user)]):
    from google.api_core.exceptions import NotFound
    for kind in ("csv", "json"):
        try:
            blob(uid, recording_id, kind).delete()
        except NotFound:
            pass
    collection(uid, "recordings").document(key(recording_id)).delete()
    return {"deleted": True}
