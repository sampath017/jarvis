"""CRUD and mobile-outbox endpoints for deterministic personal automation."""

from __future__ import annotations

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


@router.get("/notes")
def list_notes(uid: Annotated[str, Depends(get_current_user)]) -> dict[str, object]:
    fs = _fs()
    if fs.is_available:
        records = fs.get_notes(uid)
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
    if fs.is_available:
        fs.delete_note(note_id)
    _db().delete_note(uid, note_id)
    return None


@router.delete("/notes", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_notes_endpoint(uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    if fs.is_available:
        fs.delete_all_notes(uid)
    for n in _db().list_notes(uid):
        _db().delete_note(uid, n["id"])
    return None


@router.get("/reminders")
def list_reminders(
    uid: Annotated[str, Depends(get_current_user)],
    status: str | None = None,
) -> dict[str, object]:
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
    if fs.is_available:
        fs.delete_reminder(reminder_id)
    _db().delete_reminder(uid, reminder_id)
    return None


@router.delete("/reminders", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_reminders_endpoint(uid: Annotated[str, Depends(get_current_user)]) -> None:
    fs = _fs()
    if fs.is_available:
        fs.delete_all_reminders(uid)
    for r in _db().list_reminders(uid):
        _db().delete_reminder(uid, r["id"])
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
