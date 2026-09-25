package com.jarvis.jarvis_collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
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

        for (event in result.transitionEvents) {
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
            ContextEventQueue.add(context, ContextEventQueue.newEvent(eventType, activityName, transitionName))
            if (transitionName == "ENTER") {
                ContextEventQueue.setCurrentActivity(context, activityName)
                if (activityName == "STILL" || activityName == "WALKING") {
                    ContextEventQueue.scheduleDwell(context, activityName)
                }
            } else if (ContextEventQueue.currentActivity(context) == activityName) {
                ContextEventQueue.setCurrentActivity(context, "")
            }

            // Notify in-process listener (Flutter)
            transitionListener?.invoke(activityName, transitionName)

        }
    }
}
