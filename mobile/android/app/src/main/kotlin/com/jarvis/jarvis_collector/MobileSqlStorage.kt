package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject

/** Fixed SQL entities shared by native background work and the Flutter UI. */
object MobileSqlStorage {
    const val LOCAL_UID = "jarvis_local_user"
    val domainColumns = linkedMapOf(
        "tasks" to "id TEXT,title TEXT,description TEXT,due_date TEXT,priority TEXT,status TEXT,created_at TEXT,updated_at TEXT",
        "preferences" to "id TEXT,key TEXT,value TEXT,source TEXT,created_at TEXT,updated_at TEXT",
        "automations" to "id TEXT,name TEXT,trigger_type TEXT,action_type TEXT,enabled INTEGER,created_at TEXT,updated_at TEXT",
        "context_rules" to "id TEXT,name TEXT,trigger_type TEXT,action_type TEXT,enabled INTEGER,one_shot INTEGER,last_fired_at TEXT,created_at TEXT,updated_at TEXT",
        "context_events" to "id TEXT,activity TEXT,transition TEXT,gps_lat REAL,gps_lon REAL,gps_accuracy_m REAL,timestamp TEXT,session_id TEXT,created_at TEXT",
        "mobility_sessions" to "id TEXT,status TEXT,vehicle_class TEXT,confidence REAL,started_at TEXT,last_updated TEXT,paused_at TEXT,completed_at TEXT,created_at TEXT,updated_at TEXT",
        "dynamic_reminder_state" to "reminder_id TEXT",
        "context_trigger_state" to "source_type TEXT,source_id TEXT,is_inside INTEGER,last_event_id TEXT,last_seen_at TEXT",
    )
    val recordColumns = linkedMapOf(
        "mobility_sessions" to "session_id TEXT,status TEXT,vehicle_class TEXT,last_updated TEXT,started_at TEXT,paused_at TEXT,completed_at TEXT,classification_confidence REAL",
        "dynamic_reminder_state" to "payload TEXT",
        "semantic_contexts" to "state TEXT,active INTEGER,confidence REAL,last_observed_at TEXT,updated_at TEXT,context_id TEXT,mobility_session_id TEXT",
        "context_memory" to "timestamp TEXT,activity TEXT,transition TEXT,event_id TEXT,event_type TEXT,source TEXT,mobility_session_id TEXT",
        "activity_routines" to "through TEXT,computed_at TEXT",
        "activity_sessions" to "session_id TEXT,status TEXT,activity TEXT,started_at TEXT,last_updated TEXT,through TEXT,computed_at TEXT",
        "activity_cache_state" to "mobility INTEGER",
        "context_processing_errors" to "event_id TEXT,status TEXT,timestamp TEXT,created_at TEXT,updated_at TEXT",
        "context_requests" to "request_id TEXT,status TEXT,created_at TEXT,expires_at TEXT,received_at TEXT,location_status TEXT,event_id TEXT",
        "context_identity" to "fingerprint_salt TEXT,created_at TEXT",
        "motion_diagnostics" to "timestamp TEXT,source TEXT,candidate TEXT,provisional INTEGER,model_version TEXT,event_id TEXT",
        "ai_usage" to "day TEXT,call_count INTEGER,estimated_tokens INTEGER,cost_nanos INTEGER,updated_at TEXT",
    )
    fun physical(table: String, domain: Boolean = false): String {
        require((if (domain) domainColumns else recordColumns).containsKey(table)) { "Unsupported SQLite entity: $table" }
        return (if (domain) "domain_" else "record_") + table
    }
    private fun fields(table: String, domain: Boolean = false) =
        (if (domain) domainColumns else recordColumns).getValue(table).split(',').map { it.trim().substringBefore(' ') }

