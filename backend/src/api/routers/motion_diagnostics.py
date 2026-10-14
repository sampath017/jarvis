"""Shadow detector telemetry never enters the activity/automation workflow."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from src.services.sqlite_documents import FieldFilter

from ...models.telemetry import MotionDiagnosticBatch
from ...services.record_store import RecordStore
from ...backend.context_history import utc_time
from ..auth import get_current_user
from ..rate_limiter import TokenBudgetGuard

router = APIRouter(tags=['motion-diagnostics'])


def collection(uid):
    fs = RecordStore()
    if not fs.is_available:
        raise HTTPException(503, 'Motion diagnostics temporarily unavailable')
    return fs._db.collection('users').document(uid).collection('motion_diagnostics')


@router.post('/motion-diagnostics')
def save_motion_diagnostics(request: MotionDiagnosticBatch, uid: Annotated[str, Depends(get_current_user)]):
    TokenBudgetGuard().check_request_rate(uid)
    ref = collection(uid)
    received = datetime.now(timezone.utc).isoformat()
    try:
        # Stable IDs make retrying a batch safe. No sessions, Places, AI or reminders.
        batch = ref._client.batch()
        for record in request.records:
            data = record.model_dump(mode='json', exclude_none=True)
            data['timestamp'] = utc_time(record.timestamp).isoformat()
            data['server_received_at'] = received
            batch.set(ref.document(record.id), data)
        batch.commit()
    except Exception as exc:
        raise HTTPException(503, 'Motion diagnostics were not acknowledged') from exc
    return {'accepted_ids': [r.id for r in request.records]}


@router.get('/motion-diagnostics')
def get_motion_diagnostics(start_at: str, end_at: str, uid: Annotated[str, Depends(get_current_user)]):
    try:
        start, end = utc_time(start_at), utc_time(end_at)
        if start >= end or (end-start).total_seconds() > 26*3600:
            raise ValueError('Choose one day at a time')
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        records = [d.to_dict() for d in collection(uid)
                   .where(filter=FieldFilter('timestamp', '>=', start.isoformat()))
                   .where(filter=FieldFilter('timestamp', '<', end.isoformat()))
                   .order_by('timestamp').limit(6001).stream()]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, 'Motion diagnostics temporarily unavailable') from exc
    return {'records': records[:6000], 'truncated': len(records) > 6000,
            'interpretation': 'Provisional phone-motion candidates only; not confirmed personal activities.'}
