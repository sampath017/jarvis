package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.location.Location
import android.os.SystemClock
import org.json.JSONObject

/** Bounded, private, durable evidence. No interpolation or reuse across boots. */
class TelemetryHistory private constructor(context: Context) : SQLiteOpenHelper(context,
    "jarvis_telemetry_history.db", null, 1) {
    companion object {
        @Volatile private var instance: TelemetryHistory? = null
        fun get(context: Context): TelemetryHistory = instance ?: synchronized(this) {
            instance ?: TelemetryHistory(context.applicationContext).also { instance = it }
        }
        private const val RETENTION_MS = 86_400_000L
    }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE fixes (boot INTEGER, elapsed INTEGER, at INTEGER, data TEXT, PRIMARY KEY(boot,elapsed))")
        db.execSQL("CREATE TABLE diagnostics (id TEXT PRIMARY KEY, elapsed INTEGER, boot INTEGER, data TEXT, uploaded INTEGER DEFAULT 0)")
        db.execSQL("CREATE INDEX diagnostics_pending ON diagnostics(uploaded,elapsed)")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {}
    private var lastPrune = -60_000L

    @Synchronized fun remember(context: Context, location: Location) {
        if (!location.hasAccuracy() || location.accuracy > 250f || location.accuracy < 0f) return
        val elapsed = location.elapsedRealtimeNanos / 1_000_000
        if (SystemClock.elapsedRealtime() - elapsed !in 0..RETENTION_MS) return
        val gps = JSONObject().apply {
            put("latitude", location.latitude); put("longitude", location.longitude)
            put("accuracy_m", location.accuracy.toDouble())
            put("timestamp", ContextEventQueue.occurredAt(location.time))
            if (location.hasSpeed()) put("speed_mps", location.speed.toDouble())
        }
        writableDatabase.insertWithOnConflict("fixes", null, ContentValues().apply {
            put("boot", EventTiming.boot(context)); put("elapsed", elapsed)
            put("at", location.time); put("data", gps.toString())
        }, SQLiteDatabase.CONFLICT_REPLACE)
        prune(context)
    }

    @Synchronized fun nearest(context: Context, event: JSONObject): JSONObject? {
        val timing = event.optJSONObject("telemetry_diagnostics")
        val currentBoot = EventTiming.boot(context)
        val boot = timing?.optInt("boot_count", -1) ?: -1
        if (boot < 0 || boot != currentBoot || !timing!!.has("observed_elapsed_ms")) return null
        val elapsed = timing.getLong("observed_elapsed_ms")
        return readableDatabase.rawQuery("SELECT data FROM fixes WHERE boot=? AND elapsed BETWEEN ? AND ? ORDER BY ABS(elapsed-?) LIMIT 1",
            arrayOf(boot.toString(), (elapsed-120_000).toString(), (elapsed+120_000).toString(), elapsed.toString())).use {
            if (it.moveToFirst()) JSONObject(it.getString(0)) else null
        }
    }

    fun speed(context: Context): Double? {
        val event = JSONObject(); EventTiming.mark(context, event)
        return nearest(context, event)?.let { if (it.has("speed_mps")) it.getDouble("speed_mps") else null }
    }

    @Synchronized fun record(context: Context, data: JSONObject) {
        writableDatabase.insertWithOnConflict("diagnostics", null, ContentValues().apply {
            put("id", data.getString("id")); put("elapsed", SystemClock.elapsedRealtime())
            put("boot", EventTiming.boot(context)); put("data", data.toString())
        }, SQLiteDatabase.CONFLICT_IGNORE)
        prune(context)
    }
    @Synchronized fun pending(): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT data FROM diagnostics WHERE uploaded=0 ORDER BY boot,elapsed LIMIT 48", null).use {
        buildList { while (it.moveToNext()) add(JSONObject(it.getString(0))) }
    }
    @Synchronized fun export(context: Context): JSONObject {
        prune(context)
        val records = readableDatabase.rawQuery("SELECT data FROM diagnostics ORDER BY boot,elapsed", null).use {
            org.json.JSONArray().apply { while (it.moveToNext()) put(JSONObject(it.getString(0))) }
        }
        return JSONObject().put("records", records).put("monitoring", ActivityRecognitionRegistrar.isEnabled(context))
    }
    @Synchronized fun acknowledge(ids: List<String>) {
        ids.forEach { writableDatabase.update("diagnostics", ContentValues().apply { put("uploaded", 1) }, "id=?", arrayOf(it)) }
    }
    private fun prune(context: Context) {
        val now = SystemClock.elapsedRealtime()
        if (now-lastPrune < 60_000) return
        lastPrune = now
        val boot = EventTiming.boot(context).toString()
        val oldest = (SystemClock.elapsedRealtime()-RETENTION_MS).toString()
        writableDatabase.delete("fixes", "boot!=? OR elapsed<?", arrayOf(boot, oldest))
        writableDatabase.delete("diagnostics", "boot!=? OR elapsed<?", arrayOf(boot, oldest))
        // Bound rows as well as time, even if external providers deliver rapidly.
        writableDatabase.execSQL("DELETE FROM fixes WHERE rowid NOT IN (SELECT rowid FROM fixes ORDER BY elapsed DESC LIMIT 12000)")
        writableDatabase.execSQL("DELETE FROM diagnostics WHERE rowid NOT IN (SELECT rowid FROM diagnostics ORDER BY elapsed DESC LIMIT 6000)")
    }
}
