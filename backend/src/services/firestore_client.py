"""
Firestore Client — durable storage for Jarvis user data.

Implements the per-user document hierarchy from §6 of the technical spec:
    users/{uid}/
        profile, preferences/{id}, tasks/{id}, notes/{id},
        reminders/{id}, places/{id}, mobilitySessions/{id},
        contextEvents/{id}, chatThreads/{id}/messages/{id},
        agentRuns/{id}

All reads/writes are scoped by the verified Firebase UID.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)

# ── Singleton Firebase app ───────────────────────────────────────────────────

_app: firebase_admin.App | None = None


def init_firebase(project_id: str | None = None) -> firebase_admin.App:
    """Initialize the Firebase Admin SDK (idempotent)."""
    global _app
    if _app is not None:
        return _app

    try:
        # On Cloud Run, default credentials are auto-detected from the
        # attached service account.  For local dev, set
        # GOOGLE_APPLICATION_CREDENTIALS env var.
        cred = credentials.ApplicationDefault()
        _app = firebase_admin.initialize_app(cred, {
            "projectId": project_id,
        } if project_id else None)
        logger.info("Firebase Admin SDK initialised (project=%s)", project_id or "auto")
    except ValueError:
        # Already initialised (e.g. in tests)
        _app = firebase_admin.get_app()

    return _app


def get_firestore_client():
    """Return a Firestore client."""
    return firestore.client()


# ── Firestore CRUD helpers ───────────────────────────────────────────────────

class FirestoreService:
    """
    Scoped Firestore operations for a single user.

    Every method takes ``uid`` to enforce per-user data isolation.
    """

    def __init__(self, db=None) -> None:
        self._db = db

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    # ── helpers ──────────────────────────────────────────────────────────

    def _user_ref(self, uid: str):
        return self.db.collection("users").document(uid)

    def _collection(self, uid: str, name: str):
        return self._user_ref(uid).collection(name)

    # ── Generic CRUD ─────────────────────────────────────────────────────

    def create_document(
        self,
        uid: str,
        collection: str,
        doc_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a document, returning the stored data."""
        now = datetime.utcnow().isoformat()
        record = {
            "id": doc_id,
            "created_at": now,
            "updated_at": now,
            **data,
        }
        self._collection(uid, collection).document(doc_id).set(record)
        logger.debug("Created %s/%s for uid=%s", collection, doc_id, uid)
        return record

    def get_document(
        self,
        uid: str,
        collection: str,
        doc_id: str,
    ) -> dict[str, Any] | None:
        """Read a single document by ID."""
        snap = self._collection(uid, collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def update_document(
        self,
        uid: str,
        collection: str,
        doc_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update fields on an existing document."""
        ref = self._collection(uid, collection).document(doc_id)
        snap = ref.get()
        if not snap.exists:
            return None
        data["updated_at"] = datetime.utcnow().isoformat()
        ref.update(data)
        updated = ref.get()
        return updated.to_dict()

    def delete_document(
        self,
        uid: str,
        collection: str,
        doc_id: str,
    ) -> bool:
        """Delete a document.  Returns True if it existed."""
        ref = self._collection(uid, collection).document(doc_id)
        snap = ref.get()
        if not snap.exists:
            return False
        ref.delete()
        return True

    def list_documents(
        self,
        uid: str,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List documents, with optional equality filters."""
        query = self._collection(uid, collection)
        if filters:
            for key, value in filters.items():
                query = query.where(key, "==", value)
        query = query.limit(limit)
        return [snap.to_dict() for snap in query.stream()]

    # ── Idempotent event write ───────────────────────────────────────────

    def create_event_idempotent(
        self,
        uid: str,
        event_id: str,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """
        Write a context event only if its ``event_id`` has not been seen.

        Returns ``(record, created)`` where ``created`` is False if the
        event already existed (idempotent replay).
        """
        ref = self._collection(uid, "contextEvents").document(event_id)
        snap = ref.get()
        if snap.exists:
            return snap.to_dict(), False

        record = self.create_document(uid, "contextEvents", event_id, data)
        return record, True

    # ── Session helpers ──────────────────────────────────────────────────

    def get_active_session(self, uid: str) -> dict[str, Any] | None:
        """Return the currently active or paused mobility session, if any."""
        for status in ("ACTIVE", "PAUSED", "RESUMED"):
            docs = self.list_documents(
                uid, "mobilitySessions", filters={"status": status}, limit=1,
            )
            if docs:
                return docs[0]
        return None

    def upsert_session(
        self,
        uid: str,
        session_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update a mobility session document."""
        ref = self._collection(uid, "mobilitySessions").document(session_id)
        snap = ref.get()
        if snap.exists:
            return self.update_document(uid, "mobilitySessions", session_id, data)
        return self.create_document(uid, "mobilitySessions", session_id, data)

    # ── Chat thread helpers ──────────────────────────────────────────────

    def append_chat_message(
        self,
        uid: str,
        thread_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a message to a chat thread."""
        msg_id = message.get("message_id", message.get("id", ""))
        ref = (
            self._user_ref(uid)
            .collection("chatThreads").document(thread_id)
            .collection("messages").document(msg_id)
        )
        now = datetime.utcnow().isoformat()
        message.setdefault("created_at", now)
        ref.set(message)

        thread_ref = self._user_ref(uid).collection("chatThreads").document(thread_id)
        thread_snapshot = thread_ref.get()
        thread_data = {
            "thread_id": thread_id,
            "updated_at": now,
            "last_message_preview": str(message.get("content", ""))[:140],
        }
        if not thread_snapshot.exists:
            thread_data["created_at"] = now
            thread_data["title"] = (
                str(message.get("content", ""))[:48] if message.get("role") == "user" else "New chat"
            ) or "New chat"
        thread_ref.set(thread_data, merge=True)

        return message

    def get_recent_messages(
        self,
        uid: str,
        thread_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the most recent messages in a chat thread."""
        ref = (
            self._user_ref(uid)
            .collection("chatThreads").document(thread_id)
            .collection("messages")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        messages = [snap.to_dict() for snap in ref.stream()]
        messages.reverse()  # chronological order
        return messages

    # ── Scoped retrieval (§3 Phase 1 retrieval contract) ────────────────

    def load_scoped_context(
        self,
        uid: str,
        place_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Load only the context needed for an LLM call.

        Returns a dict with keys: session, tasks, reminders, messages, preferences.
        """
        context: dict[str, Any] = {}

        # Active session
        context["session"] = self.get_active_session(uid)

        # Open tasks
        context["tasks"] = self.list_documents(uid, "tasks", limit=10)

        # Recent messages
        if thread_id:
            context["messages"] = self.get_recent_messages(uid, thread_id, limit=10)
        else:
            context["messages"] = []

        # User preferences
        context["preferences"] = self.list_documents(uid, "preferences", limit=20)

        return context

    # ── Agent run recording ──────────────────────────────────────────────

    def record_agent_run(
        self,
        uid: str,
        run_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Record an agent run for auditability."""
        return self.create_document(uid, "agentRuns", run_id, data)

    def complete_agent_run(
        self,
        uid: str,
        run_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Mark an agent run as completed with final metrics."""
        data["completed_at"] = datetime.utcnow().isoformat()
        data["status"] = "completed"
        return self.update_document(uid, "agentRuns", run_id, data)
