package com.jarvis.edge.service

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.jarvis.edge.JarvisApp
import com.jarvis.edge.ui.MainActivity
import kotlin.math.abs

object NotificationHelper {

    fun showReminderNotification(
        context: Context,
        taskId: String,
        title: String,
        message: String
    ) {
        val notificationManager =
            context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Derive deterministic notification ID from task ID
        val notificationId = abs(taskId.hashCode() % 100000) + 3000

        // Anti-spam deduplication: Don't push if notification for this task is already active
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val activeNotifs = notificationManager.activeNotifications
            if (activeNotifs != null && activeNotifs.any { it.id == notificationId }) {
                return
            }
        }

        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(context, JarvisApp.CHANNEL_ID_REMINDERS)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        notificationManager.notify(notificationId, notification)
    }
}
