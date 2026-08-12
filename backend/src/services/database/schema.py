"""
SQLite Database Schema and DDL definitions for Jarvis.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    due_date TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    context_place TEXT DEFAULT '',
    trigger_place TEXT DEFAULT '',
    trigger_category TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    title TEXT DEFAULT '',
    content TEXT NOT NULL,
    place TEXT DEFAULT '',
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    google_place_id TEXT,
    name TEXT NOT NULL,
    user_label TEXT,
    category TEXT DEFAULT '',
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    notes TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (uid, key)
);

CREATE TABLE IF NOT EXISTS mobility_sessions (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    status TEXT NOT NULL,
    vehicle_class TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    started_at TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    paused_at TEXT,
    completed_at TEXT,
    parking_lat REAL,
    parking_lon REAL,
    parking_accuracy_m REAL,
    classification_confidence REAL DEFAULT 0.0,
    resume_count INTEGER DEFAULT 0,
    events_json TEXT DEFAULT '[]',
    poi_visits_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_events (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    activity TEXT DEFAULT '',
    transition TEXT DEFAULT 'ENTER',
    gps_lat REAL,
    gps_lon REAL,
    gps_accuracy_m REAL,
    gps_speed_mps REAL,
    gps_bearing_deg REAL,
    feature_summary_json TEXT,
    session_id TEXT,
    classification_confidence REAL DEFAULT 0.0,
    vehicle_class_hint TEXT DEFAULT '',
    nearby_pois_json TEXT DEFAULT '[]',
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    title TEXT DEFAULT 'New chat',
    last_message_preview TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    run_id TEXT,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES chat_threads(id)
);

CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    name TEXT DEFAULT '',
    trigger_type TEXT DEFAULT '',
    action_type TEXT DEFAULT '',
    config_json TEXT DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    due_at TEXT,
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    radius_m REAL DEFAULT 100.0,
    activity TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    one_shot INTEGER NOT NULL DEFAULT 1,
    last_fired_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_rules (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_json TEXT NOT NULL DEFAULT '{}',
    action_type TEXT NOT NULL,
    action_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    one_shot INTEGER NOT NULL DEFAULT 0,
    last_fired_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_trigger_state (
    uid TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    is_inside INTEGER NOT NULL DEFAULT 0,
    last_event_id TEXT,
    last_seen_at TEXT,
    PRIMARY KEY (uid, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    reminder_id TEXT,
    context_rule_id TEXT,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    trigger_type TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PENDING',
    payload_json TEXT NOT NULL DEFAULT '{}',
    delivered_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (uid, reminder_id, context_rule_id, event_id)
);

CREATE TABLE IF NOT EXISTS audit_entries (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_id TEXT,
    node_name TEXT NOT NULL,
    action TEXT NOT NULL,
    category TEXT DEFAULT 'SYSTEM',
    input_summary TEXT,
    output_summary TEXT,
    gps_lat REAL,
    gps_lon REAL,
    model_id TEXT,
    confidence REAL,
    tokens_used INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0.0,
    execution_result TEXT DEFAULT 'success',
    error_detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_uid ON tasks(uid);
CREATE INDEX IF NOT EXISTS idx_notes_uid ON notes(uid);
CREATE INDEX IF NOT EXISTS idx_places_uid ON places(uid);
CREATE INDEX IF NOT EXISTS idx_preferences_uid ON preferences(uid);
CREATE INDEX IF NOT EXISTS idx_sessions_uid_status ON mobility_sessions(uid, status);
CREATE INDEX IF NOT EXISTS idx_events_uid ON context_events(uid);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_uid ON audit_entries(uid);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_entries(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_node ON audit_entries(node_name);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_entries(created_at);
CREATE INDEX IF NOT EXISTS idx_reminders_uid_status ON reminders(uid, status);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at);
CREATE INDEX IF NOT EXISTS idx_context_rules_uid_enabled ON context_rules(uid, enabled);
CREATE INDEX IF NOT EXISTS idx_notifications_uid_status ON notifications(uid, status, created_at);
"""
