package com.jarvis.jarvis_collector

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.work.*
import org.json.JSONObject
import java.time.LocalDate
import java.util.concurrent.TimeUnit

/** Full daily app summaries, shared by the overview, chat and background collector. */
class UsageHistory private constructor(context: Context) : SQLiteOpenHelper(
    context, "jarvis_usage_history.db", null, 1
) {
    companion object {
        @Volatile private var instance: UsageHistory? = null
        fun get(context: Context): UsageHistory = instance ?: synchronized(this) {
            instance ?: UsageHistory(context.applicationContext).also { instance = it }
        }
        fun schedule(context: Context) {
            val work = PeriodicWorkRequestBuilder<UsageHistoryWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "jarvis_usage_history", ExistingPeriodicWorkPolicy.KEEP, work)
        }
    }

    init { setWriteAheadLoggingEnabled(true) }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE days (day TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at INTEGER NOT NULL)")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {}

    fun day(day: LocalDate): JSONObject? = readableDatabase.rawQuery(
        "SELECT data FROM days WHERE day=?", arrayOf(day.toString())
    ).use { if (it.moveToFirst()) JSONObject(it.getString(0)) else null }

    fun all(): JSONObject {
        val today = LocalDate.now(UsageReporting.zone)
        return readableDatabase.rawQuery("SELECT day,data FROM days WHERE day>=? AND day<=? ORDER BY day DESC",
            arrayOf(today.minusDays(29).toString(), today.toString())).use {
            JSONObject().apply { while (it.moveToNext()) put(it.getString(0), JSONObject(it.getString(1))) }
        }
    }

    @Synchronized fun save(day: LocalDate, data: JSONObject) {
        // A temporary permission/provider failure must never erase recorded usage.
        val previous = this.day(day)
        if (data.has("error") && (data.optString("error") != "no_records" || previous?.has("total_ms") == true)) return
        // Chat and the background worker can finish out of order for the same day.
        if (!data.has("error") && previous != null && previous.optInt("calculation_version") == data.optInt("calculation_version") &&
            previous.optLong("end_ms") > data.optLong("end_ms")) return
        writableDatabase.insertWithOnConflict("days", null, ContentValues().apply {
            put("day", day.toString()); put("data", data.toString())
            put("fetched_at", System.currentTimeMillis())
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    private val refreshLock = Any()
    fun refresh(context: Context, updated: (String, JSONObject) -> Unit = { _, _ -> }): JSONObject = synchronized(refreshLock) {
        val result = all()
        if (!JarvisPower.enabled(context)) return@synchronized result
        val today = LocalDate.now(UsageReporting.zone)
        if (!UsageReporting.allowed(context)) {
            if (!result.has(today.toString())) result.put(today.toString(), JSONObject().put("error", "usage_access_required"))
            return@synchronized result
        }
        // Import existing 11 PM reports, including days whose raw events have expired.
        for (offset in 0L..29L) {
            val date = today.minusDays(offset)
            if (day(date) == null) UsageReporting.saved(context, date.toString())?.let {
                val data = JSONObject(it)
                save(date, data)
                result.put(date.toString(), data)
                updated(date.toString(), data)
            }
        }
        // Android only retains recent raw events. Completed summaries are never rescanned.
        for (offset in 0L..6L) {
            if (!JarvisPower.enabled(context)) break
            val date = today.minusDays(offset)
            val saved = day(date)
            val fetchedAt = readableDatabase.rawQuery("SELECT fetched_at FROM days WHERE day=?",
                arrayOf(date.toString())).use { if (it.moveToFirst()) it.getLong(0) else 0L }
            val end = date.plusDays(1).atStartOfDay(UsageReporting.zone).toInstant().toEpochMilli()
            if (!UsageCachePolicy.shouldRefresh(date, today, saved?.optInt("calculation_version") ?: 0,
                    saved?.optLong("end_ms") ?: 0L, end, saved?.has("error") == true,
                    fetchedAt, System.currentTimeMillis())) continue
            val data = UsageReporting.read(context, date)
            save(date, data)
            val effective = day(date) ?: data
            result.put(date.toString(), effective)
            updated(date.toString(), effective)
        }
        writableDatabase.delete("days", "day<?", arrayOf(today.minusDays(29).toString()))
        result
    }
}

class UsageHistoryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = try {
        UsageHistory.get(applicationContext).refresh(applicationContext)
        Result.success()
    } catch (_: Exception) { Result.retry() }
}
