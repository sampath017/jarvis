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
        try {
            if (AmbientContextCapture.needsCloudIdentity(applicationContext)) {
                runCatching {
                    val response = request("GET", "$BASE_URL/context-identity", timeoutMs = 2500)
                    if (response.first in 200..299) AmbientContextCapture.restoreCloudIdentity(
                        applicationContext, JSONObject(response.second).optString("fingerprint_salt"))
                }
            }
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
                ready.remove("location_pending")
                ContextEventQueue.update(applicationContext, ready)
            }
            for (queued in ContextEventQueue.pending(applicationContext)) {
                val event = JSONObject(queued.toString())
                if (event.optBoolean("location_pending")) {
                    ContextEventQueue.scheduleLocationCapture(applicationContext)
                    return Result.success()
                }
                val response = request("POST", "$BASE_URL/context-events", event.toString())
                if (response.first !in 200..299 || JSONObject(response.second).optString("status") != "ok") {
                    Log.w(TAG, "Event ${event.optString("event_id")} rejected: HTTP ${response.first}, ${response.second.take(300)}")
                    return Result.retry()
                }
                ContextEventQueue.acknowledge(applicationContext, event.getString("event_id"))
            }
            if (inputData.getBoolean("context_checkpoint", false)) {
                val activity = ContextEventQueue.currentActivity(applicationContext).ifEmpty { "UNKNOWN" }
                ContextEventQueue.add(applicationContext,
                    ContextEventQueue.newEvent("CONTEXT_CHECKPOINT", activity, "ENTER"))
            }
            deliverNotifications()
            val reminders = request("GET", "$BASE_URL/reminders")
            if (reminders.first in 200..299) {
                val records = JSONObject(reminders.second).optJSONArray("records")
                val dynamic = records != null && (0 until records.length()).any {
                    val r = records.getJSONObject(it)
                    r.optString("status") == "ACTIVE" && !r.isNull("dynamic_policy")
                }
                ActivityRecognitionRegistrar.setDynamicMonitoring(applicationContext, dynamic)
            }
            return Result.success()
        } catch (error: Exception) {
            Log.w(TAG, "Context upload retained for retry", error)
            return Result.retry()
        }
    }

    private fun deliverNotifications() {
        val response = request("GET", "$BASE_URL/notifications?status=PENDING")
        if (response.first !in 200..299) throw IllegalStateException("Notification fetch: ${response.first}")
        val records = JSONObject(response.second).optJSONArray("records") ?: return
        for (index in 0 until records.length()) {
            val record = records.getJSONObject(index)
            if (record.optString("status").uppercase() != "PENDING") continue
            val id = record.optString("id")
            if (id.isEmpty()) continue
            PushDelivery.show(applicationContext, id, record.optString("title", "Jarvis"),
                record.optString("body"), record.optString("thread_id"), record.optString("kind"))
        }
    }

    private fun request(method: String, url: String, body: String? = null, timeoutMs: Int = 60_000): Pair<Int, String> {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
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
            connection.disconnect()
        }
    }
}
