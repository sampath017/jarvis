"""Computation over Android-supplied state; results return in the same response."""
from typing import Annotated
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth import get_current_user
from .automation import activity_history
from ...services.file_readers import Coverage
from ...services.drive_index import chunks

router = APIRouter(prefix='/mobile', tags=['mobile-compute'])


@router.post('/departure-boundaries')
def departure_boundaries(uid: Annotated[str, Depends(get_current_user)]):
    from ...services.database import DatabaseService
    from ...services.departure_setup import cached_boundary, ensure_boundary, departure_policy
    db = DatabaseService()
    places = db.list_places(uid,limit=1000)
    refreshed, upgraded, pending = [], [], set()
    provider_origins = 0
    for reminder in db.list_reminders(uid,status='ACTIVE',limit=1000):
        if reminder.get('deleted_at'):
            continue
        try:
            policy = json.loads(reminder['dynamic_policy']) if isinstance(reminder.get('dynamic_policy'),str) else reminder.get('dynamic_policy') or {}
        except ValueError:
            continue
        if not isinstance(policy,dict):
            continue
        origin = policy.get('origin') or {}
        if not isinstance(origin,dict):
            continue
        if policy.get('trigger') != 'exit':
            continue
        if not origin.get('place_id') and not isinstance(origin.get('name'),str):
            continue
        matches = [p for p in places if p['id']==origin.get('place_id')] if origin.get('place_id') else [
            p for p in places if p['name'].casefold()==origin.get('name','').casefold()]
        if len(matches)!=1:
            continue
        place = matches[0]
        if place['id'] not in refreshed:
            fresh, _ = cached_boundary(place)
            if not fresh and provider_origins >= 1:
                pending.add(place['id'])
                continue
            ensure_boundary(db,uid,place)
            refreshed.append(place['id'])
            if not fresh:
                provider_origins += 1
        if policy.get('version') != 2:
            upgraded_policy = {**policy, **departure_policy(place)}
            upgraded_policy.pop('radius_m',None)
            db.update_reminder(uid,reminder['id'],{'dynamic_policy':upgraded_policy})
            upgraded.append(reminder['id'])
    return {'status':'ok','refreshed':refreshed,'updated_reminders':upgraded,
            'pending_places':sorted(pending)}


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
