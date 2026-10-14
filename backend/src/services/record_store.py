"""
Local SQLite record repositories for Jarvis.

Stores API working records in SQLite. Android retains the durable personal
data; a Cloud Run instance may discard its local working database at any time.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from .chat_message_time import message_stamp

try:
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30))

from . import sqlite_documents as documents

logger = logging.getLogger(__name__)


class RecordStore:
    """Local persistence for reminders, notes, places, tasks, and API sync."""

    _instance: Optional[RecordStore] = None

    _instance_lock = threading.RLock()

    def __new__(cls) -> RecordStore:
        from .mobile_scope import current, mobile_only
        scope = current.get()
        if scope is not None:
            if scope.record_store is None:
                instance = super().__new__(cls)
                instance._init_db()
                scope.record_store = instance
            return scope.record_store
        if mobile_only():
            raise RuntimeError('Android request context is required; server persistence is disabled')
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_db()
                cls._instance = instance
            return cls._instance

    def _init_db(self) -> None:
        self._db = documents.Client()
        logger.info("SQLite record storage ready")

    @property
    def is_available(self) -> bool:
        return self._db is not None

    def _owned_records(self, name: str, uid: Optional[str]):
        """Apply ownership in the indexed SQLite query before reading records."""
        query = self._db.collection(name)
        if uid:
            from src.services.sqlite_documents import FieldFilter
            query = query.where(filter=FieldFilter('uid', '==', uid))
        return query

    # ── Reminders ─────────────────────────────────────────────────────────────
    def _save_synced(self, collection: str, record_id: str, data: dict) -> None:
        if hasattr(self._db, 'transaction'):
            from .sync_change_feed import SyncChangeFeed
            SyncChangeFeed(self._db).write(collection, record_id, data)
        else:  # In-memory clients used by existing unit tests.
            self._db.collection(collection).document(record_id).set(data, merge=True)

    def _delete_synced(self, collection: str, record_id: str) -> None:
        if hasattr(self._db, 'transaction'):
            from .sync_change_feed import SyncChangeFeed
            SyncChangeFeed(self._db).write(collection, record_id, delete=True)
        else:
            self._db.collection(collection).document(record_id).delete()

    def save_reminder(self, reminder_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = reminder_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._save_synced('reminders', reminder_id, doc_data)
            logger.info("Saved reminder %s to RecordStore", reminder_id)
            try:
                from .background_tasks import BackgroundTasks
                BackgroundTasks().schedule_reminder(doc_data.get('uid', 'jarvis_local_user'), doc_data)
            except Exception:
                logger.exception('Reminder saved; background scheduling will retry on sweep')
            return True
        except Exception as e:
            logger.error("Error saving reminder to RecordStore: %s", e)
            return False

    def get_reminders(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._owned_records("reminders", uid).stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid:
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching reminders from RecordStore: %s", e)
            return []

    def delete_reminder(self, reminder_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._delete_synced('reminders', reminder_id)
            logger.info("Deleted reminder %s from RecordStore", reminder_id)
            return True
        except Exception as e:
            logger.error("Error deleting reminder from RecordStore: %s", e)
            return False

    # ── Notes ─────────────────────────────────────────────────────────────────
    def save_note(self, note_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = note_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._save_synced('notes', note_id, doc_data)
            logger.info("Saved note %s to RecordStore", note_id)
            return True
        except Exception as e:
            logger.error("Error saving note to RecordStore: %s", e)
            return False

    def get_notes(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._owned_records("notes", uid).stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid:
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching notes from RecordStore: %s", e)
            return []

    def delete_note(self, note_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._delete_synced('notes', note_id)
            logger.info("Deleted note %s from RecordStore", note_id)
            return True
        except Exception as e:
            logger.error("Error deleting note from RecordStore: %s", e)
            return False

    # ── Places ────────────────────────────────────────────────────────────────
    def save_place(self, place_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = place_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._save_synced('places', place_id, doc_data)
            logger.info("Saved place %s to RecordStore", place_id)
            return True
        except Exception as e:
            logger.error("Error saving place to RecordStore: %s", e)
            return False

    def get_places(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._owned_records("places", uid).stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid:
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching places from RecordStore: %s", e)
            return []

    def delete_place(self, place_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._delete_synced('places', place_id)
            logger.info("Deleted place %s from RecordStore", place_id)
            return True
        except Exception as e:
            logger.error("Error deleting place from RecordStore: %s", e)
            return False

    # ── Mobility & semantic contexts ────────────────────────────────────────
    # These documents are deliberately uid-scoped.  Cloud Run instances are
    # ephemeral, so neither an in-process cache nor the local SQLite mirror is
    # authoritative for parked/dwell/shop continuity.
    def save_mobility_session(self, uid: str, session_id: str, data: Dict[str, Any]) -> bool:
        """Upsert a cloud mobility session without allowing an older event to win.

        ``last_updated`` should be an ISO-8601 UTC timestamp supplied by the
        session reducer.  The RecordStore transaction protects concurrent Cloud
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
        return self._transactional_fresh_set(ref, doc_data, freshness_field="last_updated", history_kind='mobility')

    def get_mobility_sessions(self, uid: str, *, active_only: bool = False) -> List[Dict[str, Any]]:
        """Return a user's cloud sessions, newest first, optionally still active."""
        if not self._db or not uid:
            return []
        try:
            query = self._user_collection(uid, "mobility_sessions")
            if active_only and hasattr(query, 'where'):
                from src.services.sqlite_documents import FieldFilter
                query = query.where(filter=FieldFilter('status', 'in', ['ACTIVE', 'PAUSED', 'RESUMED']))
            records = [doc.to_dict() or {} for doc in query.stream()]
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
        therefore safe for RecordStore and the mobile sync boundary.
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
            query = self._user_collection(uid, "semantic_contexts")
            if active_only and hasattr(query, 'where'):
                from src.services.sqlite_documents import FieldFilter
                query = query.where(filter=FieldFilter('active', '==', True))
            records = [doc.to_dict() or {} for doc in query.stream()]
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
        return self._transactional_fresh_set(ref, record, freshness_field="timestamp", history_kind='context')

    def history_revision(self, uid, start, end):
        from ..backend.context_history import utc_time
        data = self._user_collection(uid, 'activity_cache_state').document('revision').get().to_dict()
        if not data:
            return None
        # History also reads a two-day prelude to seed an earlier journey.
        first = (utc_time(start) - timedelta(days=2)).astimezone(IST_TZ).date()
        last = (utc_time(end) - timedelta(microseconds=1)).astimezone(IST_TZ).date()
        days = []
        while first <= last:
            days.append((first.isoformat(), (data.get('days') or {}).get(first.isoformat(), 0)))
            first += timedelta(days=1)
        return data.get('mobility', 0), tuple(days)

    def _invalidate_history(self, data, kind, tx=None):
        if not kind:
            return
        uid = data.get('uid')
        if not uid:
            return
        ref = self._user_collection(uid, 'activity_cache_state').document('revision')
        if tx:
            if kind == 'mobility':
                value = {'mobility': documents.Increment(1)}
            else:
                from ..backend.context_history import utc_time
                day = utc_time(data['timestamp']).astimezone(IST_TZ).date().isoformat()
                value = {'days': {day: documents.Increment(1)}}
            tx.set(ref, value, merge=True)
        # Lightweight non-transactional test clients do not use shared caching.

    def save_activity_analysis(self, uid: str, analysis: dict, through: datetime) -> None:
        """Store derived sessions and routines; raw events stay independently durable."""
        computed_at = datetime.now(timezone.utc).isoformat()
        profile = {**analysis["routine_learning"], "through": through.isoformat(), "computed_at": computed_at}
        from ..backend.context_history import utc_time
        recent = sorted((s for s in analysis["activity_sessions"] if utc_time(s["last_updated"]) >= through - timedelta(days=2)),
                        key=lambda s: s["last_updated"], reverse=True)[:50]
        profile["current_session_ids"] = [s["session_id"] for s in recent]
        ref = self._user_collection(uid, "activity_routines").document("current")
        def commit(tx=None):
            saved = ref.get(transaction=tx) if tx else ref.get()
            previous = saved.to_dict() if saved.exists else {}
            if previous.get("through") and utc_time(previous["through"]) > through:
                return
            if tx:
                tx.set(ref, profile)
            else:
                ref.set(profile)
            for session in recent:
                target = self._user_collection(uid, "activity_sessions").document(session["session_id"])
                value = {**session, "through": through.isoformat(), "computed_at": computed_at}
                if tx:
                    tx.set(target, value)
                else:
                    target.set(value)
        if hasattr(self._db, "transaction"):
            documents.transactional(commit)(self._db.transaction())
        else:
            commit()  # In-memory test clients.

    def get_activity_routines(self, uid: str) -> dict:
        snapshot = self._user_collection(uid, "activity_routines").document("current").get()
        return (snapshot.to_dict() or {}) if snapshot.exists else {}

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

    def query_context_memory(self, uid: str, start: datetime, end: datetime, limit: int = 5000, *, recent_first: bool = False) -> tuple[list[dict], bool]:
        """Read an actual time window, not merely the newest N events."""
        if not self._db or not uid:
            raise RuntimeError("Local context history is unavailable")
        query = self._user_collection(uid, "context_memory")
        if hasattr(query, "where"):
            from src.services.sqlite_documents import FieldFilter
            # A one-second margin accommodates legacy ISO timestamp formatting.
            query = query.where(filter=FieldFilter("timestamp", ">=", (start - timedelta(seconds=1)).isoformat()))
            query = query.where(filter=FieldFilter("timestamp", "<=", (end + timedelta(seconds=1)).isoformat()))
            query = query.order_by("timestamp", direction="DESCENDING" if recent_first else "ASCENDING").limit(limit + 1)
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
        return records[-limit:] if recent_first else records[:limit], len(records) > limit or raw_count >= limit + 1

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
                if key == 'activity_delay_seconds':
                    return int(item or 0)
                if key == 'delivery_mode':
                    return item or 'notification'
                return None if item == "" else item
            if any(value(current, key) != value(reminder, key) for key in
                     ("activity", "due_at", "latitude", "longitude", "location_name", "activity_delay_seconds", "delivery_mode")):
                return {}, False, current
            now = datetime.now(timezone.utc).isoformat()
            record = {**notification, "id": notification_id, "uid": uid, "status": "PENDING", "created_at": now}
            patch = {"last_fired_at": notification["payload"]["occurred_at"], "updated_at": now}
            if current.get("one_shot", True):
                patch["status"] = "COMPLETED"
            if tx:
                from .sync_change_feed import SyncChangeFeed
                SyncChangeFeed(self._db).append(tx, uid, 'reminders', reminder['id'], {**current, **patch})
                tx.set(outbox, record)
                tx.set(reminder_ref, patch, merge=True)
            else:
                outbox.set(record)
                reminder_ref.set(patch, merge=True)
            return record, True, {**current, **patch}
        if hasattr(self._db, "transaction"):
            return documents.transactional(commit)(self._db.transaction())
        return commit()  # In-memory test clients only.

    def get_notifications(self, uid: str, status: str | None = None) -> list[dict]:
        query = self._user_collection(uid, "notifications")
        if status is not None and hasattr(query, "where"):
            from src.services.sqlite_documents import FieldFilter
            # Filter before reading. One equality field needs no new composite
            # index, and old pending alerts cannot be hidden by newer history.
            query = query.where(filter=FieldFilter('status', '==', status)).limit(100)
        elif hasattr(query, "order_by"):
            query = query.order_by("created_at", direction="DESCENDING").limit(100)
        records = [doc.to_dict() or {} for doc in query.stream()]
        records = [r for r in records if status is None or r.get("status") == status]
        return sorted(records, key=lambda r: str(r.get('created_at', '')), reverse=True)

    def acknowledge_cloud_notification(self, uid: str, notification_id: str) -> dict | None:
        ref = self._user_collection(uid, "notifications").document(notification_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        patch = {"status": "DELIVERED", "delivered_at": datetime.now(timezone.utc).isoformat()}
        ref.set(patch, merge=True)
        return {**snapshot.to_dict(), **patch}

    def _transactional_fresh_set(self, ref: Any, data: Dict[str, Any], *, freshness_field: str,
                                 history_kind: str | None = None) -> bool:
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

        # SQLite serializes competing writers in a single transaction.
        # The ordinary-set fallback supports lightweight repository test doubles.
        if documents is not None and hasattr(documents, "transactional") and hasattr(self._db, "transaction"):
            try:
                transaction = self._db.transaction()

                @documents.transactional
                def write_if_fresh(active_transaction):
                    snapshot = ref.get(transaction=active_transaction)
                    existing = snapshot.to_dict() if getattr(snapshot, "exists", False) else None
                    if not should_write(existing):
                        return True
                    payload = dict(data)
                    payload["version"] = int((existing or {}).get("version", 0)) + 1
                    active_transaction.set(ref, payload, merge=True)
                    self._invalidate_history(data, history_kind, active_transaction)
                    return True

                return bool(write_if_fresh(transaction))
            except Exception as e:
                # Do not fall back after a real transaction failure: its commit
                # outcome may be unknown and a second write could regress state.
                logger.error("Transactional RecordStore context write failed: %s", e)
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
            logger.error("RecordStore context write failed: %s", e)
            return False

    # ── Chat Sessions & Messages ─────────────────────────────────────────────
    def save_chat_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        if not self._db:
            return False
        try:
            doc_data = dict(data)
            doc_data["id"] = session_id
            doc_data["updated_at"] = doc_data.get("updated_at") or datetime.now(IST_TZ).isoformat()
            self._save_synced('chat_sessions', session_id, doc_data)
            logger.info("Saved chat session %s to RecordStore", session_id)
            return True
        except Exception as e:
            logger.error("Error saving chat session to RecordStore: %s", e)
            return False

    def get_chat_sessions(self, uid: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            docs = self._owned_records("chat_sessions", uid).stream()
            records = []
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid:
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching chat sessions from RecordStore: %s", e)
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
                "timestamp": message_stamp(
                    message.get('timestamp') or datetime.now(timezone.utc), message_id=msg_id, role=message.get('role', 'user')),
                "run_id": message.get("run_id"),
                "executed_records": message.get("executed_records", []),
            }
            if message.get("duration_ms") is not None:
                doc_data["duration_ms"] = message["duration_ms"]
            self._save_synced('chat_messages', msg_id, doc_data)
            return True
        except Exception as e:
            logger.error("Error saving chat message to RecordStore: %s", e)
            return False

    def get_chat_messages(self, uid: Optional[str] = None, thread_id: Optional[str] = None,
                          *, valid_threads: Optional[set[str]] = None) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        try:
            # Valid session check to prevent returning orphaned messages
            if not thread_id and valid_threads is None:
                valid_threads = {s.id for s in self._owned_records("chat_sessions", uid).stream()}
            if not thread_id and not valid_threads:
                return []

            col = self._owned_records("chat_messages", uid)
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
                if not uid or doc_uid == uid:
                    records.append(data)
            return records
        except Exception as e:
            logger.error("Error fetching chat messages from RecordStore: %s", e)
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
                    self._delete_synced('chat_messages', m.id)
                    deleted += 1
            if deleted > 0:
                logger.info("Cleaned up %d orphaned chat messages from RecordStore", deleted)
            return deleted
        except Exception as e:
            logger.error("Error cleaning up orphaned chat messages from RecordStore: %s", e)
            return 0

    def delete_chat_session(self, session_id: str) -> bool:
        """Delete a chat session and all messages belonging to its thread from RecordStore."""
        if not self._db:
            return False
        try:
            self._delete_synced('chat_sessions', session_id)
            msgs = self._db.collection("chat_messages").where("thread_id", "==", session_id).stream()
            for m in msgs:
                self._delete_synced('chat_messages', m.id)
            # Also clean up any lingering orphaned messages
            self.cleanup_orphaned_messages()
            logger.info("Deleted chat session %s and all associated messages from RecordStore", session_id)
            return True
        except Exception as e:
            logger.error("Error deleting chat session %s from RecordStore: %s", session_id, e)
            return False

    def delete_all_chat_sessions(self, uid: Optional[str] = None) -> bool:
        """Delete all chat sessions and messages for the user from RecordStore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("chat_sessions").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    self._delete_synced('chat_sessions', d.id)
            msgs = self._db.collection("chat_messages").stream()
            for m in msgs:
                data = m.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    self._delete_synced('chat_messages', m.id)
            logger.info("Deleted all chat sessions and messages for uid %s from RecordStore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all chat sessions from RecordStore: %s", e)
            return False

    def delete_all_reminders(self, uid: Optional[str] = None) -> bool:
        """Delete all reminders for the user from RecordStore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("reminders").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    self._delete_synced('reminders', d.id)
            logger.info("Deleted all reminders for uid %s from RecordStore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all reminders from RecordStore: %s", e)
            return False

    def delete_all_notes(self, uid: Optional[str] = None) -> bool:
        """Delete all notes for the user from RecordStore."""
        if not self._db:
            return False
        try:
            docs = self._db.collection("notes").stream()
            for d in docs:
                data = d.to_dict()
                doc_uid = data.get("uid")
                if not uid or doc_uid == uid or doc_uid in ("jarvis_local_user", "poco_x4_pro_user", None):
                    self._delete_synced('notes', d.id)
            logger.info("Deleted all notes for uid %s from RecordStore", uid)
            return True
        except Exception as e:
            logger.error("Error deleting all notes from RecordStore: %s", e)
            return False


    # ── Mobile Bulk Sync ──────────────────────────────────────────────────────
    def process_sync_push(self, uid: str, pending_records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[str]]:
        """Process local mobile SQLite pending items pushed to RecordStore."""
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
        """Pull all remote RecordStore records for user to reconcile with local mobile SQLite."""
        sessions = self.get_chat_sessions(uid)
        valid_threads = {s['id'] for s in sessions if s.get('id')}
        return {
            "reminders": self.get_reminders(uid),
            "notes": self.get_notes(uid),
            "places": self.get_places(uid),
            "chat_sessions": sessions,
            "chat_messages": self.get_chat_messages(uid, valid_threads=valid_threads),
        }
