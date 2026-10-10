package com.jarvis.jarvis_collector

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** FCM data delivery runs even when Flutter is suspended or the phone is locked. */
class JarvisMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) { PushDelivery.register(applicationContext, token) }
    override fun onMessageReceived(message: RemoteMessage) {
        ContextEventQueue.scheduleFlush(applicationContext)
        val data = message.data
        if (data["kind"] == "context_request") {
            if (!ActivityRecognitionRegistrar.isEnabled(applicationContext)) return
            val requestId = data["request_id"] ?: return
            val expires = runCatching { java.time.Instant.parse(data["expires_at"]).toEpochMilli() }.getOrNull() ?: return
            if (System.currentTimeMillis() > expires) return
            val receipt = getSharedPreferences("jarvis_context_requests", Context.MODE_PRIVATE)
            if (receipt.getString("last_id", "") == requestId) return
            MonitoringService.ensure(applicationContext)
            runCatching { ActivityRecognitionRegistrar.register(applicationContext) }
            val event = ContextEventQueue.newEvent("BACKEND_CONTEXT_REQUEST", "UNKNOWN", "ENTER")
                .put("context_request_id", requestId)
            ContextEventQueue.add(applicationContext, event)
            receipt.edit().putString("last_id", requestId).commit()
            android.util.Log.i("JarvisMonitor", "Backend context wake received request=$requestId")
            return
        }
        val id = data["id"] ?: return
        PushDelivery.show(applicationContext, id, data["title"] ?: "Jarvis",
            data["body"] ?: "", data["thread_id"] ?: "", data["kind"] ?: "",
            data["delivery_mode"] ?: "notification", data["reminder_id"] ?: "", data["alarm_due_at"] ?: "", data["occurred_at"] ?: "")
    }
}

object PushDelivery {
    private const val PREFS = "jarvis_push"
    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun register(context: Context, token: String) {
        prefs(context).edit().putString("token", token).apply()
        schedule(context, refreshRegistration = true)
    }

    @Synchronized
    fun show(context: Context, id: String, title: String, body: String, threadId: String = "", kind: String = "",
             deliveryMode: String = "notification", reminderId: String = "", dueAt: String = "", occurredAt: String = ""): Boolean {
        if (id.isBlank()) return false
        val prefs = prefs(context)
        val seen = JSONArray(prefs.getString("seen", "[]"))
        if ((0 until seen.length()).any { seen.optString(it) == id }) {
            acknowledge(context, id)
            return true
        }
        val visibleChat = threadId.isNotEmpty() && MainActivity.isVisible && MainActivity.visibleThreadId == threadId
        if (ReminderAlerts.ringing(deliveryMode)) {
            val key = if (reminderId.isNotBlank() && ReminderAlerts.epoch(dueAt) > 0) ReminderAlerts.key(reminderId, dueAt) else "notification:$id"
            if (!ReminderAlerts.show(context, key, title, body, deliveryMode,
                    ReminderAlerts.epoch(dueAt).takeIf { it > 0 } ?: ReminderAlerts.epoch(occurredAt), reminderId)) return false
        } else if (!visibleChat) {
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (!manager.areNotificationsEnabled()) return false
            val channel = if (threadId.isNotEmpty()) "jarvis_chat_updates" else "jarvis_reminders_channel"
            manager.createNotificationChannel(NotificationChannel(channel,
                if (threadId.isNotEmpty()) "Jarvis replies and questions" else "Jarvis Reminders", NotificationManager.IMPORTANCE_HIGH))
            val intent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("jarvis_thread_id", threadId)
            }
            val tap = PendingIntent.getActivity(context, id.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            manager.notify(id.hashCode(), NotificationCompat.Builder(context, channel)
                .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(tap).setAutoCancel(true).setOnlyAlertOnce(true)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPriority(NotificationCompat.PRIORITY_HIGH).build())
        }
        val retained = JSONArray()
        for (i in maxOf(0, seen.length() - 199) until seen.length()) retained.put(seen.getString(i))
        retained.put(id)
        prefs.edit().putString("seen", retained.toString()).commit()
        if (threadId.isNotEmpty()) MainActivity.chatUpdateListener?.invoke(threadId)
        acknowledge(context, id)
        return true
    }

    @Synchronized
    private fun acknowledge(context: Context, id: String) {
        val p = prefs(context)
        val pending = p.getStringSet("acks", emptySet())!!.toMutableSet()
        pending.add(id)
        p.edit().putStringSet("acks", pending).commit()
        schedule(context)
    }

    @Synchronized
    fun removeAck(context: Context, id: String) {
        val p = prefs(context)
        val pending = p.getStringSet("acks", emptySet())!!.toMutableSet()
        pending.remove(id)
        p.edit().putStringSet("acks", pending).commit()
    }

    fun schedule(context: Context, refreshRegistration: Boolean = false) {
        val work = OneTimeWorkRequestBuilder<PushDeliveryWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        WorkManager.getInstance(context).enqueueUniqueWork("jarvis_push_delivery", if (refreshRegistration) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.APPEND_OR_REPLACE, work)
    }
}

class PushDeliveryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result { return try {
        val prefs = applicationContext.getSharedPreferences("jarvis_push", Context.MODE_PRIVATE)
        val token = prefs.getString("token", null)
        if (token != null && token != prefs.getString("registered_token", null)) {
            if (post("/devices/push-token", JSONObject().put("token", token).toString()) !in 200..299) return Result.retry()
            prefs.edit().putString("registered_token", token).commit()
        }
        for (id in prefs.getStringSet("acks", emptySet())!!.toSet()) {
            val status = post("/notifications/${android.net.Uri.encode(id)}/acknowledge", "{}")
            if (status in 200..299 || status == 404) PushDelivery.removeAck(applicationContext, id)
            else return Result.retry()
        }
        Result.success()
    } catch (error: Exception) { android.util.Log.w("JarvisPush", "Delivery deferred: ${error.javaClass.simpleName}"); Result.retry() } }

    private fun post(path: String, body: String): Int {
        val connection = URL("https://jarvis-backend-898516599131.asia-south1.run.app$path").openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("X-User-ID", "poco_x4_pro_user")
            connection.doOutput = true
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            connection.responseCode
        } finally { connection.disconnect() }
    }
}
