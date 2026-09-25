package com.jarvis.jarvis_collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.os.SystemClock
import org.json.JSONObject
import com.google.android.gms.location.ActivityTransition
import com.google.android.gms.location.ActivityTransitionResult
import com.google.android.gms.location.ActivityRecognitionResult
import com.google.android.gms.location.DetectedActivity

/**
 * Stage 1 Low-Power Tripwire:
 * Listens for hardware activity transitions (IN_VEHICLE, WALKING, STILL)
 * delivered by Google Play Services without holding CPU wake-locks.
 */
class ActivityTransitionReceiver : BroadcastReceiver() {
    companion object {
        const val TAG = "JarvisGAR"
        const val ACTION_PROCESS_ACTIVITY_TRANSITIONS = "com.jarvis.ACTION_PROCESS_ACTIVITY_TRANSITIONS"
        
        // Listener callback registered from MainActivity / Flutter
        var transitionListener: ((activity: String, transition: String) -> Unit)? = null
        var sampleListener: ((activity: String, confidence: Int) -> Unit)? = null
    }

    override fun onReceive(context: Context, intent: Intent) {
        // Older app versions also registered periodic samples. Ignore any
        // already in flight; transitions now wake the app only when needed.
        if (ActivityRecognitionResult.hasResult(intent)) return
        if (!ActivityTransitionResult.hasResult(intent)) {
            Log.d(TAG, "Received intent with no ActivityTransitionResult")
            return
        }

        val result = ActivityTransitionResult.extractResult(intent) ?: return

        val deliveryPrefs = context.getSharedPreferences("jarvis_transition_delivery", Context.MODE_PRIVATE)
        val boot = android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.BOOT_COUNT, 0)
        val seen = deliveryPrefs.getStringSet("seen", emptySet())!!.toMutableSet()
        val locationEvents = mutableListOf<JSONObject>()
        for (event in result.transitionEvents) {
            val key = "$boot:${event.elapsedRealTimeNanos}:${event.activityType}:${event.transitionType}"
            if (seen.contains(key)) continue
            val occurredAtMillis = System.currentTimeMillis() -
                ((SystemClock.elapsedRealtimeNanos() - event.elapsedRealTimeNanos) / 1_000_000L)
            // Play Services may redeliver a pre-reset event after an app update.
            if (occurredAtMillis < ContextEventQueue.historyResetAt(context)) continue
            val activityName = when (event.activityType) {
                DetectedActivity.IN_VEHICLE -> "IN_VEHICLE"
                DetectedActivity.WALKING -> "WALKING"
                DetectedActivity.RUNNING -> "RUNNING"
                DetectedActivity.ON_BICYCLE -> "ON_BICYCLE"
                DetectedActivity.STILL -> "STILL"
                else -> "UNKNOWN"
            }

            val transitionName = when (event.transitionType) {
                ActivityTransition.ACTIVITY_TRANSITION_ENTER -> "ENTER"
                ActivityTransition.ACTIVITY_TRANSITION_EXIT -> "EXIT"
                else -> "UNKNOWN"
            }

            Log.i(TAG, "[Stage 1 Tripwire] Transition detected: $activityName -> $transitionName")

            if (activityName == "UNKNOWN" || transitionName == "UNKNOWN") continue
            val eventType = if (transitionName == "ENTER") "ACTIVITY_ENTER" else "ACTIVITY_EXIT"
            val queued = ContextEventQueue.newEvent(
                eventType, activityName, transitionName,
                occurredAtMillis,
            )
            ContextEventQueue.add(context, queued, deferCapture = true)
            locationEvents.add(queued)
            val lastStateTime = deliveryPrefs.getLong("state_time", 0L)
            if (occurredAtMillis >= lastStateTime && transitionName == "ENTER") {
                ContextEventQueue.setCurrentActivity(context, activityName)
                if (activityName == "STILL" || activityName == "WALKING") {
                    ContextEventQueue.scheduleDwell(context, activityName)
                }
            } else if (occurredAtMillis >= lastStateTime && ContextEventQueue.currentActivity(context) == activityName) {
                ContextEventQueue.setCurrentActivity(context, "")
            }

            seen.add(key)
            while (seen.size > 200) seen.remove(seen.first())
            deliveryPrefs.edit().putStringSet("seen", seen.toSet())
                .putLong("state_time", maxOf(lastStateTime, occurredAtMillis)).commit()
            // Notify in-process listener (Flutter)
            if (occurredAtMillis >= lastStateTime) transitionListener?.invoke(activityName, transitionName)

        }
        if (locationEvents.isEmpty()) return
        val appContext = context.applicationContext
        // Persist a fallback before starting the immediate fix, in case Android
        // terminates this process. It runs offline too.
        ContextEventQueue.scheduleLocationCapture(appContext, delaySeconds = 10)
        val pendingResult = goAsync()
        Thread {
            try {
                // Keep the broadcast alive for a bounded ~6.5 seconds at most.
                for (event in ContextLocationCapture.capture(appContext, locationEvents, 5_000)) {
                    if (event.has("location")) {
                        event.remove("location_pending")
                        ContextEventQueue.update(appContext, event)
                    }
                }
            } catch (error: Exception) {
                Log.w(TAG, "Immediate location deferred to durable worker", error)
            } finally {
                try {
                    ContextEventQueue.scheduleFlush(appContext)
                } finally {
                    pendingResult.finish()
                }
            }
        }.start()
    }
}
