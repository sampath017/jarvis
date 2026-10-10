package com.jarvis.jarvis_collector

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat

/** Keeps the low-power tripwire alive; independent of Flutter/IMU recording. */
class MonitoringService : Service() {
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private val refreshLocation = object : Runnable {
        override fun run() {
            if (!ActivityRecognitionRegistrar.isEnabled(this@MonitoringService)) { stopSelf(); return }
            // Downgrade GPS when the last movement evidence has expired.
            runCatching { ActivityRecognitionRegistrar.registerPassiveLocation(this@MonitoringService) }
            handler.postDelayed(this, 120_000L)
        }
    }
    companion object {
        fun ensure(context: Context) {
            if (!ActivityRecognitionRegistrar.isEnabled(context)) return
            try {
                context.startForegroundService(Intent(context, MonitoringService::class.java))
            } catch (error: Exception) {
                Log.w("JarvisMonitor", "Foreground recovery deferred: ${error.javaClass.simpleName}")
            }
        }
    }
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("jarvis_monitoring", "Activity monitoring", NotificationManager.IMPORTANCE_LOW))
        val tap = PendingIntent.getActivity(this, 1002, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        startForeground(1002, NotificationCompat.Builder(this, "jarvis_monitoring")
            .setSmallIcon(android.R.drawable.ic_menu_compass).setContentTitle("Jarvis monitoring is on")
            .setContentText("Listening for activity changes and context requests")
            .setContentIntent(tap).setOngoing(true).setSilent(true).build())
        handler.postDelayed(refreshLocation, 120_000L)
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!ActivityRecognitionRegistrar.isEnabled(this)) { stopSelf(); return START_NOT_STICKY }
        if (intent == null) ActivityRecognitionRegistrar.register(this)
        Log.i("JarvisMonitor", "Monitoring active; queued=${ContextEventQueue.pending(this).size}; activity=${ContextEventQueue.currentActivity(this)}")
        return START_STICKY
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() { handler.removeCallbacks(refreshLocation); super.onDestroy() }
}
