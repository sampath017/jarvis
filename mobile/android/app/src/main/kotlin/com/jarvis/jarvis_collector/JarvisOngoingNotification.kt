package com.jarvis.jarvis_collector

import android.app.*
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat

/** One visible notification shared by the monitoring and microphone services. */
object JarvisOngoingNotification {
    const val ID = 1002
    fun build(c: Context): Notification {
        val manager = c.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("jarvis_monitoring", "Jarvis background activity", NotificationManager.IMPORTANCE_LOW))
        val voice = JarvisVoiceService.running
        val open = PendingIntent.getActivity(c, 5709, Intent(c, MainActivity::class.java).putExtra("jarvis_voice", voice), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val builder = NotificationCompat.Builder(c, "jarvis_monitoring")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentTitle(if (voice) "Jarvis · ${JarvisVoiceService.phase}" else "Jarvis monitoring is on")
            .setContentText(if (voice) "Say Hey Jarvis or Hello Jarvis" else "Listening for activity changes and context requests")
            .setContentIntent(open).setOngoing(true).setSilent(true).setOnlyAlertOnce(true)
        if (voice) {
            val stop = PendingIntent.getService(c, 5708, Intent(c, JarvisVoiceService::class.java).setAction("stop"), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            builder.addAction(0, "Stop listening", stop)
        }
        return builder.build()
    }
    fun refresh(c: Context) {
        val manager = c.getSystemService(NotificationManager::class.java)
        if (JarvisPower.enabled(c) && (MonitoringService.running || JarvisVoiceService.running)) manager.notify(ID, build(c))
        else manager.cancel(ID)
    }
}
