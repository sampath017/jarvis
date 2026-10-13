package com.jarvis.jarvis_collector

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.hardware.TriggerEvent
import android.hardware.TriggerEventListener
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.os.PowerManager
import android.util.Log
import org.json.JSONObject
import java.util.UUID

/** Shadow evaluation: its candidates cannot change journeys or fire reminders. */
class LocalMotionMonitor(private val context: Context) : SensorEventListener {
    private val manager = context.getSystemService(SensorManager::class.java)
    private val thread = HandlerThread("JarvisMotion")
    private lateinit var handler: Handler
    private var window = MotionWindow()
    private var lastEmit = 0L
    private var lastCandidate = ""
    private var fastUntil = 0L
    private var fast = false
    private var lastFlush = 0L
    private val activeWakeLock = context.getSystemService(PowerManager::class.java)
        .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Jarvis:MotionWindow").apply { setReferenceCounted(false) }
    @Volatile private var running = false
    private val significantMotion = manager.getDefaultSensor(Sensor.TYPE_SIGNIFICANT_MOTION)
    private val trigger = object : TriggerEventListener() {
        override fun onTrigger(event: TriggerEvent?) {
            if (!running) return
            handler.post {
                if (!running) return@post
                fastUntil = SystemClock.elapsedRealtime()+60_000
                activeWakeLock.acquire(65_000)
                fast = true; registerAcceleration()
                armMotionTrigger()
            }
        }
    }
    private val tick = object : Runnable {
        override fun run() {
            if (!running) return
            val now = SystemClock.elapsedRealtime()
            val sampledHz = if (fast) 25 else 5
            val speed = TelemetryHistory.get(context).speed(context)
            val result = window.result(now, speed)
            if (result.rms >= 0.2 || result.steps > 0 || result.candidate == "IN_VEHICLE") fastUntil = now + 60_000
            val desired = now < fastUntil
            // This phone has non-wake-up accelerometers. Keep only the bounded
            // active measurement interval awake after significant motion.
            if (desired) activeWakeLock.acquire(65_000)
            else if (activeWakeLock.isHeld) activeWakeLock.release()
            if (desired != fast) { fast = desired; registerAcceleration() }
            if (now-lastEmit >= 60_000 || result.candidate != lastCandidate) {
                val data = JSONObject().apply {
                    put("id", "motion_${UUID.randomUUID()}"); put("timestamp", ContextEventQueue.occurredAt())
                    put("source", "local_motion"); put("candidate", result.candidate)
                    put("provisional", true); put("model_version", "motion_rules_v1")
                    put("boot_count", EventTiming.boot(context)); put("observed_elapsed_ms", now)
                    put("received_elapsed_ms", now); put("delivery_delay_ms", 0)
                    put("features", JSONObject().apply {
                        put("accel_magnitude_std", result.rms); put("samples", result.samples)
                        put("span_ms", result.spanMs); put("max_gap_ms", result.maxGapMs)
                        put("steps", result.steps); put("usable", result.usable)
                        put("requested_hz", sampledHz)
                        if (result.gyroRms != null) put("gyro_rms", result.gyroRms)
                        if (speed != null) put("speed_mps", speed)
                    })
                }
                TelemetryHistory.get(context).record(context, data)
                Log.i("JarvisMotion", "candidate=${result.candidate} samples=${result.samples} span=${result.spanMs} gap=${result.maxGapMs} usable=${result.usable}")
                lastEmit = now; lastCandidate = result.candidate
            }
            if (now-lastFlush >= 300_000) { ContextEventQueue.scheduleFlush(context); lastFlush = now }
            window = MotionWindow()
            handler.postDelayed(this, 15_000)
        }
    }
    fun start() {
        running = true
        thread.start(); handler = Handler(thread.looper)
        handler.post {
            registerAcceleration()
            armMotionTrigger()
            manager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)?.let {
                runCatching { manager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL, handler) }
            }
            handler.postDelayed(tick, 15_000)
        }
    }
    private fun registerAcceleration() {
        // Prefer wake-up measurements during a bounded active interval only.
        val sensor = (if (fast) manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER, true) else null)
            ?: manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        manager.getSensorList(Sensor.TYPE_ACCELEROMETER).forEach { manager.unregisterListener(this, it) }
        sensor?.let {
            manager.unregisterListener(this, it)
            manager.registerListener(this, it, if (fast) 40_000 else 200_000, 0, handler)
        }
        manager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            manager.unregisterListener(this, it)
            if (fast) manager.registerListener(this, it, 40_000, 0, handler)
        }
    }
    private fun armMotionTrigger() {
        significantMotion?.let { runCatching { manager.requestTriggerSensor(trigger, it) } }
    }
    override fun onSensorChanged(event: SensorEvent) {
        if (SystemClock.elapsedRealtime() - event.timestamp/1_000_000 !in 0..2_000) return
        if (event.sensor.type == Sensor.TYPE_STEP_DETECTOR) window.step()
        else if (event.sensor.type == Sensor.TYPE_GYROSCOPE) window.gyro(
            event.values[0].toDouble(), event.values[1].toDouble(), event.values[2].toDouble())
        else if (event.sensor.type == Sensor.TYPE_ACCELEROMETER) window.sample(event.timestamp/1_000_000,
            event.values[0].toDouble(), event.values[1].toDouble(), event.values[2].toDouble())
    }
    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    fun stop() {
        running = false; manager.unregisterListener(this)
        if (activeWakeLock.isHeld) activeWakeLock.release()
        significantMotion?.let { manager.cancelTriggerSensor(trigger, it) }
        handler.removeCallbacksAndMessages(null); thread.quitSafely()
    }
}
