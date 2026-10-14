"""Computation over Android-supplied state; results return in the same response."""
from typing import Annotated
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth import get_current_user
from .automation import activity_history
from ...services.file_readers import Coverage
from ...services.drive_index import chunks

router = APIRouter(prefix='/mobile', tags=['mobile-compute'])


@router.post('/activity-history')
def history(payload: dict, uid: Annotated[str, Depends(get_current_user)]):
    return activity_history(uid, payload['start_at'], payload['end_at'])


@router.post('/parse-file')
async def parse_file(request: Request):
    import asyncio
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 128 * 1024 * 1024:
            raise HTTPException(413, 'File exceeds the 128 MB processing limit')
    mime = request.headers.get('x-file-mime', 'application/octet-stream')
    from urllib.parse import unquote
    title = unquote(request.headers.get('x-file-name', 'file'))
    def parse():
        coverage = Coverage()
        result = []
        total = 0
        for item, text, locator in chunks(bytes(raw), mime, title, coverage):
            if text:
                total += len(text)
                if total > 16 * 1024 * 1024 or len(result) >= 12000:
                    raise HTTPException(413, 'Extracted text exceeds the mobile index limit')
                result.append({'text': text, 'locator': locator,
                               'content_kind': item.get('_content_kind', 'content')})
        return {'chunks': result, 'coverage': coverage.report()}
    return await asyncio.to_thread(parse)
