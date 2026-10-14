"""Direct SQLite entity tables and atomic transactions.

There are no collection paths, document references, snapshots or query builders.
Scalar fields live in named SQL columns; nested values use JSON columns.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid


class AlreadyExists(ValueError):
    pass


class NotFound(KeyError):
    pass


def encode(value):
    if isinstance(value, datetime):
        return {"__jarvis_datetime__": value.isoformat()}
    raise TypeError(f"Unsupported SQLite JSON value: {type(value).__name__}")


def decode(value):
    if set(value) == {"__jarvis_datetime__"}:
        return datetime.fromisoformat(value["__jarvis_datetime__"])
    return value


def dumps(value):
    return json.dumps(value, default=encode, ensure_ascii=False, sort_keys=True)


def loads(value):
    return json.loads(value, object_hook=decode)


# These are entity-specific scalar fields, not a path/key/payload record table.
STATE_COLUMNS = {
    "mobility_sessions": "session_id TEXT,status TEXT,vehicle_class TEXT,last_updated TEXT,started_at TEXT,paused_at TEXT,completed_at TEXT,classification_confidence REAL",
    "dynamic_reminder_state": "payload TEXT NOT NULL DEFAULT '{}'",
    "semantic_contexts": "state TEXT,active INTEGER,confidence REAL,last_observed_at TEXT,updated_at TEXT,context_id TEXT,mobility_session_id TEXT",
    "context_memory": "timestamp TEXT,activity TEXT,transition TEXT,event_id TEXT,event_type TEXT,source TEXT,mobility_session_id TEXT",
    "activity_routines": "through TEXT,computed_at TEXT",
    "activity_sessions": "session_id TEXT,status TEXT,activity TEXT,started_at TEXT,last_updated TEXT,through TEXT,computed_at TEXT",
    "activity_cache_state": "mobility INTEGER DEFAULT 0",
    "context_processing_errors": "event_id TEXT,status TEXT,timestamp TEXT,created_at TEXT,updated_at TEXT",
    "context_requests": "request_id TEXT,status TEXT,created_at TEXT,expires_at TEXT,received_at TEXT,location_status TEXT,event_id TEXT",
    "context_identity": "fingerprint_salt TEXT,created_at TEXT",
    "motion_diagnostics": "timestamp TEXT,source TEXT,candidate TEXT,provisional INTEGER,model_version TEXT,event_id TEXT",
    "ai_usage": "day TEXT,call_count INTEGER DEFAULT 0,estimated_tokens INTEGER DEFAULT 0,cost_nanos INTEGER DEFAULT 0,updated_at TEXT",
    "runtime_control": "enabled INTEGER,cloud_ready INTEGER,updated_at TEXT,transition TEXT",
    "command_runs": "request_id TEXT,thread_id TEXT,status TEXT,fingerprint TEXT,cancel_requested INTEGER,started_at TEXT,updated_at TEXT,expires_at TEXT,message TEXT,sequence INTEGER,calendar_key_hash TEXT,calendar_result_id TEXT",
    "command_control": "request_id TEXT,until TEXT",
    "file_memories": "name TEXT,mimeType TEXT,size INTEGER,url TEXT,storage TEXT,created_at TEXT,updated_at TEXT,modifiedTime TEXT",
    "file_analyses": "fingerprint TEXT,status TEXT,created_at TEXT,updated_at TEXT",

}
NATIVE_TABLES = frozenset({"notes", "reminders", "places", "tasks", "preferences",
    "automations", "context_rules", "context_events", "mobility_sessions", "chat_threads",
    "chat_messages", "notifications", "audit_entries", "dynamic_reminder_state", "context_trigger_state"})
TABLES = NATIVE_TABLES | STATE_COLUMNS.keys()
JSON_FIELDS = {
    "mobility_sessions": {"events": "events_json", "poi_visits": "poi_visits_json"},
    "context_events": {"feature_summary": "feature_summary_json", "nearby_pois": "nearby_pois_json"},
    "context_rules": {"trigger": "trigger_json", "action": "action_json"},
    "notifications": {"payload": "payload_json"},
    "automations": {"config": "config_json"},
}


def table_name(table):
    if table not in TABLES:
        raise ValueError(f"Unknown SQLite entity: {table}")
    return table


def physical_table(table):
    """Keep derived state separate from normalized domain SQL rows."""
    table = table_name(table)
    return "state_" + table if table in STATE_COLUMNS else table


class SqlStore:
    def __init__(self, path=None):
        from .mobile_scope import current
        self.scope = current.get() if path is None else None
        self.lock = self.scope.lock if self.scope else threading.RLock()
        self.path = ":memory:" if self.scope else str(path) if path is not None else None
        if self.scope:
            self.db = self.scope.db
        elif path == ":memory:":
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            if path is None:
                raise RuntimeError("A phone request scope or explicit SQLite path is required")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self):
        with self.lock:
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='sql_store_meta'").fetchone():
                ready = self.db.execute("SELECT value FROM sql_store_meta WHERE key='schema_version'").fetchone()
                if ready:
                    return
            from .database.schema import SCHEMA_SQL
            self.db.executescript(SCHEMA_SQL)
            for table, fields in STATE_COLUMNS.items():
                self.db.execute(f'CREATE TABLE IF NOT EXISTS "{physical_table(table)}" (uid TEXT NOT NULL,id TEXT NOT NULL,{fields},extra_json TEXT NOT NULL DEFAULT \'{{}}\',PRIMARY KEY(uid,id))')
            for table in TABLES:
                physical = physical_table(table)
                columns = {row["name"] for row in self.db.execute(f'PRAGMA table_info("{physical}")')}
                if "extra_json" not in columns:
                    self.db.execute(f'ALTER TABLE "{physical}" ADD COLUMN extra_json TEXT NOT NULL DEFAULT \'{{}}\'')
                if "uid" in columns:
                    self.db.execute(f'CREATE INDEX IF NOT EXISTS "idx_sql_{table}_uid" ON "{physical}"(uid)')
                for field in ("timestamp", "status", "updated_at", "last_observed_at", "execute_at"):
                    if "uid" in columns and field in columns:
                        self.db.execute(f'CREATE INDEX IF NOT EXISTS "idx_sql_{table}_{field}" ON "{physical}"(uid,"{field}")')
            self.db.execute("CREATE TABLE IF NOT EXISTS sql_store_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            self.db.commit()
            self.db.execute("INSERT OR REPLACE INTO sql_store_meta VALUES('schema_version','1')")
            self.db.commit()

    @contextmanager
    def connection(self):
        with self.lock:
            if self.scope and self.scope.closed:
                raise RuntimeError("Mobile operation has finished")
            yield self.db

    @contextmanager
    def atomic(self):
        with self.connection() as db:
            nested = db.in_transaction
            savepoint = "sql_" + uuid.uuid4().hex
            db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                if nested:
                    db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    db.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    db.rollback()
                raise
            else:
                db.execute(f"RELEASE SAVEPOINT {savepoint}") if nested else db.commit()

    def _columns(self, table):
        return {row["name"]: dict(row) for row in self.db.execute(f'PRAGMA table_info("{physical_table(table)}")')}

    def _key_column(self, table):
        return "id"

    def _record(self, table, row):
        if row is None:
            return None
        data = dict(row)
        extras = loads(data.pop("extra_json", "{}") or "{}")
        datetimes = extras.pop("__sql_datetime_fields__", [])
        key = data.get(self._key_column(table))
        data.update(extras)
        data["_key"] = key
        data["id"] = key
        for name, column in JSON_FIELDS.get(table, {}).items():
            raw = data.pop(column, None)
            if raw is not None:
                data[name] = loads(raw) if isinstance(raw, str) else raw
        if table == "dynamic_reminder_state":
            payload = loads(data.pop("payload", "{}"))
            return {**payload, "uid": data["uid"], "id": key, "_key": key}
        if table == "mobility_sessions":
            data["session_id"] = key
            if data.get("parking_lat") is not None:
                data["parking_gps"] = {"latitude": data.pop("parking_lat"), "longitude": data.pop("parking_lon"), "accuracy_m": data.pop("parking_accuracy_m")}
        if table == "context_events":
            if data.get("gps_lat") is not None:
                data["gps"] = {"latitude": data.pop("gps_lat"), "longitude": data.pop("gps_lon"), "accuracy_m": data.pop("gps_accuracy_m"), "speed_mps": data.pop("gps_speed_mps"), "bearing_deg": data.pop("gps_bearing_deg")}
        for field in datetimes:
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        for field in ("active", "enabled", "connected", "cloud_ready", "cancel_requested", "deleted", "one_shot", "provisional"):
            if field in data and data[field] is not None:
                data[field] = bool(data[field])
        return data

    def get(self, table, identifier, *, uid=None):
        table = table_name(table)
        with self.connection() as db:
            where = f'"{self._key_column(table)}"=?'
            args = [str(identifier)]
            if uid is not None:
                where += " AND uid=?"
                args.append(str(uid))
            rows = db.execute(f'SELECT * FROM "{physical_table(table)}" WHERE {where} LIMIT 2', args).fetchall()
            if len(rows) > 1:
                raise ValueError("Owner is required for an ambiguous SQLite entity key")
            return self._record(table, rows[0]) if rows else None

    def put(self, table, identifier, data, *, uid=None, merge=True):
        table = table_name(table)
        identifier = str(identifier)
        incoming = dict(data)
        incoming.pop("_key", None)
        if incoming.get("id") is not None and str(incoming["id"]) != identifier:
            raise ValueError("Entity id must match its SQL key")
        owner = str(uid if uid is not None else incoming.get("uid", ""))
        with self.atomic():
            previous = self.get(table, identifier, uid=owner)
            if table in NATIVE_TABLES and table not in STATE_COLUMNS and previous is None:
                other = self.get(table, identifier)
                if other and str(other.get("uid", "")) != owner:
                    raise ValueError("Record belongs to another user")
            value = {**(previous or {}), **incoming} if merge else incoming
            value.pop("_key", None)
            value["uid"] = owner
            columns = self._columns(table)
            key_column = self._key_column(table)
            values = {key_column: identifier, "uid": owner}
            extras = {}
            value.pop("id", None)
            if table == "dynamic_reminder_state":
                values["payload"] = dumps({k: v for k, v in value.items() if k not in {"uid", "reminder_id"}})
            else:
                for name, column in JSON_FIELDS.get(table, {}).items():
                    if name in value and column in columns:
                        values[column] = dumps(value.pop(name))
                for nested, prefix in (("parking_gps", "parking"), ("gps", "gps")):
                    if nested in value and isinstance(value[nested], dict) and f"{prefix}_lat" in columns:
                        point = value.pop(nested)
                        mapping = {"latitude": "lat", "longitude": "lon", "accuracy_m": "accuracy_m", "speed_mps": "speed_mps", "bearing_deg": "bearing_deg"}
                        for source, suffix in mapping.items():
                            if f"{prefix}_{suffix}" in columns:
                                values[f"{prefix}_{suffix}"] = point.get(source)
                if table == "notes" and "content" not in value and "text" in value:
                    value["content"] = value["text"]
                for field, item in value.items():
                    if field in {"uid", "session_id"} and (field == "uid" or table == "mobility_sessions"):
                        continue
                    if field in columns and field != "extra_json":
                        if isinstance(item, datetime):
                            values[field] = item.isoformat()
                            extras.setdefault("__sql_datetime_fields__", []).append(field)
                        elif isinstance(item, (dict, list)):
                            values[field] = dumps(item)
                        else:
                            values[field] = item
                    else:
                        extras[field] = item
            now = datetime.now(timezone.utc).isoformat()
            for name, info in columns.items():
                if name in values or name == "extra_json" or info["dflt_value"] is not None or not info["notnull"]:
                    continue
                if name in {"created_at", "updated_at", "timestamp", "started_at", "last_updated"}:
                    values[name] = now
                elif info["type"] in {"INTEGER", "REAL"}:
                    values[name] = 0
                else:
                    values[name] = ""
            if previous is not None and not merge:
                # Replacement is a full row replacement, including indexed
                # nullable scalars. Updating only supplied columns would leave
                # stale status/times behind after the JSON extras were cleared.
                for name, info in columns.items():
                    if name in values or name == "extra_json" or info["pk"]:
                        continue
                    default = info["dflt_value"]
                    values[name] = self.db.execute("SELECT " + default).fetchone()[0] if default is not None else None
            values["extra_json"] = dumps(extras)
            names = list(values)
            quoted = ",".join(f'"{name}"' for name in names)
            db = self.db
            if previous is None:
                db.execute(f'INSERT INTO "{physical_table(table)}" ({quoted}) VALUES ({",".join("?" for _ in names)})', [values[name] for name in names])
            else:
                fields = [name for name in names if name not in {key_column, "uid"}]
                db.execute(f'UPDATE "{physical_table(table)}" SET {",".join(chr(34)+name+chr(34)+"=?" for name in fields)} WHERE "{key_column}"=? AND uid=?', [values[name] for name in fields] + [identifier, owner])
            return self.get(table, identifier, uid=owner)

    def create(self, table, identifier, data, *, uid=None):
        owner = uid if uid is not None else data.get("uid", "")
        with self.atomic():
            if self.get(table, identifier, uid=owner) is not None:
                raise AlreadyExists(str(identifier))
            return self.put(table, identifier, data, uid=owner, merge=False)

    def delete(self, table, identifier, *, uid=None):
        table = table_name(table)
        with self.atomic():
            row = self.get(table, identifier, uid=uid)
            if row is None:
                return False
            self.db.execute(f'DELETE FROM "{physical_table(table)}" WHERE "{self._key_column(table)}"=? AND uid=?', (str(identifier), row.get("uid", "")))
            return True

    def _field(self, table, field, args):
        if field == "_key":
            field = self._key_column(table)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", field):
            raise ValueError("Invalid SQLite field")
        if field in self._columns(table):
            return f'"{field}"'
        args.append("$." + field)
        return "json_extract(extra_json,?)"

    def list(self, table, *, uid=None, filters=(), order_by=(), limit=None, after_id=None):
        table = table_name(table)
        with self.connection() as db:
            clauses, args = [], []
            if uid is not None:
                clauses.append("uid=?")
                args.append(str(uid))
            for field, operation, value in filters:
                expression = self._field(table, field, args)
                if operation in {"in", "not-in"}:
                    values = list(value)
                    clauses.append(f'{expression} {"IN" if operation == "in" else "NOT IN"} ({",".join("?" for _ in values)})' if values else ("0" if operation == "in" else "1"))
                    args.extend(values)
                elif value is None and operation in {"==", "!=", "="}:
                    clauses.append(f'{expression} IS {"NOT " if operation == "!=" else ""}NULL')
                elif operation in {"==", "=", "!=", "<", "<=", ">", ">="}:
                    clauses.append(f'{expression} {"=" if operation == "==" else operation} ?')
                    args.append(value.isoformat() if isinstance(value, datetime) else value)
                else:
                    raise ValueError("Unsupported SQLite comparison")
            if after_id is not None:
                clauses.append(f'"{self._key_column(table)}">?')
                args.append(str(after_id))
            ordering = []
            for entry in order_by:
                field, direction = (entry, "ASC") if isinstance(entry, str) else entry
                direction = direction.upper().replace("ENDING", "")
                if direction not in {"ASC", "DESC"}:
                    raise ValueError("Invalid SQLite sort direction")
                ordering.append(self._field(table, field, args) + " " + direction)
            sql = f'SELECT * FROM "{physical_table(table)}"' + (" WHERE " + " AND ".join(clauses) if clauses else "")
            if ordering:
                sql += " ORDER BY " + ",".join(ordering)
            if limit is not None:
                sql += " LIMIT ?"
                args.append(max(0, int(limit)))
            return [self._record(table, row) for row in db.execute(sql, args)]

    def export_records(self, *, exclude_tables=()):
        excluded = {table_name(table) for table in exclude_tables}
        records = []
        for table in sorted(STATE_COLUMNS.keys() - excluded):
            for value in self.list(table):
                key = value.pop("_key")
                records.append({"table": table, "id": key, "uid": value.get("uid", ""), "data": value})
        return records

