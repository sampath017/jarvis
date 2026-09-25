"""CRUD and mobile-outbox endpoints for deterministic personal automation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...backend.context_automation import ContextAutomationService
from ...models.schemas import (
    ContextRuleCreateRequest,
    ContextRulePatchRequest,
    NoteCreateRequest,
    NotePatchRequest,
    ReminderCreateRequest,
    ReminderPatchRequest,
)
from ...services.database import DatabaseService
from ...services.firestore_service import FirestoreService
from ..auth import get_current_user


router = APIRouter(tags=["personal-automation"])


def _db() -> DatabaseService:
    return DatabaseService()


def _fs() -> FirestoreService:
    return FirestoreService()


@router.get("/context-memory")
def context_memory(uid: Annotated[str, Depends(get_current_user)],
                   lookback_minutes: int | None = Query(default=None, ge=1, le=44640),
                   start_at: str = "", end_at: str = "") -> dict[str, object]:
    fs = _fs()
    if lookback_minutes is not None or start_at or end_at:
        from ...backend.context_history import history_window, build_timeline
        try:
            start, end = history_window(lookback_minutes or 2880, start_at, end_at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            records, truncated = fs.query_context_memory(uid, start, end)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Context history temporarily unavailable") from exc
        return build_timeline(records, start, end, truncated=truncated)
    records = fs.get_context_memory(uid, limit=50) if fs.is_available else []
    return {"records": records, "count": len(records)}


@router.get("/activity-history")
def activity_history(
    uid: Annotated[str, Depends(get_current_user)],
    start_at: str,
    end_at: str,
) -> dict[str, object]:
    """Return one local day's sampled events and overlapping journey sessions."""
    from ...backend.context_history import build_timeline, utc_time

    try:
        start, end = utc_time(start_at), utc_time(end_at)
        if start >= end or (end - start).total_seconds() > 26 * 3600:
            raise ValueError("Choose one day at a time")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    fs = _fs()
    try:
        records, truncated = fs.query_context_memory(uid, start, end)
        sessions = fs.get_mobility_sessions(uid)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Activity history temporarily unavailable") from exc

    observations = [
        {
            "event_id": record.get("event_id"),
            "timestamp": record.get("timestamp"),
            "activity": record.get("activity"),
            "transition": record.get("transition"),
            "gps": record.get("gps"),
            "session_id": record.get("mobility_session_id"),
            "saved_places": record.get("saved_places") or [],
            "nearby_candidates": record.get("nearby_candidates") or [],
            "contexts": record.get("contexts") or [],
            "context_changes": record.get("context_changes") or [],
        }
        for record in records
    ]
    overlapping_sessions = []
    for session in sessions:
        try:
            opened = utc_time(session["started_at"])
            closed = utc_time(session.get("completed_at") or session["last_updated"])
        except (KeyError, TypeError, ValueError):
            continue
        if opened >= end or closed < start:
            continue
        overlapping_sessions.append({
            "session_id": session.get("session_id") or session.get("id"),
            "started_at": session.get("started_at"),
            "last_updated": session.get("last_updated"),
            "completed_at": session.get("completed_at"),
            "status": session.get("status"),
            "vehicle_class": session.get("vehicle_class"),
            "parking_gps": session.get("parking_gps"),
            "poi_visits": session.get("poi_visits") or [],
            "resume_count": session.get("resume_count") or 0,
        })
    return {
        # The remaining hours of today are not missing observations.
        **build_timeline(records, start, min(end, datetime.now(timezone.utc)), truncated=truncated),
        "observations": observations,
        "sessions": overlapping_sessions,
    }


@router.get("/notes")
def list_notes(uid: Annotated[str, Depends(get_current_user)]) -> dict[str, object]:
    fs = _fs()
    if fs.is_available:
        records = [n for n in fs.get_notes(uid) if not n.get("deleted_at")]
        return {"records": records, "count": len(records)}
    records = _db().list_notes(uid)
    return {"records": records, "count": len(records)}


