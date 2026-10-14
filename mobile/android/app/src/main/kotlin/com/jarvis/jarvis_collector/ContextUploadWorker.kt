package com.jarvis.jarvis_collector

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

/** One bounded drain. Work triggers coalesce; original observations never do. */
class ContextUploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    companion object {
        private const val TAG = "JarvisContextWorker"
        private val running = AtomicBoolean(false)
    }

    override fun doWork(): Result {
        val app = applicationContext
        if (!JarvisPower.enabled(app)) return Result.success()
        inputData.getString("dwell_activity")?.let { activity ->
            if (ContextEventQueue.currentActivity(app) == activity) {
                ContextEventQueue.add(app, ContextEventQueue.newEvent("DWELL_CHECK", activity, "ENTER"))
            }
            return Result.success()
        }
        if (!running.compareAndSet(false, true)) {
            ContextEventQueue.scheduleKick(app)
            return Result.success()
        }
        val started = android.os.SystemClock.elapsedRealtime()
        var delay = 1_000L
        try {
            var liveCalls = 0
            var archived = 0
            while (JarvisPower.enabled(app) && !isStopped &&
                android.os.SystemClock.elapsedRealtime() - started < 45_000) {
                val pending = ContextEventQueue.pending(app)
                if (pending.isEmpty()) break
                val plan = ContextUploadPolicy.plan(pending.map {
                    ContextUploadPolicy.Event(it.getString("event_id"), ContextEventQueue.eventTime(it), it.optBoolean("location_pending"))
                }, System.currentTimeMillis())
                val rows = pending.associateBy { it.getString("event_id") }
                val historyIds = plan.historyIds
                val badFutureIds = plan.deferredIds.filter {
                    (ContextEventQueue.eventTime(rows.getValue(it)) ?: 0L) - System.currentTimeMillis() > 120_000
                }
                val invalidIds = plan.invalidIds + badFutureIds
                if (invalidIds.isNotEmpty()) {
                    val invalid = invalidIds.mapNotNull { rows[it] }
                    MobileRecords.archiveInvalidContextEvents(app, invalid)
                    ContextEventQueue.acknowledge(app, invalidIds.toSet())
                }
                if (historyIds.isNotEmpty() && archived < 500) {
                    val history = historyIds.take(500 - archived).mapNotNull { rows[it] }
                    // No stale alerts, Places/LLM calls or current-journey rewinds.
                    MobileRecords.archiveContextEvents(app, history)
                    ContextEventQueue.acknowledge(app, history.map { it.getString("event_id") }.toSet())
                    archived += history.size
                    Log.i(TAG, "Preserved ${history.size} historical observations locally")
                }
                if (plan.locationBlockedIds.isNotEmpty()) ContextEventQueue.scheduleLocationCapture(app)
                val retryWait = ContextEventQueue.retryAt(app) - System.currentTimeMillis()
                if (retryWait > 0) { delay = retryWait; break }
                val base = ContextEventQueue.apiUrl(app)
                if (base == null) { delay = 5_000; break }
                val live = plan.liveIds.take(4 - liveCalls)
                if (live.isEmpty()) {
                    if (historyIds.isNotEmpty() && archived < 500) continue
                    delay = if (plan.locationBlockedIds.isNotEmpty()) 10_000 else 30_000
                    break
                }
                for (id in live) {
                    if (isStopped || !JarvisPower.enabled(app) ||
                        android.os.SystemClock.elapsedRealtime() - started >= 45_000) break
                    val event = JSONObject(rows.getValue(id).toString())
                    if (MobileRecords.applied(app, id)) {
                        ContextEventQueue.acknowledge(app, id)
                        continue
                    }
                    if (ContextUploadPolicy.classify(ContextEventQueue.eventTime(event), System.currentTimeMillis()) !=
                        ContextUploadPolicy.TimeClass.LIVE) continue
                    val timing = event.optJSONObject("telemetry_diagnostics")
                    if (timing != null && timing.optInt("boot_count", -1) == EventTiming.boot(app)) {
                        val now = android.os.SystemClock.elapsedRealtime()
                        timing.put("upload_elapsed_ms", now)
                        if (now >= timing.optLong("received_elapsed_ms", now)) timing.put("upload_delay_ms", now - timing.getLong("received_elapsed_ms"))
                    }
                    event.put("_mobile_state", MobileRecords.context(app, event))
                    liveCalls++
                    val (status, body) = request(base + "/context-events", event.toString())
                    val response = runCatching { JSONObject(body) }.getOrNull()
                    val changes = response?.optJSONObject("_mobile_changes")
                    if (status !in 200..299 || response?.optString("status") != "ok" ||
                        changes == null) {
                        delay = ContextEventQueue.recordUploadFailure(app, "Context processing rejected: HTTP $status")
                        Log.w(TAG, "Context processing rejected: HTTP $status; retry in ${delay / 1000}s")
                        return Result.success()
                    }
                    MobileRecords.apply(app, changes)
                    ContextEventQueue.acknowledge(app, id)
                    ContextEventQueue.recordUploadSuccess(app)
                    Log.i(TAG, "Committed context event $id")
                }
                if (liveCalls >= 4 || archived >= 500) { delay = 20_000; break }
            }
            MobileRecords.deliver(app)
        } catch (error: Exception) {
            delay = ContextEventQueue.recordUploadFailure(app, "${error.javaClass.simpleName}: ${error.message.orEmpty()}")
            Log.w(TAG, "Context upload retained; bounded retry in ${delay / 1000}s", error)
        } finally {
            running.set(false)
            if (JarvisPower.enabled(app) && ContextEventQueue.pending(app).isNotEmpty()) {
                ContextEventQueue.scheduleKick(app, delay)
            }
        }
        return Result.success()
    }

    private fun request(url: String, body: String): Pair<Int, String> {
        val app = applicationContext
        check(JarvisPower.enabled(app) && !isStopped) { "Jarvis is powered off" }
        val connection = (URL(url).openConnection() as HttpURLConnection).also { JarvisPower.track(app, it) }
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("X-User-ID", ContextEventQueue.apiUser(app))
            connection.doOutput = true
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            status to (stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally {
            JarvisPower.release(connection)
        }
    }
}

/** A replaceable wake request never performs HTTP work itself. */
class ContextUploadKickWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (JarvisPower.enabled(applicationContext) && ContextEventQueue.pending(applicationContext).isNotEmpty()) {
            val wait = ContextEventQueue.retryAt(applicationContext) - System.currentTimeMillis()
            if (wait > 0) ContextEventQueue.scheduleKick(applicationContext, wait)
            else {
                ContextEventQueue.enqueueDrain(applicationContext)
                // A durable watchdog covers KEEP ignoring this wake during completion,
                // or the uploader process being interrupted before its final wake.
                ContextEventQueue.scheduleKick(applicationContext, 10_000)
            }
        }
        return Result.success()
    }
}

/** Periodic wakeups use the same upload drain as activity transitions. */
class ContextCheckpointWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (JarvisPower.enabled(applicationContext)) {
            ContextEventQueue.add(applicationContext, ContextEventQueue.newEvent("CONTEXT_CHECKPOINT",
                ContextEventQueue.currentActivity(applicationContext), "ENTER"))
            ContextEventQueue.scheduleFlush(applicationContext)
        }
        return Result.success()
    }
}
