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
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.Tasks
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/** Uploads queued transitions without keeping the app or CPU awake between events. */
class ContextUploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    companion object {
        private const val BASE_URL = "https://jarvis-backend-898516599131.asia-south1.run.app"
        private const val CHANNEL = "jarvis_reminders_channel"
        private const val TAG = "JarvisContextWorker"
    }

    override fun doWork(): Result {
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

            for (queued in ContextEventQueue.pending(applicationContext)) {
                val event = JSONObject(queued.toString())
                attachRecentLocation(event)
                val response = request("POST", "$BASE_URL/context-events", event.toString())
                if (response.first !in 200..299 || JSONObject(response.second).optString("status") != "ok") {
                    Log.w(TAG, "Event ${event.optString("event_id")} rejected: HTTP ${response.first}, ${response.second.take(300)}")
                    return Result.retry()
                }
                ContextEventQueue.acknowledge(applicationContext, event.getString("event_id"))
            }
            deliverNotifications()
            return Result.success()
        } catch (error: Exception) {
            Log.w(TAG, "Context upload retained for retry", error)
            return Result.retry()
        }
    }

    private fun attachRecentLocation(event: JSONObject) {
        if (event.has("location")) return
        if (Build.VERSION.SDK_INT >= 29 &&
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return
        if (ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return

        try {
            val client = LocationServices.getFusedLocationProviderClient(applicationContext)
            val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }
            val occurred = format.parse(event.getString("occurred_at"))?.time ?: return
            var location = Tasks.await(client.lastLocation, 4, TimeUnit.SECONDS)
            if ((location == null || abs(location.time - occurred) > 120_000 || location.accuracy > 250f) &&
                abs(System.currentTimeMillis() - occurred) <= 120_000
            ) {
                // Request one bounded fix only at a fresh transition. No GPS stream runs while idle.
                val request = CurrentLocationRequest.Builder()
                    .setPriority(Priority.PRIORITY_BALANCED_POWER_ACCURACY)
                    .setMaxUpdateAgeMillis(120_000)
                    .setDurationMillis(15_000)
                    .build()
                location = Tasks.await(client.getCurrentLocation(request, null), 18, TimeUnit.SECONDS)
            }
            if (location == null) return
            // A later cached fix must not be mistaken for the location at the event.
            if (abs(location.time - occurred) > 120_000 || location.accuracy > 250f) return
            event.put("location", JSONObject().apply {
                put("latitude", location.latitude)
                put("longitude", location.longitude)
                put("accuracy_m", location.accuracy.toDouble())
                put("timestamp", ContextEventQueue.occurredAt(location.time))
            })
        } catch (error: Exception) {
            Log.d(TAG, "No recent location for activity event: ${error.message}")
        }
    }

    private fun deliverNotifications() {
        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        if (!manager.areNotificationsEnabled()) return

        val response = request("GET", "$BASE_URL/notifications?status=PENDING")
        if (response.first !in 200..299) throw IllegalStateException("Notification fetch: ${response.first}")
        val records = JSONObject(response.second).optJSONArray("records") ?: return
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL, "Jarvis Reminders", NotificationManager.IMPORTANCE_HIGH,
            ))
        }
        for (index in 0 until records.length()) {
            val record = records.getJSONObject(index)
            if (record.optString("status").uppercase() != "PENDING") continue
            val id = record.optString("id")
            if (id.isEmpty()) continue
            val title = record.optString("title", "Jarvis Reminder")
            val body = record.optString("body", title)
            val launchIntent = applicationContext.packageManager.getLaunchIntentForPackage(applicationContext.packageName)
            val contentIntent = launchIntent?.let {
                PendingIntent.getActivity(applicationContext, id.hashCode(), it,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            }
            val notification = NotificationCompat.Builder(applicationContext, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(contentIntent)
                .build()
            manager.notify(id.hashCode(), notification)
            val ack = request("POST", "$BASE_URL/notifications/${Uri.encode(id)}/acknowledge", "{}")
            if (ack.first !in 200..299) throw IllegalStateException("Notification acknowledgement: ${ack.first}")
        }
    }

    private fun request(method: String, url: String, body: String? = null): Pair<Int, String> {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 60_000
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
