package com.jarvis.jarvis_collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.google.android.gms.location.ActivityTransition
import com.google.android.gms.location.ActivityTransitionResult
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
    }

    override fun onReceive(context: Context, intent: Intent) {
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

            // Notify in-process listener (Flutter)
            transitionListener?.invoke(activityName, transitionName)

            // If entering a vehicle, automatically ensure ForegroundService is active
            if (activityName == "IN_VEHICLE" && transitionName == "ENTER") {
                Log.i(TAG, "[Stage 1 Kickstart] IN_VEHICLE ENTER -> Kicking off Stage 2 Bounded IMU Burst")
                val serviceIntent = Intent(context, TelemetryForegroundService::class.java).apply {
                    action = TelemetryForegroundService.ACTION_START
                    putExtra(TelemetryForegroundService.EXTRA_TITLE, "Jarvis")
                    putExtra(TelemetryForegroundService.EXTRA_CONTENT, "Active in background")
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(serviceIntent)
                } else {
                    context.startService(serviceIntent)
                }
            }
        }
    }
}
