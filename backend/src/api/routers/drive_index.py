"""Authenticated index operations; no Drive tokens stored or forwarded."""
from typing import Annotated
import anyio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .file_memories import owner, get_metadata
from ...services import drive_index as service

router = APIRouter(prefix='/drive-index', tags=['drive-index'])
logger = logging.getLogger(__name__)
index_capacity = anyio.CapacityLimiter(1)


def ready():
    if not service.configured():
        raise HTTPException(503, 'Drive indexing is not configured yet')


@router.get('/status')
def status(uid: Annotated[str, Depends(owner)]):
    return {'configured': service.configured(), 'background': False, 'storage': 'chroma',
        'reader_version': 2, 'supported': ['documents', 'spreadsheets', 'presentations', 'archives', 'media', 'forms', 'shortcuts', 'binary metadata and strings']}


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    account: str = Field(min_length=1, max_length=320)


class Evidence(Search):
    file_id: str = Field(min_length=1, max_length=256)
    source_version: str = Field(max_length=128)


class VerifiedFile(BaseModel):
    file_id: str = Field(min_length=1, max_length=256)
    source_version: str = Field(max_length=128)


class ContentSearch(Search):
    files: list[VerifiedFile] = Field(max_length=62)


@router.post('/search-contents')
def content_search(body: ContentSearch, uid: Annotated[str, Depends(owner)]):
    ready()
    return service.search_contents(uid, body.account, body.query, [file.model_dump() for file in body.files])


@router.post('/evidence')
def read_evidence(body: Evidence, uid: Annotated[str, Depends(owner)]):
    ready()
    return service.evidence(uid, body.account, body.file_id, body.source_version, body.query)


@router.post('/search')
def search(body: Search, uid: Annotated[str, Depends(owner)]):
    ready()
    try:
        return service.search(uid, body.account, body.query)
    except Exception as exc:
        logger.exception('Drive index search failed')
        raise HTTPException(503, 'Drive content search is temporarily unavailable') from exc


@router.post('/files/{file_id}')
async def put(file_id: str, request: Request, uid: Annotated[str, Depends(owner)]):
    # One upload/index stream per backend instance keeps its 512 MiB RAM bounded;
    # search, telemetry and chat continue on the event loop and other worker threads.
    async with index_capacity:
        return await put_stream(file_id, request, uid)


async def put_stream(file_id: str, request: Request, uid: str):
    ready()
    memory = await run_in_threadpool(get_metadata, uid, file_id)
    if not memory:
        raise HTTPException(404, 'File metadata not registered')
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 128 * 1024 * 1024:
            raise HTTPException(413, 'File exceeds the 128 MB processing limit')
    try:
        return await run_in_threadpool(service.put_file, uid, memory, bytes(raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception('Drive file indexing failed')
        raise HTTPException(503, 'File indexing failed; retry to resume') from exc


@router.delete('/files/{file_id}')
def remove(file_id: str, account: str, uid: Annotated[str, Depends(owner)]):
    ready()
    service.index().delete(where=service.where_file(uid, account, file_id))
    return {'removed': True}
