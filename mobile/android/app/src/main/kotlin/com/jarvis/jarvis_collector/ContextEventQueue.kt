package com.jarvis.jarvis_collector

import android.content.Context
import android.os.Build
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OutOfQuotaPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.TimeUnit

/** Disk-backed handoff between Play Services broadcasts and short-lived workers. */
object ContextEventQueue {
    private const val PREFS = "jarvis_context_events"
    private const val EVENTS = "events"
    private const val ACTIVITY = "current_activity"
    private const val FLUSH = "jarvis_context_flush"
    private const val PERIODIC = "jarvis_context_periodic"
    private const val CAPTURE = "jarvis_context_location"
    private const val DWELL = "jarvis_context_dwell"

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun occurredAt(time: Long = System.currentTimeMillis()): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date(time))

    fun newEvent(type: String, activity: String, transition: String, time: Long = System.currentTimeMillis()): JSONObject =
        JSONObject().apply {
            put("event_id", "evt_${UUID.randomUUID()}")
            put("event_type", type)
            put("activity", activity)
            put("transition", transition)
            put("occurred_at", occurredAt(time))
            put("timestamp", occurredAt(time))
        }

    @Synchronized
    fun add(context: Context, event: JSONObject, deferCapture: Boolean = false) {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        if (!event.has("location")) event.put("location_pending", true)
        entries.put(event)
        check(prefs(context).edit().putString(EVENTS, entries.toString()).commit())
        if (event.optBoolean("location_pending")) {
            if (!deferCapture) scheduleLocationCapture(context)
        } else scheduleFlush(context)
    }

    @Synchronized
    fun update(context: Context, event: JSONObject) {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        for (index in 0 until entries.length()) {
            if (entries.getJSONObject(index).optString("event_id") == event.optString("event_id")) {
                entries.put(index, event)
                check(prefs(context).edit().putString(EVENTS, entries.toString()).commit())
                return
            }
        }
    }

    fun scheduleLocationCapture(context: Context, delaySeconds: Long = 0) {
        val builder = OneTimeWorkRequestBuilder<ContextLocationWorker>()
        if (Build.VERSION.SDK_INT >= 31 && delaySeconds == 0L) {
            builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
        }
        if (delaySeconds > 0) builder.setInitialDelay(delaySeconds, TimeUnit.SECONDS)
        val request = builder.build()
        // No network constraint: an offline transition still needs its location.
        // Append so a new event cannot cancel a fix already in progress.
        WorkManager.getInstance(context).enqueueUniqueWork(CAPTURE, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    @Synchronized
    fun pending(context: Context): List<JSONObject> {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        return (0 until entries.length()).map { entries.getJSONObject(it) }
    }

    @Synchronized
    fun acknowledge(context: Context, id: String) {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        val remaining = JSONArray()
        for (index in 0 until entries.length()) {
            val event = entries.getJSONObject(index)
            if (event.optString("event_id") != id) remaining.put(event)
        }
        check(prefs(context).edit().putString(EVENTS, remaining.toString()).commit())
    }

    fun currentActivity(context: Context): String = prefs(context).getString(ACTIVITY, "") ?: ""

    fun historyResetAt(context: Context): Long = prefs(context).getLong("history_reset_at", 0L)

    fun setCurrentActivity(context: Context, activity: String) {
        check(prefs(context).edit().putString(ACTIVITY, activity).commit())
    }

    fun scheduleFlush(context: Context) {
        val request = OneTimeWorkRequestBuilder<ContextUploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        // Serialize uploads so a new transition cannot cancel an in-flight request.
        WorkManager.getInstance(context).enqueueUniqueWork(FLUSH, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    fun schedulePeriodic(context: Context) {
        val request = PeriodicWorkRequestBuilder<ContextUploadWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun scheduleDwell(context: Context, activity: String) {
        val request = OneTimeWorkRequestBuilder<ContextUploadWorker>()
            .setInputData(workDataOf("dwell_activity" to activity))
            .setInitialDelay(100, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(DWELL, ExistingWorkPolicy.REPLACE, request)
    }

    fun stopMonitoring(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        WorkManager.getInstance(context).cancelUniqueWork(DWELL)
        setCurrentActivity(context, "")
    }
}
