"""
Sync Router — Bidirectional synchronization between Mobile SQLite and Cloud Firestore.

Enables offline-first mobile operations where mobile SQLite changes are pushed to Firestore,
and remote Firestore updates (e.g. from LangGraph AI agents) are pulled down to mobile.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ...services.database import DatabaseService
from ...services.firestore_service import FirestoreService
from ..auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


class SyncPushRequest(BaseModel):
    reminders: List[Dict[str, Any]] = Field(default_factory=list)
    notes: List[Dict[str, Any]] = Field(default_factory=list)
    places: List[Dict[str, Any]] = Field(default_factory=list)
    chat_sessions: List[Dict[str, Any]] = Field(default_factory=list)
    chat_messages: List[Dict[str, Any]] = Field(default_factory=list)


class SyncPushResponse(BaseModel):
    status: str = "ok"
    synced: Dict[str, List[str]] = Field(default_factory=dict)


class SyncPullResponse(BaseModel):
    status: str = "ok"
    reminders: List[Dict[str, Any]] = Field(default_factory=list)
    notes: List[Dict[str, Any]] = Field(default_factory=list)
    places: List[Dict[str, Any]] = Field(default_factory=list)
    chat_sessions: List[Dict[str, Any]] = Field(default_factory=list)
    chat_messages: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/push", response_model=SyncPushResponse, status_code=status.HTTP_200_OK)
async def push_offline_records(
    request: SyncPushRequest,
    uid: Annotated[str, Depends(get_current_user)],
) -> SyncPushResponse:
    """Receive pending records created/modified on mobile SQLite and commit to Firestore."""
    fs = FirestoreService()
    db = DatabaseService()
    synced_ids: Dict[str, List[str]] = {
        "reminders": [],
        "notes": [],
        "places": [],
        "chat_sessions": [],
        "chat_messages": [],
    }

    # 1. Reminders
    for r in request.reminders:
        r_id = r.get("id")
        if r_id:
            data = dict(r)
            data["uid"] = uid
            db.create_reminder(uid, data)
            if fs.is_available:
                fs.save_reminder(r_id, data)
            synced_ids["reminders"].append(r_id)

    # 2. Notes
    for n in request.notes:
        n_id = n.get("id")
        if n_id:
            data = dict(n)
            data["uid"] = uid
            db.create_note(uid, data)
            if fs.is_available:
                fs.save_note(n_id, data)
            synced_ids["notes"].append(n_id)

    # 3. Places
    for p in request.places:
        p_id = p.get("id")
        if p_id:
            data = dict(p)
            data["uid"] = uid
            db.create_place(uid, data)
            if fs.is_available:
                fs.save_place(p_id, data)
            synced_ids["places"].append(p_id)

    # 4. Chat Sessions
    for s in request.chat_sessions:
        s_id = s.get("id")
        if s_id:
            data = dict(s)
            data["uid"] = uid
            if fs.is_available:
                fs.save_chat_session(s_id, data)
            synced_ids["chat_sessions"].append(s_id)

    # 5. Chat Messages
    for m in request.chat_messages:
        m_id = m.get("id")
        t_id = m.get("thread_id", "default")
        if m_id:
            if fs.is_available:
                fs.save_chat_message(uid, t_id, m)
            synced_ids["chat_messages"].append(m_id)

    logger.info("Processed sync push for user %s: %s", uid, synced_ids)
    return SyncPushResponse(status="ok", synced=synced_ids)


@router.get("/pull", response_model=SyncPullResponse, status_code=status.HTTP_200_OK)
async def pull_remote_records(
    uid: Annotated[str, Depends(get_current_user)],
) -> SyncPullResponse:
    """Pull all remote records for user to reconcile into local mobile SQLite."""
    fs = FirestoreService()
    db = DatabaseService()

    if fs.is_available:
        records = fs.process_sync_pull(uid)
        return SyncPullResponse(
            status="ok",
            reminders=records.get("reminders", []),
            notes=records.get("notes", []),
            places=records.get("places", []),
            chat_sessions=records.get("chat_sessions", []),
            chat_messages=records.get("chat_messages", []),
        )

    # Fallback to local SQLite if Firestore is unavailable (e.g. testing)
    return SyncPullResponse(
        status="ok",
        reminders=db.list_reminders(uid),
        notes=db.list_notes(uid),
        places=db.list_places(uid),
        chat_sessions=[],
        chat_messages=[],
    )

