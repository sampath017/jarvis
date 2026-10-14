package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject

/** The worker and Flutter share one WAL database; no server copy is required. */
object MobileRecords {
    private fun open(context: Context): SQLiteDatabase {
        val file = context.getDatabasePath("jarvis_mobile.db")
        check(file.exists()) { "Open Jarvis once to initialize local storage" }
        return SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).apply {
            execSQL("PRAGMA busy_timeout=10000")
            execSQL("CREATE TABLE IF NOT EXISTS mobile_agent_rows(collection TEXT,id TEXT,payload TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(collection,id))")
            execSQL("CREATE TABLE IF NOT EXISTS mobile_notifications(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            execSQL("CREATE TABLE IF NOT EXISTS mobile_usage(day TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)")
            execSQL("CREATE TABLE IF NOT EXISTS mobile_receipts(operation_id TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)")
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
            "SELECT * FROM reminders WHERE status='ACTIVE' AND deleted_at IS NULL LIMIT 1000"))
        val gps = event.optJSONObject("location") ?: event.optJSONObject("gps")
        val places = if(gps != null && gps.has("latitude") && gps.has("longitude")) rows(db,
            "SELECT * FROM places WHERE ABS(latitude-?)<0.1 AND ABS(longitude-?)<0.1 LIMIT 100",
            arrayOf(gps.getDouble("latitude").toString(), gps.getDouble("longitude").toString())) else JSONArray()
        records.put("places", places)
        val docs = JSONArray(); val domain = JSONObject()
        val collections = listOf("mobility_sessions", "semantic_contexts", "context_memory", "activity_routines")
        for(name in collections) {
            val saved = rows(db, "SELECT collection,id,payload FROM mobile_agent_rows WHERE collection=? ORDER BY updated_at DESC LIMIT ?",
                arrayOf("users/jarvis_local_user/$name", if(name=="context_memory") "10" else "30"))
            for(i in 0 until saved.length()) { val row=saved.getJSONObject(i)
                docs.put(JSONObject().put("collection",row.getString("collection")).put("id",row.getString("id"))
                    .put("data",JSONObject(row.getString("payload"))))
            }
        }
        for(name in listOf("mobility_sessions","dynamic_reminder_state","context_trigger_state","context_rules","automations","context_events")) {
            val limit=if(name=="context_events") "10" else if(name=="mobility_sessions") "30" else "1000"
            val saved=rows(db,"SELECT payload FROM mobile_agent_rows WHERE collection=? ORDER BY updated_at DESC LIMIT ?",arrayOf("domain:$name",limit))
            val items=JSONArray(); for(i in 0 until saved.length())items.put(JSONObject(saved.getJSONObject(i).getString("payload")))
            domain.put(name,items)
        }
        val day=java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
        val budget=rows(db,"SELECT * FROM mobile_usage WHERE day=?",arrayOf(day)).optJSONObject(0) ?: JSONObject().put("day",day)
        JSONObject().put("records",records).put("agent",JSONObject().put("documents",docs).put("domain",domain)).put("budget",budget)
    }
    fun applied(context:Context,eventId:String):Boolean=open(context).use {db->rows(db,"SELECT operation_id FROM mobile_receipts WHERE operation_id=?",arrayOf("event:$eventId")).length()>0}
    fun apply(context: Context, changes: JSONObject) {
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
                fun save(collection:String,id:String,value:JSONObject) {
                    val data=ContentValues().apply {put("collection",collection);put("id",id);put("payload",value.toString());put("updated_at",System.currentTimeMillis())}
                    db.insertWithOnConflict("mobile_agent_rows",null,data,SQLiteDatabase.CONFLICT_REPLACE)
                }
                val agent=changes.optJSONObject("agent") ?: JSONObject()
                val domain=agent.optJSONObject("domain") ?: JSONObject()
                domain.keys().forEach { name->val items=domain.getJSONArray(name);for(i in 0 until items.length()) {
                    val row=items.getJSONObject(i);val id=row.getString("__key");row.remove("__key");save("domain:$name",id,row)
                }}
                val deleted=agent.optJSONObject("domain_deleted") ?: JSONObject()
                deleted.keys().forEach { name->val ids=deleted.getJSONArray(name);for(i in 0 until ids.length())db.delete("mobile_agent_rows","collection=? AND id=?",arrayOf("domain:$name",ids.getString(i))) }
                val docs=agent.optJSONArray("documents") ?: JSONArray()
                for(i in 0 until docs.length()) {val row=docs.getJSONObject(i);save(row.getString("collection"),row.getString("id"),row.getJSONObject("data"))}
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
