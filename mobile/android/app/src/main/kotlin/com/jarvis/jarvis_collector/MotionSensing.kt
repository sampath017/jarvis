package com.jarvis.jarvis_collector

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.SystemClock

/** Hardware events start the existing durable capture path before GAR confirms activity. */
object MotionSensing {
    @Volatile private var observedElapsed = -1L
    fun hardwareAvailable(c: Context): Boolean {
        val manager = c.getSystemService(SensorManager::class.java)
        return listOf(Sensor.TYPE_MOTION_DETECT, Sensor.TYPE_SIGNIFICANT_MOTION, Sensor.TYPE_STEP_DETECTOR)
            .any { manager.getDefaultSensor(it, true) != null }
    }
    fun collecting(c: Context) = SensingPolicy.collect(hardwareAvailable(c),
        ContextEventQueue.currentActivity(c), SensingPolicy.recentMotion(observedElapsed, SystemClock.elapsedRealtime()))
    fun reset() { observedElapsed = -1L }
    fun observe(c: Context, reason: String, elapsed: Long): Boolean {
        if (!ActivityRecognitionRegistrar.isEnabled(c)) return false
        val now = SystemClock.elapsedRealtime()
        if (now - elapsed !in 0..2_000) return false
        val starting = !SensingPolicy.recentMotion(observedElapsed, now)
        observedElapsed = elapsed
        if (!starting) return true // Continuous movement extends the same collection period; no cooldown.
        runCatching { ActivityRecognitionRegistrar.registerPassiveLocation(c) }
        val wall = System.currentTimeMillis() - (now - elapsed)
        val event = ContextEventQueue.newEvent("CONTEXT_CHECKPOINT", "UNKNOWN", "ENTER", wall)
            .put("activity_evidence", "hardware_motion")
            .put("reported_activity", "UNKNOWN")
        EventTiming.mark(c, event, elapsed)
        // Do not promote a pickup/step to a Google WALKING transition.
        event.put("received_at", ContextEventQueue.occurredAt())
        event.put("location_status", "hardware_$reason")
        ContextEventQueue.add(c, event, deferCapture = true)
        ContextEventQueue.scheduleLocationCapture(c, delaySeconds = 10)
        Thread {
            try {
                for (captured in ContextLocationCapture.capture(c, listOf(event), 5_000)) {
                    if (captured.has("location")) captured.remove("location_pending")
                    ContextEventQueue.update(c, captured)
                }
            } catch (error: Exception) {
                android.util.Log.w("JarvisMotion", "Hardware capture retained for durable worker", error)
            } finally { ContextEventQueue.scheduleFlush(c) }
        }.start()
        return true
    }
    fun nearKnownPlaceWifi(c: Context): Boolean = runCatching {
        val wifi = AmbientContextCapture.capture(c).optJSONObject("wifi") ?: return@runCatching false
        val connected = wifi.optJSONObject("connected") ?: return@runCatching false
        val id = connected.optString("id")
        SensingPolicy.nearKnownWifi(id.isNotBlank() && id in MobileRecords.knownPlaceWifiIds(c), connected.optInt("rssi", -127))
    }.getOrDefault(false)
}
