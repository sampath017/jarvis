package com.jarvis.jarvis_collector

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Uploads queued transitions without keeping the app or CPU awake between events. */
class ContextUploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    companion object {
        private const val BASE_URL = "https://jarvis-backend-898516599131.asia-south1.run.app"
        private const val CHANNEL = "jarvis_reminders_channel"
        private const val TAG = "JarvisContextWorker"
    }

    override fun doWork(): Result {
        if (!JarvisPower.enabled(applicationContext)) return Result.success()
        try {
            val dwellActivity = inputData.getString("dwell_activity")
            if (dwellActivity != null) {
                if (ContextEventQueue.currentActivity(applicationContext) == dwellActivity) {
                    ContextEventQueue.add(
                        applicationContext,
                        ContextEventQueue.newEvent("DWELL_CHECK", dwellActivity, "ENTER"),
                    )
                }
                return Result.success()
            }

            val awaitingLocation = ContextEventQueue.pending(applicationContext).filter { it.optBoolean("location_pending") }
            for (ready in ContextLocationCapture.capture(applicationContext, awaitingLocation, 15_000)) {
                ContextLocationCapture.finishAttempt(ready)
                ContextEventQueue.update(applicationContext, ready)
            }
            for (queued in ContextEventQueue.pending(applicationContext)) {
                if(MobileRecords.applied(applicationContext,queued.getString("event_id"))){
                    ContextEventQueue.acknowledge(applicationContext,queued.getString("event_id"));continue
                }
                val event = JSONObject(queued.toString())
                val timing = event.optJSONObject("telemetry_diagnostics")
                if (timing != null && timing.optInt("boot_count", -1) == EventTiming.boot(applicationContext)) {
                    val now = android.os.SystemClock.elapsedRealtime()
                    timing.put("upload_elapsed_ms", now)
                    if (now >= timing.optLong("received_elapsed_ms", now)) timing.put("upload_delay_ms", now - timing.getLong("received_elapsed_ms"))
                }
                if (event.optBoolean("location_pending")) {
                    ContextEventQueue.scheduleLocationCapture(applicationContext)
                    return Result.success()
                }
                event.put("_mobile_state", MobileRecords.context(applicationContext, event))
                val response = request("POST", "$BASE_URL/context-events", event.toString())
                if (response.first !in 200..299 || JSONObject(response.second).optString("status") != "ok") {
                    Log.w(TAG, "Context processing rejected: HTTP ${response.first}")
                    return Result.retry()
                }
                MobileRecords.apply(applicationContext, JSONObject(response.second).getJSONObject("_mobile_changes"))
                ContextEventQueue.acknowledge(applicationContext, event.getString("event_id"))
            }

            if (inputData.getBoolean("context_checkpoint", false)) {
                val activity = ContextEventQueue.currentActivity(applicationContext).ifEmpty { "UNKNOWN" }
                ContextEventQueue.add(applicationContext,
                    ContextEventQueue.newEvent("CONTEXT_CHECKPOINT", activity, "ENTER"))
            }
            MobileRecords.deliver(applicationContext)
            return Result.success()
        } catch (error: Exception) {
            Log.w(TAG, "Context upload retained for retry", error)
            return Result.retry()
        }
    }

    private fun request(method: String, url: String, body: String? = null, timeoutMs: Int = 60_000): Pair<Int, String> {
        check(JarvisPower.enabled(applicationContext) && !isStopped) { "Jarvis is powered off" }
        val connection = (URL(url).openConnection() as HttpURLConnection).also { JarvisPower.track(applicationContext, it) }.apply {
            requestMethod = method
            connectTimeout = minOf(10_000, timeoutMs)
            readTimeout = timeoutMs
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("X-User-ID", "poco_x4_pro_user")
            if (body != null) {
                doOutput = true
                outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
        }
        return try {
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            status to (stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally {
            JarvisPower.release(connection)
        }
    }
}
