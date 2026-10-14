"""The private paired phone can stop and resume the entire development runtime."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from .server_google import owner as paired_owner
import os
from ...services.runtime_power import RuntimePower

router = APIRouter(prefix='/runtime', tags=['runtime-power'])


def owner(x_calendar_session: Annotated[str, Header()] = ''):
    if not os.getenv('JARVIS_GOOGLE_OWNER_HASH'):
        raise HTTPException(503, 'Cloud power control needs a paired phone.')
    return paired_owner(x_calendar_session)


class PowerRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    enabled: bool


@router.get('/power')
def status(connection: Annotated[str, Depends(owner)]):
    return RuntimePower().status()


@router.put('/power')
def set_power(body: PowerRequest, connection: Annotated[str, Depends(owner)]):
    result = RuntimePower().set(body.enabled)
    if result['enabled']:
        from ...services.drive_index_queue import kick, jobs
        from src.services import sqlite_documents as documents
        try:
            if list(jobs().where(filter=documents.FieldFilter('status', '==', 'queued')).limit(1).stream()):
                kick()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Power resumed; staged Drive indexing will retry on the next index status request')
    return result