    fun ensure(db: SQLiteDatabase) {
        if (query(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='mobile_schema_meta'").isNotEmpty() &&
            query(db, "SELECT value FROM mobile_schema_meta WHERE key='entity_schema' AND value='1'").isNotEmpty()) return
        db.beginTransaction()
        try {
            for (domain in listOf(false, true)) {
                for ((kind, columns) in if (domain) domainColumns else recordColumns) {
                    val table = physical(kind, domain)
                    db.execSQL("CREATE TABLE IF NOT EXISTS $table (row_key TEXT NOT NULL,uid TEXT NOT NULL,$columns,extra_json TEXT NOT NULL DEFAULT '{}',stored_at INTEGER NOT NULL,PRIMARY KEY(uid,row_key))")
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_${table}_recent ON $table(uid,stored_at)")
                    for (field in fields(kind, domain)) if (field in setOf("timestamp", "status", "last_observed_at", "started_at")) {
                        db.execSQL("CREATE INDEX IF NOT EXISTS idx_${table}_$field ON $table(uid,$field)")
                    }
                }
            }
            db.execSQL("CREATE TABLE IF NOT EXISTS mobile_schema_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execSQL("INSERT OR REPLACE INTO mobile_schema_meta(key,value) VALUES('entity_schema','1')")
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    fun put(db: SQLiteDatabase, kind: String, id: String, data: JSONObject,
            uid: String = LOCAL_UID, domain: Boolean = false, storedAt: Long = System.currentTimeMillis()) {
        require(id.isNotEmpty() && uid.isNotEmpty()) { "SQLite entity requires an ID and owner" }
        val table = physical(kind, domain)
        val extra = JSONObject(data.toString())
        val values = ContentValues().apply { put("row_key", id); put("uid", uid); put("stored_at", storedAt) }
        for (field in fields(kind, domain)) {
            when (val value = data.opt(field)) {
                is String -> {
                    values.put(field, value)
                    if ((if (domain) domainColumns else recordColumns).getValue(kind).split(',').first { it.trim().startsWith("$field ") }.trim().endsWith(" TEXT")) extra.remove(field)
                }
                is Number -> {
                    values.put(field, value.toString())
                    if (value is Byte || value is Short || value is Int || value is Long) {
                        if ((if (domain) domainColumns else recordColumns).getValue(kind).split(',').first { it.trim().startsWith("$field ") }.trim().endsWith(" INTEGER")) extra.remove(field)
                    }
                }
                is Boolean -> values.put(field, if (value) 1 else 0)
                is JSONObject -> if (value.length() == 1 && value.has("__jarvis_datetime__")) values.put(field, value.getString("__jarvis_datetime__"))
            }
        }
        values.put("extra_json", extra.toString())
        val columns = values.keySet().toList()
        val args = arrayOfNulls<Any>(columns.size)
        columns.forEachIndexed { index, column -> args[index] = values.get(column) }
        db.execSQL("INSERT OR REPLACE INTO $table (${columns.joinToString(",")}) VALUES (${columns.joinToString(",") { "?" }})", args)
    }

    private fun decodeRow(kind: String, row: JSONObject, domain: Boolean = false): JSONObject {
        val result = JSONObject()
        for (field in fields(kind, domain)) if (row.has(field) && !row.isNull(field)) result.put(field, row.get(field))
        val extra = JSONObject(row.getString("extra_json"))
        extra.keys().forEach { result.put(it, extra.get(it)) }
        return result
    }
    fun domainRows(db: SQLiteDatabase, kind: String, limit: Int = 100, uid: String = LOCAL_UID): JSONArray = JSONArray().apply {
        for (row in query(db, "SELECT * FROM ${physical(kind, true)} WHERE uid=? ORDER BY stored_at DESC LIMIT ?", arrayOf(uid, limit.toString()))) {
            put(decodeRow(kind, row, true).put("__key", row.getString("row_key")))
        }
    }
    fun records(db: SQLiteDatabase, kind: String, limit: Int = 10000, uid: String = LOCAL_UID): JSONArray = JSONArray().apply {
        for (row in query(db, "SELECT * FROM ${physical(kind)} WHERE uid=? ORDER BY stored_at DESC LIMIT ?", arrayOf(uid, limit.toString()))) {
            put(JSONObject().put("table", kind).put("id", row.getString("row_key")).put("uid", row.getString("uid")).put("data", decodeRow(kind, row)))
        }
    }
    /** Carry continuity for live reminders even when newer unrelated state is present. */
    fun recordsForActiveReminders(db: SQLiteDatabase): JSONArray = JSONArray().apply {
        val kind = "dynamic_reminder_state"
        val sql = "SELECT state.* FROM ${physical(kind)} AS state " +
            "JOIN reminders AS reminder ON state.row_key=reminder.id " +
            "WHERE state.uid=? AND reminder.status='ACTIVE' AND reminder.deleted_at IS NULL " +
            "ORDER BY reminder.id LIMIT 1000"
        for (row in query(db, sql, arrayOf(LOCAL_UID))) {
            put(JSONObject().put("table", kind).put("id", row.getString("row_key"))
                .put("uid", row.getString("uid")).put("data", decodeRow(kind, row)))
        }
    }
    fun remove(db: SQLiteDatabase, kind: String, id: String, uid: String = LOCAL_UID, domain: Boolean = false) {
        db.delete(physical(kind, domain), "uid=? AND row_key=?", arrayOf(uid, id))
    }
    fun query(db: SQLiteDatabase, sql: String, args: Array<String> = emptyArray()): List<JSONObject> =
        db.rawQuery(sql, args).use { cursor -> buildList {
            while (cursor.moveToNext()) add(JSONObject().apply {
                for (index in 0 until cursor.columnCount) put(cursor.getColumnName(index), when (cursor.getType(index)) {
                    0 -> JSONObject.NULL; 1 -> cursor.getLong(index); 2 -> cursor.getDouble(index); else -> cursor.getString(index)
                })
            })
        } }

}