@router.post("/notes", status_code=status.HTTP_201_CREATED)
def create_note(
    request: NoteCreateRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    data = request.model_dump()
    data["uid"] = uid
    fs = _fs()
    if fs.is_available:
        import uuid
        note_id = str(uuid.uuid4())
        fs.save_note(note_id, data)
    return _db().create_note(uid, data)


@router.patch("/notes/{note_id}")
def update_note(
    note_id: str,
    request: NotePatchRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    record = _db().update_note(uid, note_id, request.model_dump(exclude_unset=True))
    if record is None:
        raise HTTPException(status_code=404, detail="Note not found")
    fs = _fs()
    if fs.is_available:
        fs.save_note(note_id, record)
    return record


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: str, uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    db = _db()
    existing = db.get_note(uid, note_id)
    if existing is None and fs.is_available:
        existing = next((n for n in fs.get_notes(uid) if n.get("id") == note_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Note not found")
    deleted_at = datetime.now(timezone.utc).isoformat()
    data = {**existing, "id": note_id, "uid": uid, "deleted_at": deleted_at, "updated_at": deleted_at}
    db.create_note(uid, data)
    if fs.is_available:
        fs.save_note(note_id, data)
    return None


@router.post("/notes/{note_id}/restore")
def restore_note(note_id: str, uid: Annotated[str, Depends(get_current_user)]) -> dict[str, object]:
    fs = _fs()
    db = _db()
    existing = db.get_note(uid, note_id)
    if existing is None and fs.is_available:
        existing = next((n for n in fs.get_notes(uid) if n.get("id") == note_id), None)
    if existing is None or not existing.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Note not in Trash")
    data = {**existing, "id": note_id, "uid": uid, "deleted_at": None}
    record = db.create_note(uid, data)
    if fs.is_available:
        fs.save_note(note_id, {**record, "deleted_at": None})
    return record


@router.delete("/notes", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_notes_endpoint(uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    records = fs.get_notes(uid) if fs.is_available else _db().list_notes(uid, limit=1000)
    for n in records:
        if not n.get("deleted_at"):
            delete_note(n["id"], uid)
    return None


@router.get("/reminders")
def list_reminders(
    uid: Annotated[str, Depends(get_current_user)],
    status: str | None = None,
) -> dict[str, object]:
    fs = _fs()
    if fs.is_available:
        try:
            docs = fs._db.collection('reminders').where('uid', '==', uid).stream()
            records = [d.to_dict() for d in docs]
        except Exception as exc:
            raise HTTPException(503, 'Reminders temporarily unavailable') from exc
        records = [r for r in records if r.get('status') == status] if status else [r for r in records if r.get('status') != 'DELETED']
        for reminder in records: _db().create_reminder(uid, reminder)
    else:
        records = _db().list_reminders(uid, status=status)
    return {"records": records, "count": len(records)}


@router.post("/reminders", status_code=status.HTTP_201_CREATED)
def create_reminder(
    request: ReminderCreateRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    record = _db().create_reminder(uid, request.model_dump(mode="json"))
    fs = _fs()
    if fs.is_available:
        fs.save_reminder(record["id"], {**record, "uid": uid})
    return record


@router.patch("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: str,
    request: ReminderPatchRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    db = _db()
    existing = db.get_reminder(uid, reminder_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    patch = request.model_dump(mode="json", exclude_unset=True)
    validated = ReminderCreateRequest.model_validate({**existing, **patch})
    return db.update_reminder(uid, reminder_id, validated.model_dump(mode="json")) or existing


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: str, uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    db = _db()
    existing = db.get_reminder(uid, reminder_id)
    if existing is None and fs.is_available:
        existing = next((r for r in fs.get_reminders(uid) if r.get("id") == reminder_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    deleted_at = datetime.now(timezone.utc).isoformat()
    data = {**existing, "id": reminder_id, "uid": uid, "previous_status": existing.get("status", "ACTIVE"),
            "status": "DELETED", "deleted_at": deleted_at, "updated_at": deleted_at}
    db.create_reminder(uid, data)
    if fs.is_available:
        fs.save_reminder(reminder_id, data)
    return None


@router.post("/reminders/{reminder_id}/restore")
def restore_reminder(reminder_id: str, uid: Annotated[str, Depends(get_current_user)]) -> dict[str, object]:
    fs = _fs()
    db = _db()
    existing = db.get_reminder(uid, reminder_id)
    if existing is None and fs.is_available:
        existing = next((r for r in fs.get_reminders(uid) if r.get("id") == reminder_id), None)
    if existing is None or existing.get("status") != "DELETED":
        raise HTTPException(status_code=404, detail="Reminder not in Trash")
    data = {**existing, "id": reminder_id, "uid": uid,
            "status": existing.get("previous_status") or "ACTIVE", "previous_status": None,
            "deleted_at": None}
    record = db.create_reminder(uid, data)
    if fs.is_available:
        fs.save_reminder(reminder_id, {**record, "deleted_at": None, "previous_status": None})
    return record


@router.delete("/reminders", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_reminders_endpoint(uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    records = fs.get_reminders(uid) if fs.is_available else _db().list_reminders(uid, limit=1000)
    for r in records:
        if r.get("status") != "DELETED":
            delete_reminder(r["id"], uid)
    return None


@router.get("/context-rules")
def list_context_rules(
    uid: Annotated[str, Depends(get_current_user)],
    enabled: bool | None = None,
) -> dict[str, object]:
    records = _db().list_context_rules(uid, enabled=enabled)
    return {"records": records, "count": len(records)}


@router.post("/context-rules", status_code=status.HTTP_201_CREATED)
def create_context_rule(
    request: ContextRuleCreateRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    return _db().create_context_rule(uid, request.model_dump(mode="json"))


@router.patch("/context-rules/{rule_id}")
def update_context_rule(
    rule_id: str,
    request: ContextRulePatchRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    db = _db()
    existing = db.get_context_rule(uid, rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Context rule not found")
    patch = request.model_dump(mode="json", exclude_unset=True)
    validated = ContextRuleCreateRequest.model_validate({**existing, **patch})
    return db.update_context_rule(uid, rule_id, validated.model_dump(mode="json")) or existing


@router.delete("/context-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_context_rule(rule_id: str, uid: Annotated[str, Depends(get_current_user)]) -> None:
    if not _db().delete_context_rule(uid, rule_id):
        raise HTTPException(status_code=404, detail="Context rule not found")


@router.get("/notifications")
def list_notifications(
    uid: Annotated[str, Depends(get_current_user)],
    notification_status: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, object]:
    # Polling is also a reliable fallback when the API process was asleep when a
    # time reminder became due; the lifespan sweeper handles the normal case.
    fs = _fs()
    db = _db()
    if fs.is_available:
        for reminder in fs.get_reminders(uid):
            db.create_reminder(uid, reminder)
        latest = fs.get_context_memory(uid, limit=1)
        if latest:
            event = latest[0]
            db.create_event_idempotent(uid, event["event_id"], event)
    _ = ContextAutomationService(db=db).process_due_reminders()
    if fs.is_available:
        records = fs.get_notifications(uid, notification_status)
        records.extend(r for r in db.list_notifications(uid, status=notification_status) if r.get("context_rule_id"))
        return {"records": records, "count": len(records)}
    records = _db().list_notifications(uid, status=notification_status)
    return {"records": records, "count": len(records)}


@router.post("/notifications/{notification_id}/acknowledge")
def acknowledge_notification(
    notification_id: str,
    uid: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    fs = _fs()
    record = fs.acknowledge_cloud_notification(uid, notification_id) if fs.is_available else None
    record = record or _db().acknowledge_notification(uid, notification_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return record
