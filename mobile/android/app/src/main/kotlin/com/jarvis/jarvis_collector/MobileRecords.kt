package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.OffsetDateTime

/** The worker and Flutter share one WAL database; no server copy is required. */
object MobileRecords {
    private fun open(context: Context): SQLiteDatabase {
        val file = context.getDatabasePath("jarvis_mobile.db")
        check(file.exists()) { "Open Jarvis once to initialize local storage" }
        val db = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE)
        try {
            // This assignment returns a row on Android; execSQL rejects it as a query.
            db.rawQuery("PRAGMA busy_timeout=10000", null).use { cursor ->
                check(cursor.moveToFirst() && cursor.getInt(0) == 10000) {
                    "Could not configure the local database busy timeout"
                }
            }
            db.execSQL("CREATE TABLE IF NOT EXISTS mobile_notifications(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            db.execSQL("CREATE TABLE IF NOT EXISTS mobile_usage(day TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)")
            db.execSQL("CREATE TABLE IF NOT EXISTS mobile_receipts(operation_id TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)")
            MobileSqlStorage.ensure(db)
            return db
        } catch (error: Throwable) {
            db.close()
            throw error
        }
    }
    private fun rows(db: SQLiteDatabase, sql: String, args: Array<String> = emptyArray()): JSONArray {
        val result = JSONArray()
        db.rawQuery(sql, args).use { c -> while(c.moveToNext()) {
            val row = JSONObject()
            for(i in 0 until c.columnCount) row.put(c.getColumnName(i), when(c.getType(i)) {
                0 -> JSONObject.NULL; 1 -> c.getLong(i); 2 -> c.getDouble(i); else -> c.getString(i)
            })
            result.put(row)
        }}
        return result
    }
    fun context(context: Context, event: JSONObject): JSONObject = open(context).use { db ->
        // Only active rules, nearby saved places and the latest continuity state.
        val records = JSONObject().put("reminders", rows(db,
            "SELECT * FROM reminders WHERE status='ACTIVE' AND deleted_at IS NULL ORDER BY id LIMIT 1000"))
        val gps = event.optJSONObject("location") ?: event.optJSONObject("gps")
        val places = if(gps != null && gps.has("latitude") && gps.has("longitude")) rows(db,
            "SELECT * FROM places WHERE ABS(latitude-?)<0.1 AND ABS(longitude-?)<0.1 LIMIT 100",
            arrayOf(gps.getDouble("latitude").toString(), gps.getDouble("longitude").toString())) else JSONArray()
        records.put("places", places)
        val recordsState = JSONArray(); val domain = JSONObject()
        for (name in listOf("mobility_sessions", "semantic_contexts", "context_memory", "activity_routines")) {
            val saved = MobileSqlStorage.records(db, name, if (name == "context_memory") 10 else 30)
            for (index in 0 until saved.length()) recordsState.put(saved.getJSONObject(index))
        }
        val reminderState = MobileSqlStorage.recordsForActiveReminders(db)
        for (index in 0 until reminderState.length()) recordsState.put(reminderState.getJSONObject(index))
        for (name in listOf("mobility_sessions", "dynamic_reminder_state", "context_trigger_state", "context_rules", "automations", "context_events")) {
            domain.put(name, MobileSqlStorage.domainRows(db, name, if (name == "context_events") 10 else if (name == "mobility_sessions") 30 else 1000))
        }
        val day=java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
        val budget=rows(db,"SELECT * FROM mobile_usage WHERE day=?",arrayOf(day)).optJSONObject(0) ?: JSONObject().put("day",day)
        JSONObject().put("records",records).put("agent",JSONObject().put("records",recordsState).put("domain",domain)).put("budget",budget)
    }
    fun applied(context:Context,eventId:String):Boolean=open(context).use {db->rows(db,"SELECT operation_id FROM mobile_receipts WHERE operation_id=?",arrayOf("event:$eventId")).length()>0}
    /** Preserve old queued observations as history without replaying live rules or journeys. */
    fun archiveContextEvents(context: Context, events: List<JSONObject>): Int = open(context).use { db ->
        var archived = 0
        db.beginTransaction()
        try {
            for (event in events) {
                val eventId = event.getString("event_id")
                require(eventId.isNotBlank()) { "Context history requires an event ID" }
                val receipt = "event:$eventId"
                if (rows(db, "SELECT operation_id FROM mobile_receipts WHERE operation_id=?", arrayOf(receipt)).length() > 0) continue
                val occurred = event.optString("occurred_at").ifBlank { event.getString("timestamp") }
                val observed = OffsetDateTime.parse(occurred).toInstant()
                val memory = JSONObject(event.toString()).apply {
                    remove("_mobile_state")
                    put("source", "phone_observation")
                    put("uid", "jarvis_local_user")
                    put("schema_version", 1)
                    put("timestamp", observed.toString())
                    put("gps", event.optJSONObject("location") ?: event.optJSONObject("gps") ?: JSONObject.NULL)
                    put("archived_locally", true)
                    put("processing_status", "history_only")
                    // No retrospective journey, place or semantic inference was performed.
                    put("mobility_session_id", JSONObject.NULL)
                    put("nearby_candidates", JSONArray())
                    put("saved_places", JSONArray())
                    put("context_changes", JSONArray())
                    put("contexts", JSONArray())
                }
                // Use the same document identity as server-side context persistence.
                val id = MessageDigest.getInstance("SHA-256").digest(eventId.toByteArray(Charsets.UTF_8))
                    .joinToString("") { "%02x".format(it.toInt() and 255) }
                if (MobileSqlStorage.query(db, "SELECT row_key FROM record_context_memory WHERE uid=? AND row_key=?", arrayOf(MobileSqlStorage.LOCAL_UID, id)).isEmpty()) {
                    MobileSqlStorage.put(db, "context_memory", id, memory, storedAt = observed.toEpochMilli())
                }
                db.insertOrThrow("mobile_receipts", null, ContentValues().apply {
                    put("operation_id", receipt)
                })
                archived++
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        archived
    }
    /** Keep malformed observations losslessly without inventing an observation time. */
    fun archiveInvalidContextEvents(context: Context, events: List<JSONObject>): Int = open(context).use { db ->
        var archived = 0
        db.beginTransaction()
        try {
            for (event in events) {
                val eventId = event.getString("event_id")
                require(eventId.isNotBlank()) { "Context quarantine requires an event ID" }
                val receipt = "event:$eventId"
                if (rows(db, "SELECT operation_id FROM mobile_receipts WHERE operation_id=?", arrayOf(receipt)).length() > 0) continue
                val id = MessageDigest.getInstance("SHA-256").digest(eventId.toByteArray(Charsets.UTF_8))
                    .joinToString("") { "%02x".format(it.toInt() and 255) }
                val payload = JSONObject().put("event_id", eventId).put("uid", "jarvis_local_user")
                    .put("source", "phone_context_quarantine").put("schema_version", 1)
                    .put("reason", "invalid_observation_time").put("original_payload", JSONObject(event.toString()))
                // Zero is a storage-order sentinel, never a fabricated observation timestamp.
                if (MobileSqlStorage.query(db, "SELECT row_key FROM record_context_processing_errors WHERE uid=? AND row_key=?", arrayOf(MobileSqlStorage.LOCAL_UID, id)).isEmpty()) {
                    MobileSqlStorage.put(db, "context_processing_errors", id, payload, storedAt = 0L)
                }
                db.insertOrThrow("mobile_receipts", null, ContentValues().apply { put("operation_id", receipt) })
                archived++
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        archived
    }
    fun apply(context: Context, changes: JSONObject) {
        val suppliedAgent = changes.opt("agent")
        require(suppliedAgent == null || suppliedAgent == JSONObject.NULL || suppliedAgent is JSONObject) {
            "Jarvis returned an unsupported state format; update the API before retrying"
        }
        val agent = changes.optJSONObject("agent") ?: JSONObject()
        require(agent.keys().asSequence().all { it in setOf("domain", "domain_deleted", "records", "removed") }) {
            "Jarvis returned an unsupported state format; update the API before retrying"
        }
        open(context).use { db ->
            db.beginTransaction()
            try {
                for(table in listOf("notes","reminders","places")) {
                    val records=changes.optJSONObject("records")?.optJSONArray(table) ?: JSONArray()
                    val versions=changes.optJSONObject("base_versions")?.optJSONObject(table) ?: JSONObject()
                    val columns=mutableSetOf<String>()
                    db.rawQuery("PRAGMA table_info($table)",null).use { c->while(c.moveToNext())columns.add(c.getString(c.getColumnIndexOrThrow("name"))) }
                    for(i in 0 until records.length()) {
                        val row=records.getJSONObject(i); val id=row.getString("id")
                        val old=rows(db,"SELECT * FROM $table WHERE id=?",arrayOf(id)).optJSONObject(0)
                        if(old!=null && old.opt("updated_at")!=versions.opt(id))continue
                        val data=ContentValues()
                        val merged=old ?: JSONObject()
                        row.keys().forEach { key->merged.put(key,row.opt(key)) }
                        merged.put("sync_status","synced")
                        merged.keys().forEach { key->if(key in columns) {
                            val v=merged.opt(key)
                            when(v) { null,JSONObject.NULL->data.putNull(key); is Number->data.put(key,v.toString()); is Boolean->data.put(key,if(v)1 else 0);else->data.put(key,v.toString()) }
                        }}
                        db.insertWithOnConflict(table,null,data,SQLiteDatabase.CONFLICT_REPLACE)
                    }
                }
                val domain = agent.optJSONObject("domain") ?: JSONObject()
                domain.keys().forEach { name ->
                    val items = domain.getJSONArray(name)
                    for (index in 0 until items.length()) {
                        val value = JSONObject(items.getJSONObject(index).toString())
                        val id = value.getString("__key"); value.remove("__key")
                        MobileSqlStorage.put(db, name, id, value,
                            uid = value.optString("uid", MobileSqlStorage.LOCAL_UID), domain = true)
                    }
                }
                val deleted = agent.optJSONObject("domain_deleted") ?: JSONObject()
                deleted.keys().forEach { name ->
                    val ids = deleted.getJSONArray(name)
                    for (index in 0 until ids.length()) MobileSqlStorage.remove(db, name, ids.getString(index), domain = true)
                }
                val recordsState = agent.optJSONArray("records") ?: JSONArray()
                for (index in 0 until recordsState.length()) {
                    val row = recordsState.getJSONObject(index)
                    MobileSqlStorage.put(db, row.getString("table"), row.getString("id"), row.getJSONObject("data"),
                        uid = row.optString("uid", MobileSqlStorage.LOCAL_UID))
                }
                val removed = agent.optJSONArray("removed") ?: JSONArray()
                for (index in 0 until removed.length()) {
                    val row = removed.getJSONObject(index)
                    MobileSqlStorage.remove(db, row.getString("table"), row.getString("id"),
                        uid = row.optString("uid", MobileSqlStorage.LOCAL_UID))
                }
                val alerts=changes.optJSONArray("notifications") ?: JSONArray()
                for(i in 0 until alerts.length()) {val row=alerts.getJSONObject(i);val id=row.optString("id");if(id.isNotEmpty())db.insertWithOnConflict("mobile_notifications",null,ContentValues().apply {put("id",id);put("payload",row.toString())},SQLiteDatabase.CONFLICT_IGNORE)}
                val receipt=changes.getString("operation_id")
                val old=rows(db,"SELECT * FROM mobile_receipts WHERE operation_id=?",arrayOf(receipt)).optJSONObject(0) ?: JSONObject()
                val usage=changes.optJSONObject("budget") ?: JSONObject()
                val keys=listOf("cost_nanos","call_count","estimated_tokens")
                val delta=keys.map {usage.optLong(it)-old.optLong(it)}
                if(usage.has("day") && delta.all {it>=0})db.execSQL("INSERT INTO mobile_usage(day,cost_nanos,call_count,estimated_tokens) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET cost_nanos=cost_nanos+excluded.cost_nanos,call_count=call_count+excluded.call_count,estimated_tokens=estimated_tokens+excluded.estimated_tokens",arrayOf(usage.getString("day"),delta[0],delta[1],delta[2]))
                if(delta.all {it>=0})db.insertWithOnConflict("mobile_receipts",null,ContentValues().apply {put("operation_id",receipt);keys.forEach {put(it,usage.optLong(it))}},SQLiteDatabase.CONFLICT_REPLACE)
                db.setTransactionSuccessful()
            } finally {db.endTransaction()}
            ReminderAlerts.reconcile(context,rows(db,"SELECT * FROM reminders WHERE deleted_at IS NULL"))
        }
        deliver(context)
    }
    fun deliver(context:Context) = open(context).use { db->
        val alerts=rows(db,"SELECT id,payload FROM mobile_notifications")
        for(i in 0 until alerts.length()) {
            val row=alerts.getJSONObject(i);val n=JSONObject(row.getString("payload"));val payload=n.optJSONObject("payload") ?: JSONObject()
            val shown=PushDelivery.show(context,n.getString("id"),n.optString("title","Jarvis"),n.optString("body"),n.optString("thread_id"),n.optString("kind"),payload.optString("delivery_mode","notification"),n.optString("reminder_id"),payload.optString("alarm_due_at"),payload.optString("occurred_at"))
            if(shown)db.delete("mobile_notifications","id=?",arrayOf(row.getString("id")))
        }
    }
}
