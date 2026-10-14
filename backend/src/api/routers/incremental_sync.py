"""Bounded synchronization pages with explicit deletes and replay-safe cursors."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from ..auth import get_current_user
from ...services.record_store import RecordStore
from ...services.sync_change_feed import SyncChangeFeed

router = APIRouter(prefix='/sync', tags=['sync'])


@router.get('/changes')
async def changes(uid: Annotated[str, Depends(get_current_user)],
                  cursor: str | None = Query(default=None, max_length=2048),
                  limit: int = Query(default=100, ge=1, le=200)):
    fs = RecordStore()
    if not fs.is_available:
        raise HTTPException(503, 'Cloud sync is unavailable; local records are preserved')
    try:
        return await run_in_threadpool(SyncChangeFeed(fs._db).pull, uid, cursor, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Could not read sync changes; retry from the saved cursor') from exc
