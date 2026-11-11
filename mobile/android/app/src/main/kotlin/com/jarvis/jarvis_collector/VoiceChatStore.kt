package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Voice shares the phone database, with its own thread and timestamped messages. */
object VoiceChatStore {
    fun prefs(c:Context)=c.getSharedPreferences("jarvis_voice",Context.MODE_PRIVATE)
    fun thread(c:Context):String {
        val p=prefs(c);return p.getString("thread",null) ?: ("voice_"+UUID.randomUUID()).also {check(p.edit().putString("thread",it).commit())}
    }
    fun newThread(c:Context):String=("voice_"+UUID.randomUUID()).also {check(prefs(c).edit().putString("thread",it).commit())}
    private fun <T> db(c:Context,body:(SQLiteDatabase)->T):T {
        val file=c.getDatabasePath("jarvis_mobile.db");check(file.exists()) {"Open Jarvis once before starting voice mode."}
        return SQLiteDatabase.openDatabase(file.path,null,SQLiteDatabase.OPEN_READWRITE).use {db->
            db.rawQuery("PRAGMA busy_timeout=10000",null).use {it.moveToFirst()};body(db)
        }
    }
    fun history(c:Context,thread:String):JSONArray=db(c) {db->
        val rows=JSONArray();db.rawQuery("SELECT id,role,content,timestamp FROM chat_messages WHERE thread_id=? ORDER BY julianday(timestamp),CASE WHEN role='user' THEN 0 ELSE 1 END,id",arrayOf(thread)).use {r->while(r.moveToNext())rows.put(JSONObject().put("id",r.getString(0)).put("role",r.getString(1)).put("content",r.getString(2)).put("timestamp",r.getString(3)))};rows
    }
    fun message(c:Context,thread:String,id:String,role:String,text:String)=db(c) {db->
        val at=ContextEventQueue.occurredAt();db.beginTransaction()
        try {
            db.execSQL("INSERT INTO chat_sessions(id,title,created_at,updated_at,sync_status) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated_at=excluded.updated_at",arrayOf(thread,"Voice · "+java.time.LocalDate.now().toString(),at,at,"pending"))
            db.insertWithOnConflict("chat_messages",null,ContentValues().apply {put("id",id);put("thread_id",thread);put("role",role);put("content",text);put("timestamp",at);put("sync_status","pending")},SQLiteDatabase.CONFLICT_IGNORE)
            db.setTransactionSuccessful()
        } finally {db.endTransaction()}
    }
    fun readTool(c:Context,tool:String,args:JSONObject):JSONObject=db(c) {db->
        val table=when {
            tool.contains("note") -> "notes"
            tool.contains("reminder") -> "reminders"
            tool in setOf("list_saved_places","save_place","delete_place","check_saved_geofences","check_user_geofences","inspect_satellite_view") -> "places"
            else -> null
        }
        if(table==null) {
            if(tool in setOf("list_tasks","update_task","update_task_status","delete_task"))
                return@db JSONObject().put("agent",JSONObject().put("domain",JSONObject().put("tasks",MobileSqlStorage.domainRows(db,"tasks"))))
            require(tool in setOf("get_current_context","get_motion_evidence","get_monitoring_status","preview_reminder_match")) {"This phone tool requires Jarvis open; its records were not read in voice mode."}
            return@db MobileRecords.context(c,JSONObject())
        }
        val id=args.optString(when(table){"notes"->"note_id";"reminders"->"reminder_id";else->"place_id"})
        val where=mutableListOf<String>();val values=mutableListOf<String>()
        if(id.isNotBlank()) {where.add("id=?");values.add(id)}
        val ids=args.optJSONArray("note_ids")
        if(ids!=null) {require(ids.length() in 1..50);where.add("id IN ("+List(ids.length()){"?"}.joinToString(",")+")");for(i in 0 until ids.length())values.add(ids.getString(i))}
        if(tool=="create_note") {where.add("deleted_at IS NULL AND lower(trim(title))=lower(?)");values.add(args.optString("title"))}
        if(tool=="create_reminder") {where.add("status='ACTIVE' AND lower(title)=lower(?)");values.add(args.optString("title"))}
        val query=args.optString("query").ifBlank {args.optString("criteria")}
        if(query.isNotBlank()) {val fields=when(table){"notes"->listOf("title","content");"reminders"->listOf("title","body");else->listOf("name","address")};where.add("("+fields.joinToString(" OR "){"lower($it) LIKE ?"}+")");fields.forEach{values.add("%"+query.lowercase()+"%")}}
        val limit=args.optInt("limit",100).coerceIn(1,1000)
        val out=JSONArray();db.rawQuery("SELECT * FROM $table"+(if(where.isEmpty())"" else " WHERE "+where.joinToString(" AND "))+" ORDER BY updated_at DESC LIMIT ?",(values+limit.toString()).toTypedArray()).use {r->
            while(r.moveToNext()) out.put(JSONObject().apply {for(i in 0 until r.columnCount)put(r.getColumnName(i),when(r.getType(i)){0->JSONObject.NULL;1->r.getLong(i);2->r.getDouble(i);else->r.getString(i)})})
        }
        val records=JSONObject().put(table,out)
        if(tool=="create_reminder") {
            val places=JSONArray();val name=args.optString("journey_origin").ifBlank {args.optString("location_name")}
            if(name.isNotBlank()) db.rawQuery("SELECT * FROM places WHERE lower(name)=lower(?) LIMIT 10",arrayOf(name)).use {r->while(r.moveToNext()) places.put(JSONObject().apply{for(i in 0 until r.columnCount)put(r.getColumnName(i),when(r.getType(i)){0->JSONObject.NULL;1->r.getLong(i);2->r.getDouble(i);else->r.getString(i)})})}
            records.put("places",places)
        }
        JSONObject().put("records",records)
    }
}
