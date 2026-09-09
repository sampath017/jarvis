"""
Cloud Firestore Service for Jarvis.

Stores and synchronizes Reminders, Notes, Places, and Tasks across Cloud Run
and Android mobile clients in real-time. Eliminates ephemeral container SQLite
loss on Cloud Run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30))

try:
    from google.cloud import firestore
except ImportError:
    firestore = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class FirestoreService:
    """Manages Firestore persistence for reminders, notes, places, tasks, and sync."""

    _instance: Optional[FirestoreService] = None

    def __new__(cls) -> FirestoreService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self) -> None:
        self._db = None
        if firestore is None:
            logger.warning("google-cloud-firestore not installed, Firestore disabled")
            return
        try:
            self._db = firestore.Client(project="jarvis-agent-61947")
            logger.info("Connected to Google Cloud Firestore (jarvis-agent-61947)")
        except Exception as e:
            logger.warning("Failed to initialize Firestore Client: %s", e)
            self._db = None

    @property
    def is_available(self) -> bool:
        return self._db is not None

    # ── Reminders ─────────────────────────────────────────────────────────────
    def save_reminder(self, reminder_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = reminder_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._db.collection("reminders").document(reminder_id).set(doc_data, merge=True)
            logger.info("Saved reminder %s to Firestore", reminder_id)
            return True
        except Exception as e:
            logger.error("Error saving reminder to Firestore: %s", e)
            return False

    def get_reminders(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._db.collection("reminders").stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", "user-456", "user-react-2", None):
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching reminders from Firestore: %s", e)
            return []

    def delete_reminder(self, reminder_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._db.collection("reminders").document(reminder_id).delete()
            logger.info("Deleted reminder %s from Firestore", reminder_id)
            return True
        except Exception as e:
            logger.error("Error deleting reminder from Firestore: %s", e)
            return False

    # ── Notes ─────────────────────────────────────────────────────────────────
    def save_note(self, note_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = note_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._db.collection("notes").document(note_id).set(doc_data, merge=True)
            logger.info("Saved note %s to Firestore", note_id)
            return True
        except Exception as e:
            logger.error("Error saving note to Firestore: %s", e)
            return False

    def get_notes(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._db.collection("notes").stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", "user-456", "user-react-2", None):
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching notes from Firestore: %s", e)
            return []

    def delete_note(self, note_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._db.collection("notes").document(note_id).delete()
            logger.info("Deleted note %s from Firestore", note_id)
            return True
        except Exception as e:
            logger.error("Error deleting note from Firestore: %s", e)
            return False

    # ── Places ────────────────────────────────────────────────────────────────
    def save_place(self, place_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = place_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._db.collection("places").document(place_id).set(doc_data, merge=True)
            logger.info("Saved place %s to Firestore", place_id)
            return True
        except Exception as e:
            logger.error("Error saving place to Firestore: %s", e)
            return False

    def get_places(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._db.collection("places").stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", "user-456", "user-react-2", None):
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching places from Firestore: %s", e)
            return []

    def delete_place(self, place_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._db.collection("places").document(place_id).delete()
            logger.info("Deleted place %s from Firestore", place_id)
            return True
        except Exception as e:
            logger.error("Error deleting place from Firestore: %s", e)
            return False

    # ── Chat Sessions & Messages ─────────────────────────────────────────────
    def save_chat_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = session_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._db.collection("chat_sessions").document(session_id).set(doc_data, merge=True)
            logger.info("Saved chat session %s to Firestore", session_id)
            return True
        except Exception as e:
            logger.error("Error saving chat session to Firestore: %s", e)
            return False

    def get_chat_sessions(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._db.collection("chat_sessions").stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", "user-456", "user-react-2", None):
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching chat sessions from Firestore: %s", e)
            return []

    def save_chat_message(self, uid: str, thread_id: str, message: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            msg_id = message.get("id") or message.get("message_id") or str(datetime.now().timestamp())
            doc_data = {
                "id": msg_id,
                "uid": uid,
                "thread_id": thread_id,
                "role": message.get("role", "user"),
                "content": message.get("content", ""),
                "timestamp": message.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "run_id": message.get("run_id"),
                "executed_records": message.get("executed_records", []),
            }
            self._db.collection("chat_messages").document(msg_id).set(doc_data, merge=True)
            return True
        except Exception as e:
            logger.error("Error saving chat message to Firestore: %s", e)
            return False

    def get_chat_messages(self, uid: Optional[str] = None, thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            # Valid session check to prevent returning orphaned messages
            valid_threads: Optional[set[str]] = None
            if not thread_id:
                valid_threads = {s.id for s in self._db.collection("chat_sessions").stream()}

            col = self._db.collection("chat_messages")
            if thread_id:
                query = col.where("thread_id", "==", thread_id)
            else:
                query = col
            docs = query.stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                msg_tid = data.get("thread_id")
                if valid_threads is not None and msg_tid not in valid_threads:
                    continue
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", "user-456", "user-react-2", None):
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching chat messages from Firestore: %s", e)
            return []

    def cleanup_orphaned_messages(self) -> int:
        """Purge any chat_messages docs whose thread_id does not exist in chat_sessions."""
        if not self._db:
            return 0
        try:
            sessions = {s.id for s in self._db.collection("chat_sessions").stream()}
            msgs = self._db.collection("chat_messages").stream()
            deleted = 0
            for m in msgs:
                data = m.to_dict()
                tid = data.get("thread_id")
                if not tid or tid not in sessions:
                    m.reference.delete()
                    deleted += 1
            if deleted > 0:
                logger.info("Cleaned up %d orphaned chat messages from Firestore", deleted)
            return deleted
        except Exception as e:
            logger.error("Error cleaning up orphaned chat messages from Firestore: %s", e)
            return 0

    def delete_chat_session(self, session_id: str) -> bool:
        """Delete a chat session and all messages belonging to its thread from Firestore."""
        if not self._db:
            return False
        try:
            self._db.collection("chat_sessions").document(session_id).delete()
            msgs = self._db.collection("chat_messages").where("thread_id", "==", session_id).stream()
            for m in msgs:
                m.reference.delete()
            # Also clean up any lingering orphaned messages
            self.cleanup_orphaned_messages()
            logger.info("Deleted chat session %s and all associated messages from Firestore", session_id)
            return True
        except Exception as e:
            logger.error("Error deleting chat session %s from Firestore: %s", session_id, e)
            return False

    def delete_all_chat_sessions(self, uid: Optional[str] = None) -> bool:
        """Delete all chat sessions and messages for the user from Firestore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("chat_sessions").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    d.reference.delete()
            msgs = self._db.collection("chat_messages").stream()
            for m in msgs:
                data = m.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    m.reference.delete()
            logger.info("Deleted all chat sessions and messages for uid %s from Firestore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all chat sessions from Firestore: %s", e)
            return False

    def delete_all_reminders(self, uid: Optional[str] = None) -> bool:
        """Delete all reminders for the user from Firestore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("reminders").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    d.reference.delete()
            logger.info("Deleted all reminders for uid %s from Firestore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all reminders from Firestore: %s", e)
            return False

    def delete_all_notes(self, uid: Optional[str] = None) -> bool:
        """Delete all notes for the user from Firestore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("notes").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    d.reference.delete()
            logger.info("Deleted all notes for uid %s from Firestore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all notes from Firestore: %s", e)
            return False


    # ── Mobile Bulk Sync ──────────────────────────────────────────────────────
    def process_sync_push(self, uid: str, pending_records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[str]]:
        """Process local mobile SQLite pending items pushed to Firestore."""
        synced: Dict[str, List[str]] = {
            "reminders": [],
            "notes": [],
            "places": [],
            "chat_sessions": [],
            "chat_messages": [],
        }
        if not self._db:
            return synced

        reminders = pending_records.get("reminders", [])
        for r in reminders:
            r_id = r.get("id")
            if r_id:
                data = dict(r)
                data["uid"] = uid
                if self.save_reminder(r_id, data):
                    synced["reminders"].append(r_id)

        notes = pending_records.get("notes", [])
        for n in notes:
            n_id = n.get("id")
            if n_id:
                data = dict(n)
                data["uid"] = uid
                if self.save_note(n_id, data):
                    synced["notes"].append(n_id)

        places = pending_records.get("places", [])
        for p in places:
            p_id = p.get("id")
            if p_id:
                data = dict(p)
                data["uid"] = uid
                if self.save_place(p_id, data):
                    synced["places"].append(p_id)

        chat_sessions = pending_records.get("chat_sessions", [])
        for s in chat_sessions:
            s_id = s.get("id")
            if s_id:
                data = dict(s)
                data["uid"] = uid
                if self.save_chat_session(s_id, data):
                    synced["chat_sessions"].append(s_id)

        chat_messages = pending_records.get("chat_messages", [])
        for m in chat_messages:
            m_id = m.get("id")
            t_id = m.get("thread_id", "default")
            if m_id:
                if self.save_chat_message(uid, t_id, m):
                    synced["chat_messages"].append(m_id)

        return synced

    def process_sync_pull(self, uid: str) -> Dict[str, List[Dict[str, Any]]]:
        """Pull all remote Firestore records for user to reconcile with local mobile SQLite."""
        return {
            "reminders": self.get_reminders(uid),
            "notes": self.get_notes(uid),
            "places": self.get_places(uid),
            "chat_sessions": self.get_chat_sessions(uid),
            "chat_messages": self.get_chat_messages(uid),
        }

