package com.jarvis.jarvis_collector

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import com.google.android.gms.location.ActivityRecognition
import com.google.android.gms.location.ActivityTransition
import com.google.android.gms.location.ActivityTransitionRequest
import com.google.android.gms.location.DetectedActivity
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority

object ActivityRecognitionRegistrar {
    private const val PREFS = "jarvis_monitoring"

    fun isEnabled(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("enabled", false)

    fun setEnabled(context: Context, enabled: Boolean) {
        check(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean("enabled", enabled).commit())
    }

    private fun pendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, ActivityTransitionReceiver::class.java).apply {
            action = ActivityTransitionReceiver.ACTION_PROCESS_ACTIVITY_TRANSITIONS
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        return PendingIntent.getBroadcast(context, 2002, intent, flags)
    }

    private fun locationPendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, PassiveLocationReceiver::class.java)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        return PendingIntent.getBroadcast(context, 2003, intent, flags)
    }

    private fun registerPassiveLocation(context: Context) {
        if (Build.VERSION.SDK_INT >= 29 &&
            context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        val request = LocationRequest.Builder(Priority.PRIORITY_PASSIVE, 5 * 60_000L)
            .setMinUpdateIntervalMillis(2 * 60_000L)
            .setMinUpdateDistanceMeters(100f)
            .setMaxUpdateAgeMillis(0)
            .build()
        LocationServices.getFusedLocationProviderClient(context)
            .requestLocationUpdates(request, locationPendingIntent(context))
            .addOnSuccessListener { Log.i("JarvisPassive", "Passive location registered") }
            .addOnFailureListener { Log.w("JarvisPassive", "Passive location unavailable", it) }
    }

    fun register(context: Context, onSuccess: () -> Unit = {}, onFailure: (Exception) -> Unit = {}) {
        val transitions = listOf(
            DetectedActivity.IN_VEHICLE,
            DetectedActivity.WALKING,
            DetectedActivity.STILL,
            DetectedActivity.RUNNING,
            DetectedActivity.ON_BICYCLE,
        ).flatMap { activity ->
            listOf(
                ActivityTransition.Builder().setActivityType(activity)
                    .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_ENTER).build(),
                ActivityTransition.Builder().setActivityType(activity)
                    .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_EXIT).build(),
            )
        }
        val client = ActivityRecognition.getClient(context)
        client.requestActivityTransitionUpdates(ActivityTransitionRequest(transitions), pendingIntent(context))
            .addOnSuccessListener {
                setEnabled(context, true)
                // Clean up the old app's two-minute activity sampler.
                client.removeActivityUpdates(pendingIntent(context))
                ContextEventQueue.schedulePeriodic(context)
                ContextEventQueue.scheduleFlush(context)
                try {
                    registerPassiveLocation(context)
                } catch (error: Exception) {
                    Log.w("JarvisPassive", "Passive location unavailable", error)
                }
                onSuccess()
            }
            .addOnFailureListener(onFailure)
    }

    fun unregister(context: Context, onSuccess: () -> Unit, onFailure: (Exception) -> Unit) {
        setEnabled(context, false)
        ContextEventQueue.stopMonitoring(context)
        val client = ActivityRecognition.getClient(context)
        client.removeActivityUpdates(pendingIntent(context))
        LocationServices.getFusedLocationProviderClient(context)
            .removeLocationUpdates(locationPendingIntent(context))
        client.removeActivityTransitionUpdates(pendingIntent(context))
            .addOnSuccessListener { onSuccess() }
            .addOnFailureListener(onFailure)
    }
}
