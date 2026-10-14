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
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Local notification display and acknowledgement for polled API updates. */
object PushDelivery {
    private const val PREFS = "jarvis_notification_receipts"
    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    @Synchronized
    fun show(context: Context, id: String, title: String, body: String, threadId: String = "", kind: String = "",
             deliveryMode: String = "notification", reminderId: String = "", dueAt: String = "", occurredAt: String = ""): Boolean {
        if (!JarvisPower.enabled(context) || id.isBlank()) return false
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

    private fun acknowledge(context:Context,id:String) {}
    fun removeAck(context:Context,id:String) {}
    fun schedule(context:Context,refreshRegistration:Boolean=false) {}
}
// Retain the worker class so work queued by older installations can finish safely.
class PushDeliveryWorker(context:Context,params:WorkerParameters):Worker(context,params) {
    override fun doWork():Result {
        return Result.success()
    }
}
