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
    private const val FLUSH = "jarvis_context_flush_v2"
    private const val KICK = "jarvis_context_kick_v2"
    private const val PERIODIC = "jarvis_context_periodic_v2"
    private const val CAPTURE = "jarvis_context_location"
    private const val DWELL = "jarvis_context_dwell"
    private val migrationRunning = java.util.concurrent.atomic.AtomicBoolean(false)
    private val migrationExecutor = java.util.concurrent.Executors.newSingleThreadExecutor()

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun configureApi(context: Context, baseUrl: String, userId: String) {
        val url = java.net.URI(baseUrl.trim().trimEnd('/'))
        val debug = context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0
        check(url.host != null && url.userInfo == null && url.query == null && url.fragment == null &&
            (url.scheme == "https" || (debug && url.scheme == "http" && url.host in setOf("localhost", "127.0.0.1")))) {
            "A valid HTTPS API URL is required"
        }
        check(userId.isNotBlank() && userId.length <= 256)
        check(prefs(context).edit().putString("api_url", url.toString()).putString("api_user", userId).commit())
        if (JarvisPower.enabled(context)) scheduleFlush(context)
    }

    fun apiUrl(context: Context): String? = prefs(context).getString("api_url", null)
    fun apiUser(context: Context): String = prefs(context).getString("api_user", "poco_x4_pro_user")!!

    private fun migrateUploads(context: Context) {
        val app = context.applicationContext
        if (prefs(app).getInt("upload_scheduler_version", 0) >= 3 ||
            !migrationRunning.compareAndSet(false, true)) return
        migrationExecutor.execute {
            try {
                val manager = WorkManager.getInstance(app)
                for (name in listOf("jarvis_context_flush", "jarvis_context_periodic")) {
                    // Cancel each unfinished root once. cancelUniqueWork would revisit
                    // every named descendant of a long APPEND chain quadratically.
                    val work = manager.getWorkInfosForUniqueWork(name).get(30, TimeUnit.SECONDS)
                    val roots = work.filter { !it.state.isFinished && it.state != androidx.work.WorkInfo.State.BLOCKED }
                    val candidates = if (roots.isEmpty()) work.filter { !it.state.isFinished }.take(1) else roots
                    for (info in candidates) manager.cancelWorkById(info.id).result.get(60, TimeUnit.SECONDS)
                }
                check(prefs(app).edit().putInt("upload_scheduler_version", 3).commit())
            } catch (error: Exception) {
                android.util.Log.w("JarvisContextWorker", "Upload scheduler migration will retry", error)
            } finally {
                migrationRunning.set(false)
            }
        }
    }

    fun retryAt(context: Context): Long = prefs(context).getLong("upload_retry_at", 0)
    fun recordUploadFailure(context: Context, reason: String): Long {
        val p = prefs(context)
        val attempt = p.getInt("upload_failures", 0)
        val delay = ContextUploadPolicy.retryDelayMillis(attempt)
        check(p.edit().putInt("upload_failures", minOf(attempt + 1, 20))
            .putLong("upload_retry_at", System.currentTimeMillis() + delay)
            .putString("upload_error", reason.take(240)).commit())
        return delay
    }

    fun recordUploadSuccess(context: Context) {
        check(prefs(context).edit().putInt("upload_failures", 0).remove("upload_retry_at")
            .remove("upload_error").putLong("upload_success_at", System.currentTimeMillis()).commit())
    }

    fun uploadStatus(context: Context): Map<String, Any?> = mapOf(
        "pending" to pending(context).size, "lastSuccess" to prefs(context).getLong("upload_success_at", 0),
        "retryAt" to retryAt(context), "error" to prefs(context).getString("upload_error", null),
        "apiUrl" to apiUrl(context))

    fun scheduleKick(context: Context, delayMillis: Long = 2_000) {
        if (!JarvisPower.enabled(context)) return
        val request = OneTimeWorkRequestBuilder<ContextUploadKickWorker>()
            .setInitialDelay(maxOf(1_000, delayMillis), TimeUnit.MILLISECONDS).build()
        // Replacing a tiny wake request never cancels active HTTP work.
        WorkManager.getInstance(context).enqueueUniqueWork(KICK, ExistingWorkPolicy.REPLACE, request)
    }

    fun enqueueDrain(context: Context) {
        if (!JarvisPower.enabled(context)) return
        migrateUploads(context)
        val request = OneTimeWorkRequestBuilder<ContextUploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST).build()
        WorkManager.getInstance(context).enqueueUniqueWork(FLUSH, ExistingWorkPolicy.KEEP, request)
    }

    fun eventTime(event: JSONObject): Long? = runCatching {
        java.time.Instant.parse(event.optString("occurred_at")).toEpochMilli()
    }.getOrNull()

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
            if (type !in setOf("ACTIVITY_ENTER", "ACTIVITY_EXIT", "ACTIVITY_SAMPLE")) {
                put("activity_evidence", "cached_state")
                put("reported_activity", activity)
                put("activity", "UNKNOWN")
            }
        }

    @Synchronized
    fun add(context: Context, event: JSONObject, deferCapture: Boolean = false) {
        if (!JarvisPower.enabled(context)) return
        if (!event.has("telemetry_diagnostics") && event.optString("occurred_at") == event.optString("timestamp") &&
            event.optString("event_type") !in setOf("ACTIVITY_ENTER", "ACTIVITY_EXIT", "ACTIVITY_SAMPLE", "CONTEXT_CHECKPOINT")) {
            EventTiming.mark(context, event)
        }
        val timing = event.optJSONObject("telemetry_diagnostics")
        if (timing != null && event.optString("event_type") in setOf("ACTIVITY_ENTER", "ACTIVITY_EXIT", "ACTIVITY_SAMPLE")) {
            TelemetryHistory.get(context).record(context, JSONObject(timing.toString()).apply {
                put("id", event.getString("event_id")); put("timestamp", event.getString("occurred_at"))
                put("source", "google_activity"); put("candidate", event.optString("reported_activity", event.optString("activity")))
                put("provisional", true); put("model_version", "google_play_services")
                put("features", JSONObject().apply {
                    put("accepted_activity", event.optString("activity")); put("event_type", event.optString("event_type"))
                    if (event.has("activity_confidence")) put("confidence", event.getInt("activity_confidence"))
                })
            })
        }
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        if (!event.has("ambient_context")) event.put("ambient_context", AmbientContextCapture.capture(context))
        if (!event.has("location")) event.put("location_pending", true)
        entries.put(event)
        check(prefs(context).edit().putString(EVENTS, entries.toString()).commit())
        android.util.Log.i("JarvisQueue", "Queued ${event.optString("event_type")} ${event.optString("activity")} id=${event.optString("event_id")} pending=${entries.length()}")
        if (event.optBoolean("location_pending")) {
            if (!deferCapture) scheduleLocationCapture(context)
        } else scheduleFlush(context)
    }

    @Synchronized
    fun update(context: Context, event: JSONObject) {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        for (index in 0 until entries.length()) {
            if (entries.getJSONObject(index).optString("event_id") == event.optString("event_id")) {
                val existing = entries.getJSONObject(index)
                // Immediate capture and fallback workers may overlap. A stale
                // failure must not erase a fix already captured for this event.
                if (existing.has("location") && !existing.isNull("location") &&
                    (!event.has("location") || event.isNull("location"))) {
                    event.put("location", existing.getJSONObject("location"))
                    event.put("location_status", existing.optString("location_status"))
                    event.remove("location_pending")
                }
                if (existing.optInt("location_attempts") > event.optInt("location_attempts")) {
                    event.put("location_attempts", existing.optInt("location_attempts"))
                }
                entries.put(index, event)
                check(prefs(context).edit().putString(EVENTS, entries.toString()).commit())
                return
            }
        }
    }

    fun scheduleLocationCapture(context: Context, delaySeconds: Long = 0) {
        if (!JarvisPower.enabled(context)) return
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
        acknowledge(context, setOf(id))
    }

    @Synchronized
    fun acknowledge(context: Context, ids: Set<String>) {
        val entries = JSONArray(prefs(context).getString(EVENTS, "[]"))
        val remaining = JSONArray()
        for (index in 0 until entries.length()) {
            val event = entries.getJSONObject(index)
            if (event.optString("event_id") !in ids) remaining.put(event)
        }
        check(prefs(context).edit().putString(EVENTS, remaining.toString()).commit())
    }

    fun currentActivity(context: Context): String =
        if (MotionEvidence.fresh(prefs(context).getLong("activity_observed_at", 0L), System.currentTimeMillis()))
            prefs(context).getString(ACTIVITY, "") ?: "" else "UNKNOWN"

    fun historyResetAt(context: Context): Long = prefs(context).getLong("history_reset_at", 0L)

    fun setCurrentActivity(context: Context, activity: String, at: Long = System.currentTimeMillis()) {
        if (at < prefs(context).getLong("activity_observed_at", 0L)) return
        val previous = currentActivity(context)
        check(prefs(context).edit().putString(ACTIVITY, activity).putLong("activity_observed_at", at).commit())
        if (previous != activity && ActivityRecognitionRegistrar.isEnabled(context)) {
            runCatching { ActivityRecognitionRegistrar.registerPassiveLocation(context) }
        }
    }

    fun scheduleFlush(context: Context) {
        if (!JarvisPower.enabled(context)) return
        enqueueDrain(context)
        // Cover an arrival while KEEP observes the previous worker finishing.
        scheduleKick(context, maxOf(2_000, retryAt(context) - System.currentTimeMillis()))
    }

    fun schedulePeriodic(context: Context) {
        if (!JarvisPower.enabled(context)) return
        migrateUploads(context)
        val request = PeriodicWorkRequestBuilder<ContextCheckpointWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    fun scheduleDwell(context: Context, activity: String) {
        if (!JarvisPower.enabled(context)) return
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
