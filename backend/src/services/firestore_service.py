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

    # ── Mobility & semantic contexts ────────────────────────────────────────
    # These documents are deliberately uid-scoped.  Cloud Run instances are
    # ephemeral, so neither an in-process cache nor the local SQLite mirror is
    # authoritative for parked/dwell/shop continuity.
    def save_mobility_session(self, uid: str, session_id: str, data: Dict[str, Any]) -> bool:
        """Upsert a cloud mobility session without allowing an older event to win.

        ``last_updated`` should be an ISO-8601 UTC timestamp supplied by the
        session reducer.  The Firestore transaction protects concurrent Cloud
        Run requests; the guarded non-transactional branch exists only for
        lightweight test doubles that do not implement transactions.
        """
        if not self._db or not uid or not session_id:
            return False
        doc_data = dict(data)
        doc_data.update({
            "id": session_id,
            "session_id": session_id,
            "uid": uid,
            "updated_at": doc_data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        })
        ref = self._user_collection(uid, "mobility_sessions").document(session_id)
        return self._transactional_fresh_set(ref, doc_data, freshness_field="last_updated")

    def get_mobility_sessions(self, uid: str, *, active_only: bool = False) -> List[Dict[str, Any]]:
        """Return a user's cloud sessions, newest first, optionally still active."""
        if not self._db or not uid:
            return []
        try:
            records = [doc.to_dict() or {} for doc in self._user_collection(uid, "mobility_sessions").stream()]
            if active_only:
                records = [record for record in records if record.get("status") in {"ACTIVE", "PAUSED", "RESUMED"}]
            return sorted(records, key=lambda record: str(record.get("last_updated", "")), reverse=True)
        except Exception as e:
            logger.error("Error fetching mobility sessions for uid %s: %s", uid, e)
            return []

    def get_active_mobility_session(self, uid: str) -> Optional[Dict[str, Any]]:
        """Get the latest active mobility session for context-event continuity."""
        sessions = self.get_mobility_sessions(uid, active_only=True)
        return sessions[0] if sessions else None

    def save_semantic_context(self, uid: str, context_id: str, data: Dict[str, Any]) -> bool:
        """Persist one PARKED/DWELLING/IN_SHOP context under its owning user.

        ``data`` is the primitive dictionary emitted by
        ``SemanticContext.to_dict``.  It contains no model-only values and is
        therefore safe for Firestore and the mobile sync boundary.
        """
        if not self._db or not uid or not context_id:
            return False
        doc_data = dict(data)
        doc_data.update({
            "id": context_id,
            "context_id": context_id,
            "uid": uid,
            "updated_at": doc_data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        })
        ref = self._user_collection(uid, "semantic_contexts").document(context_id)
        return self._transactional_fresh_set(ref, doc_data, freshness_field="last_observed_at")

    def get_semantic_contexts(self, uid: str, *, active_only: bool = True) -> List[Dict[str, Any]]:
        """Load a user's semantic contexts for policy evaluation in Cloud Run."""
        if not self._db or not uid:
            return []
        try:
            records = [doc.to_dict() or {} for doc in self._user_collection(uid, "semantic_contexts").stream()]
            if active_only:
                records = [record for record in records if record.get("active", True)]
            return sorted(records, key=lambda record: str(record.get("last_observed_at", "")), reverse=True)
        except Exception as e:
            logger.error("Error fetching semantic contexts for uid %s: %s", uid, e)
            return []

    def _user_collection(self, uid: str, name: str):
        """Resolve a uid-isolated subcollection; kept private to prevent path drift."""
        return self._db.collection("users").document(uid).collection(name)

    def save_context_memory(self, uid: str, event_id: str, data: Dict[str, Any]) -> bool:
        """Durable, retry-safe observations; nearby candidates are never visits."""
        if not self._db or not uid or not event_id:
            return False
        import hashlib
        doc_id = hashlib.sha256(event_id.encode()).hexdigest()
        record = {**data, "uid": uid, "event_id": event_id, "schema_version": 1}
        from ..backend.context_history import utc_time
        observed = datetime.fromisoformat(str(record["timestamp"]).replace("Z", "+00:00"))
        record["timestamp"] = utc_time(observed if observed.tzinfo else observed.replace(tzinfo=timezone.utc)).isoformat(timespec="microseconds")
        ref = self._user_collection(uid, "context_memory").document(doc_id)
        return self._transactional_fresh_set(ref, record, freshness_field="timestamp")

    def get_context_memory(self, uid: str, limit: int = 30) -> List[Dict[str, Any]]:
        if not self._db or not uid:
            return []
        try:
            query = self._user_collection(uid, "context_memory")
            if hasattr(query, "order_by"):
                query = query.order_by("timestamp", direction="DESCENDING").limit(min(limit, 100))
            records = [doc.to_dict() or {} for doc in query.stream()]
            return sorted(records, key=lambda item: str(item.get("timestamp", "")), reverse=True)[:limit]
        except Exception as exc:
            logger.error("Context memory read failed: %s", exc)
            return []

    def query_context_memory(self, uid: str, start: datetime, end: datetime, limit: int = 5000) -> tuple[list[dict], bool]:
        """Read an actual time window, not merely the newest N events."""
        if not self._db or not uid:
            raise RuntimeError("Firebase context history is unavailable")
        query = self._user_collection(uid, "context_memory")
        if hasattr(query, "where"):
            from google.cloud.firestore_v1.base_query import FieldFilter
            # A one-second margin accommodates legacy ISO timestamp formatting.
            query = query.where(filter=FieldFilter("timestamp", ">=", (start - timedelta(seconds=1)).isoformat()))
            query = query.where(filter=FieldFilter("timestamp", "<=", (end + timedelta(seconds=1)).isoformat()))
            query = query.order_by("timestamp").limit(limit + 1)
        from ..backend.context_history import utc_time
        records = []
        raw_count = 0
        for doc in query.stream():
            raw_count += 1
            record = doc.to_dict() or {}
            try:
                at = utc_time(record["timestamp"])
            except (KeyError, ValueError, TypeError):
                continue
            if start <= at <= end:
                records.append(record)
        records.sort(key=lambda item: utc_time(item["timestamp"]))
        return records[:limit], len(records) > limit or raw_count >= limit + 1

    def commit_reminder_notification(self, uid: str, reminder: dict, notification: dict) -> tuple[dict, bool, dict]:
        """Atomically complete the reminder and queue one durable cloud alert."""
        import hashlib
        key = f"{uid}:{reminder['id']}:{'once' if reminder.get('one_shot', True) else notification['event_id']}"
        notification_id = hashlib.sha256(key.encode()).hexdigest()
        outbox = self._user_collection(uid, "notifications").document(notification_id)
        reminder_ref = self._db.collection("reminders").document(reminder["id"])
        def commit(tx=None):
            existing = outbox.get(transaction=tx) if tx else outbox.get()
            saved = reminder_ref.get(transaction=tx) if tx else reminder_ref.get()
            current = saved.to_dict() if saved.exists else {}
            if existing.exists:
                return existing.to_dict(), False, current
            if current.get("uid") != uid or current.get("status", "ACTIVE") != "ACTIVE":
                return {}, False, current
            def value(record, key):
                item = record.get(key)
                return None if item == "" else item
            if any(value(current, key) != value(reminder, key) for key in
                   ("activity", "due_at", "latitude", "longitude", "location_name")):
                return {}, False, current
            now = datetime.now(timezone.utc).isoformat()
            record = {**notification, "id": notification_id, "uid": uid, "status": "PENDING", "created_at": now}
            patch = {"last_fired_at": notification["payload"]["occurred_at"], "updated_at": now}
            if current.get("one_shot", True):
                patch["status"] = "COMPLETED"
            if tx:
                tx.set(outbox, record)
                tx.set(reminder_ref, patch, merge=True)
            else:
                outbox.set(record)
                reminder_ref.set(patch, merge=True)
            return record, True, {**current, **patch}
        if hasattr(self._db, "transaction"):
            return firestore.transactional(commit)(self._db.transaction())
        return commit()  # In-memory test clients only.

    def get_notifications(self, uid: str, status: str | None = None) -> list[dict]:
        query = self._user_collection(uid, "notifications")
        if hasattr(query, "order_by"):
            query = query.order_by("created_at", direction="DESCENDING").limit(100)
        records = [doc.to_dict() or {} for doc in query.stream()]
        return [r for r in records if status is None or r.get("status") == status]

    def acknowledge_cloud_notification(self, uid: str, notification_id: str) -> dict | None:
        ref = self._user_collection(uid, "notifications").document(notification_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        patch = {"status": "DELIVERED", "delivered_at": datetime.now(timezone.utc).isoformat()}
        ref.set(patch, merge=True)
        return {**snapshot.to_dict(), **patch}

    def _transactional_fresh_set(self, ref: Any, data: Dict[str, Any], *, freshness_field: str) -> bool:
        """Atomically write a newer context/session snapshot when the SDK supports it.

        A duplicate event is a successful no-op.  A stale event is also ignored
        successfully: callers can safely retry network deliveries without
        resurrecting a departed shop visit or an earlier mobility state.
        """
        def should_write(existing: Dict[str, Any] | None) -> bool:
            if not existing:
                return True
            incoming_at = str(data.get(freshness_field) or "")
            existing_at = str(existing.get(freshness_field) or "")
            if incoming_at and existing_at and incoming_at < existing_at:
                return False
            if incoming_at and existing_at and incoming_at == existing_at:
                # Same source event is idempotent.  Different events at an
                # identical timestamp are conservatively left to the first
                # committed writer, avoiding a non-deterministic overwrite.
                return data.get("last_event_id") != existing.get("last_event_id") and not existing.get("last_event_id")
            return True

        # Real Firestore supplies a transactional decorator that retries on
        # contention.  Keep the ordinary-set fallback only for unavailable
        # transactions/test clients; production Cloud Run takes this branch.
        if firestore is not None and hasattr(firestore, "transactional") and hasattr(self._db, "transaction"):
            try:
                transaction = self._db.transaction()

                @firestore.transactional
                def write_if_fresh(active_transaction):
                    snapshot = ref.get(transaction=active_transaction)
                    existing = snapshot.to_dict() if getattr(snapshot, "exists", False) else None
                    if not should_write(existing):
                        return True
                    payload = dict(data)
                    payload["version"] = int((existing or {}).get("version", 0)) + 1
                    active_transaction.set(ref, payload, merge=True)
                    return True

                return bool(write_if_fresh(transaction))
            except Exception as e:
                # Do not fall back after a real transaction failure: its commit
                # outcome may be unknown and a second write could regress state.
                logger.error("Transactional Firestore context write failed: %s", e)
                return False

        try:
            snapshot = ref.get() if hasattr(ref, "get") else None
            existing = snapshot.to_dict() if snapshot and getattr(snapshot, "exists", True) else None
            if not should_write(existing):
                return True
            payload = dict(data)
            payload["version"] = int((existing or {}).get("version", 0)) + 1
            ref.set(payload, merge=True)
            return True
        except Exception as e:
            logger.error("Firestore context write failed: %s", e)
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
