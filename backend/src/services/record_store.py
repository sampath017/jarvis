"""Domain repositories backed directly by SQLite entity tables."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import threading
from zoneinfo import ZoneInfo
from .chat_message_time import message_stamp
from .sqlite_store import SqlStore

logger = logging.getLogger(__name__)
try:
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30))


def clean(row):
    return {key: value for key, value in row.items() if key != "_key"} if row else row


class RecordStore:
    """Android owns durable data; API operations use their RAM SQL workspace."""
    _instance = None
    _instance_lock = threading.RLock()

    def __new__(cls):
        from .mobile_scope import current
        scope = current.get()
        if scope is None:
            if cls._instance is not None:
                return cls._instance  # Explicit isolated-test injection only.
            raise RuntimeError("Android request context is required; server persistence is disabled")
        if scope.record_store is None:
            instance = super().__new__(cls)
            instance._init_db()
            scope.record_store = instance
        return scope.record_store

    def _init_db(self):
        self._db = SqlStore()

    @classmethod
    def from_sql(cls, store):
        """Explicit handle for isolated repository tests."""
        instance = object.__new__(cls)
        instance._db = store
        return instance

    @property
    def sql(self):
        return self._db

    @property
    def is_available(self):
        return self._db is not None

    def _save(self, table, identifier, data):
        if not self._db:
            return False
        try:
            previous = self._db.get(table, identifier)
            uid = data.get("uid") or (previous or {}).get("uid") or "jarvis_local_user"
            self._db.put(table, identifier, {**data, "id": identifier,
                "updated_at": data.get("updated_at") or datetime.now(timezone.utc).isoformat()}, uid=uid)
            return True
        except Exception:
            logger.exception("SQLite %s write failed", table)
            return False

    def _list(self, table, uid=None, **kwargs):
        return [clean(row) for row in self._db.list(table, uid=uid, **kwargs)] if self._db else []

    def _delete(self, table, identifier):
        if not self._db:
            return False
        try:
            self._db.delete(table, identifier)
            return True
        except Exception:
            logger.exception("SQLite %s deletion failed", table)
            return False

    def save_reminder(self, reminder_id, data):
        return self._save("reminders", reminder_id, data)

    def get_reminders(self, uid=None):
        return self._list("reminders", uid)

    def delete_reminder(self, reminder_id):
        return self._delete("reminders", reminder_id)

    def save_note(self, note_id, data):
        return self._save("notes", note_id, data)

    def get_notes(self, uid=None):
        return self._list("notes", uid)

    def delete_note(self, note_id):
        return self._delete("notes", note_id)

    def save_place(self, place_id, data):
        return self._save("places", place_id, data)

    def get_places(self, uid=None):
        return self._list("places", uid)

    def delete_place(self, place_id):
        return self._delete("places", place_id)

    def _fresh_put(self, table, uid, identifier, data, freshness_field, history_kind=None):
        if not self._db or not uid or not identifier:
            return False
        try:
            with self._db.atomic():
                existing = self._db.get(table, identifier, uid=uid)
                incoming = str(data.get(freshness_field) or "")
                previous = str((existing or {}).get(freshness_field) or "")
                if existing and incoming and previous and incoming <= previous:
                    return True
                payload = {**data, "uid": uid, "id": identifier,
                           "version": int((existing or {}).get("version", 0)) + 1}
                self._db.put(table, identifier, payload, uid=uid)
                self._invalidate_history(payload, history_kind)
            return True
        except Exception:
            logger.exception("SQLite context write failed")
            return False

    def save_mobility_session(self, uid, session_id, data):
        return self._fresh_put("mobility_sessions", uid, session_id,
            {**data, "session_id": session_id, "schema_version": 1}, "last_updated", "mobility")

    def get_mobility_sessions(self, uid, *, active_only=False):
        filters = [("status", "in", ["ACTIVE", "PAUSED", "RESUMED"])] if active_only else []
        return self._list("mobility_sessions", uid, filters=filters, order_by=[("last_updated", "DESC")])

    def get_active_mobility_session(self, uid):
        rows = self.get_mobility_sessions(uid, active_only=True)
        return rows[0] if rows else None

    def save_semantic_context(self, uid, context_id, data):
        return self._fresh_put("semantic_contexts", uid, context_id,
            {**data, "context_id": context_id, "schema_version": 1}, "last_observed_at")

    def get_semantic_contexts(self, uid, *, active_only=True):
        return self._list("semantic_contexts", uid, filters=[("active", "==", True)] if active_only else [],
                          order_by=[("last_observed_at", "DESC")])

    def save_context_memory(self, uid, event_id, data):
        from ..backend.context_history import utc_time
        observed = datetime.fromisoformat(str(data["timestamp"]).replace("Z", "+00:00"))
        timestamp = utc_time(observed if observed.tzinfo else observed.replace(tzinfo=timezone.utc)).isoformat(timespec="microseconds")
        return self._fresh_put("context_memory", uid, hashlib.sha256(event_id.encode()).hexdigest(),
            {**data, "timestamp": timestamp, "event_id": event_id, "schema_version": 1}, "timestamp", "context")

    def _invalidate_history(self, data, kind):
        if not kind or not data.get("uid"):
            return
        uid = data["uid"]
        value = clean(self._db.get("activity_cache_state", "revision", uid=uid)) or {}
        if kind == "mobility":
            value["mobility"] = int(value.get("mobility") or 0) + 1
        else:
            from ..backend.context_history import utc_time
            day = utc_time(data["timestamp"]).astimezone(IST_TZ).date().isoformat()
            days = dict(value.get("days") or {})
            days[day] = int(days.get(day, 0)) + 1
            value["days"] = days
        self._db.put("activity_cache_state", "revision", value, uid=uid)

    def history_revision(self, uid, start, end):
        from ..backend.context_history import utc_time
        value = self._db.get("activity_cache_state", "revision", uid=uid)
        if not value:
            return None
        day = (utc_time(start) - timedelta(days=2)).astimezone(IST_TZ).date()
        last = (utc_time(end) - timedelta(microseconds=1)).astimezone(IST_TZ).date()
        values = []
        while day <= last:
            values.append((day.isoformat(), (value.get("days") or {}).get(day.isoformat(), 0)))
            day += timedelta(days=1)
        return value.get("mobility", 0), tuple(values)

    def save_activity_analysis(self, uid, analysis, through):
        from ..backend.context_history import utc_time
        now = datetime.now(timezone.utc).isoformat()
        recent = sorted((row for row in analysis["activity_sessions"] if utc_time(row["last_updated"]) >= through - timedelta(days=2)), key=lambda row: row["last_updated"], reverse=True)[:50]
        profile = {**analysis["routine_learning"], "through": through.isoformat(), "computed_at": now,
                   "current_session_ids": [row["session_id"] for row in recent]}
        with self._db.atomic():
            previous = self._db.get("activity_routines", "current", uid=uid) or {}
            if previous.get("through") and utc_time(previous["through"]) > through:
                return
            self._db.put("activity_routines", "current", profile, uid=uid, merge=False)
            for row in recent:
                self._db.put("activity_sessions", row["session_id"], {**row, "through": through.isoformat(), "computed_at": now}, uid=uid, merge=False)

    def get_activity_routines(self, uid):
        return clean(self._db.get("activity_routines", "current", uid=uid)) or {}

    def get_context_memory(self, uid, limit=30):
        return self._list("context_memory", uid, order_by=[("timestamp", "DESC")], limit=min(limit, 100))

    def query_context_memory(self, uid, start, end, limit=5000, *, recent_first=False):
        from ..backend.context_history import utc_time
        rows = self._list("context_memory", uid, filters=[("timestamp", ">=", (start - timedelta(seconds=1)).isoformat()),
            ("timestamp", "<=", (end + timedelta(seconds=1)).isoformat())],
            order_by=[("timestamp", "DESC" if recent_first else "ASC")], limit=limit + 1)
        records = [row for row in rows if start <= utc_time(row["timestamp"]) <= end]
        records.sort(key=lambda row: utc_time(row["timestamp"]))
        return records[-limit:] if recent_first else records[:limit], len(rows) >= limit + 1

    def commit_reminder_notification(self, uid, reminder, notification):
        key = f"{uid}:{reminder['id']}:{'once' if reminder.get('one_shot', True) else notification['event_id']}"
        notification_id = hashlib.sha256(key.encode()).hexdigest()
        with self._db.atomic():
            existing = self._db.get("notifications", notification_id, uid=uid)
            saved = self._db.get("reminders", reminder["id"], uid=uid) or {}
            if existing:
                return clean(existing), False, clean(saved)
            if not saved or saved.get("status", "ACTIVE") != "ACTIVE":
                return {}, False, clean(saved)
            for field in ("activity", "due_at", "latitude", "longitude", "location_name", "activity_delay_seconds", "delivery_mode"):
                default = 0 if field == "activity_delay_seconds" else "notification" if field == "delivery_mode" else None
                if (saved.get(field) or default) != (reminder.get(field) or default):
                    return {}, False, clean(saved)
            now = datetime.now(timezone.utc).isoformat()
            value = {**notification, "id": notification_id, "uid": uid, "status": "PENDING", "created_at": now}
            self._db.create("notifications", notification_id, value, uid=uid)
            patch = {"last_fired_at": notification["payload"]["occurred_at"], "updated_at": now}
            if saved.get("one_shot", True):
                patch["status"] = "COMPLETED"
            saved = self._db.put("reminders", reminder["id"], patch, uid=uid)
            return value, True, clean(saved)

    def get_notifications(self, uid, status=None):
        return self._list("notifications", uid, filters=[("status", "==", status)] if status else [],
                          order_by=[("created_at", "DESC")], limit=100)

    def acknowledge_cloud_notification(self, uid, notification_id):
        if not self._db.get("notifications", notification_id, uid=uid):
            return None
        return clean(self._db.put("notifications", notification_id,
            {"status": "DELIVERED", "delivered_at": datetime.now(timezone.utc).isoformat()}, uid=uid))

    def save_chat_session(self, session_id, data):
        return self._save("chat_threads", session_id, data)

    def get_chat_sessions(self, uid=None):
        return self._list("chat_threads", uid)

    def save_chat_message(self, uid, thread_id, message):
        identifier = message.get("id") or message.get("message_id") or str(datetime.now().timestamp())
        data = {**message, "id": identifier, "uid": uid, "thread_id": thread_id,
                "role": message.get("role", "user"), "content": message.get("content", ""),
                "timestamp": message_stamp(message.get("timestamp") or datetime.now(timezone.utc),
                    message_id=identifier, role=message.get("role", "user"))}
        return self._save("chat_messages", identifier, data)

    def get_chat_messages(self, uid=None, thread_id=None, *, valid_threads=None):
        if thread_id is None and valid_threads is None:
            valid_threads = {row["id"] for row in self.get_chat_sessions(uid)}
        if thread_id is None and not valid_threads:
            return []
        rows = self._list("chat_messages", uid, filters=[("thread_id", "==", thread_id)] if thread_id else [],
                          order_by=[("timestamp", "ASC")])
        return [row for row in rows if valid_threads is None or row.get("thread_id") in valid_threads]

    def cleanup_orphaned_messages(self):
        sessions = {(row["uid"], row["id"]) for row in self.get_chat_sessions()}
        count = 0
        for row in self._list("chat_messages"):
            if (row["uid"], row["thread_id"]) not in sessions:
                self._db.delete("chat_messages", row["id"], uid=row["uid"])
                count += 1
        return count

    def delete_chat_session(self, session_id):
        with self._db.atomic():
            session = self._db.get("chat_threads", session_id)
            if not session:
                return True
            for row in self._list("chat_messages", session["uid"], filters=[("thread_id", "==", session_id)]):
                self._db.delete("chat_messages", row["id"], uid=session["uid"])
            return self._delete("chat_threads", session_id)

    def _delete_all(self, table, uid):
        with self._db.atomic():
            for row in self._list(table, uid):
                self._db.delete(table, row["id"], uid=row.get("uid"))
        return True

    def delete_all_chat_sessions(self, uid=None):
        with self._db.atomic():
            self._delete_all("chat_messages", uid)
            return self._delete_all("chat_threads", uid)

    def delete_all_reminders(self, uid=None):
        return self._delete_all("reminders", uid)

    def delete_all_notes(self, uid=None):
        return self._delete_all("notes", uid)
