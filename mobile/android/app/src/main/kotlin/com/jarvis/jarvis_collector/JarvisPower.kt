package com.jarvis.jarvis_collector

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import androidx.work.WorkManager
import java.net.HttpURLConnection

/** Durable master switch is checked before every background entry point. */
object JarvisPower {
    private fun prefs(c: Context) = c.getSharedPreferences("jarvis_power", Context.MODE_PRIVATE)
    fun enabled(c: Context) = prefs(c).getBoolean("enabled", true)
    fun status(c: Context) = mapOf("enabled" to enabled(c), "cloudConfirmed" to prefs(c).getBoolean("cloud_confirmed", true), "resumeMonitoring" to prefs(c).getBoolean("resume_monitoring", true))
    fun cloudConfirmed(c: Context, value: Boolean) { check(prefs(c).edit().putBoolean("cloud_confirmed", value).commit()) }
    private val connections = java.util.Collections.synchronizedSet(mutableSetOf<HttpURLConnection>())
    private val locations = java.util.Collections.synchronizedSet(mutableSetOf<com.google.android.gms.tasks.CancellationTokenSource>())
    fun trackLocation(c: Context, source: com.google.android.gms.tasks.CancellationTokenSource) {
        synchronized(locations) {
            if (!enabled(c)) source.cancel() else locations.add(source)
        }
    }
    fun releaseLocation(source: com.google.android.gms.tasks.CancellationTokenSource) { locations.remove(source); source.cancel() }
    fun track(c: Context, connection: HttpURLConnection) {
        synchronized(connections) {
            check(enabled(c)) { "Jarvis is powered off" }
            connections.add(connection)
        }
    }
    fun release(connection: HttpURLConnection) { connections.remove(connection); connection.disconnect() }

    @Synchronized fun setEnabled(c: Context, value: Boolean) {
        val p = prefs(c)
        if (!value && enabled(c)) {
            p.edit().putBoolean("resume_monitoring", ActivityRecognitionRegistrar.isEnabled(c)).commit()
        }
        check(p.edit().putBoolean("enabled", value).commit()) // Persist before cancellation/reboot.
        if (!value) {
            synchronized(locations) { locations.toList().forEach { it.cancel() }; locations.clear() }
            synchronized(connections) { connections.toList().forEach { it.disconnect() }; connections.clear() }
            ActivityRecognitionRegistrar.unregister(c, {}, {})
            c.stopService(Intent(c, MonitoringService::class.java))
            c.stopService(Intent(c, TelemetryForegroundService::class.java))
            ReminderAlerts.pause(c)
            UsageReporting.pause(c)
            WorkManager.getInstance(c).cancelAllWork()
            (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancelAll()
        } else {
            UsageReporting.schedule(c)
            ReminderAlerts.restore(c)
            if (p.getBoolean("resume_monitoring", true)) ActivityRecognitionRegistrar.register(c)
        }
    }
}
