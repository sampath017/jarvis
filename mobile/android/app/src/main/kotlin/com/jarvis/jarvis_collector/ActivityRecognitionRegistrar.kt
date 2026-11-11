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
    private var sampling: Boolean? = null
    private var locationMode: String? = null

    @Synchronized private fun updateSampling(context: Context, active: Boolean) {
        if (sampling == active) return
        sampling = active
        val client = ActivityRecognition.getClient(context)
        val task = if (active) client.requestActivityUpdates(30_000L, samplePendingIntent(context))
            else client.removeActivityUpdates(samplePendingIntent(context))
        task.addOnFailureListener { sampling = null; Log.w("JarvisGAR", "Sampling update failed", it) }
    }

    fun isEnabled(context: Context): Boolean =
        JarvisPower.enabled(context) && context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("enabled", false)

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

    private fun samplePendingIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context, 2004, Intent(context, ActivityTransitionReceiver::class.java).setAction("com.jarvis.ACTIVITY_SAMPLE"),
        PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)

    private fun locationPendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, PassiveLocationReceiver::class.java)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        return PendingIntent.getBroadcast(context, 2003, intent, flags)
    }

    fun setDynamicMonitoring(context: Context, enabled: Boolean) {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (p.getBoolean("dynamic", false) == enabled) return
        p.edit().putBoolean("dynamic", enabled).commit()
        if (isEnabled(context)) registerPassiveLocation(context)
    }

    fun registerPassiveLocation(context: Context) {
        if (!JarvisPower.enabled(context)) return
        val collecting = MotionSensing.collecting(context)
        updateSampling(context, collecting)
        if (!collecting) {
            if (locationMode != "idle") {
                locationMode = "idle"
                LocationServices.getFusedLocationProviderClient(context).removeLocationUpdates(locationPendingIntent(context))
                    .addOnFailureListener { locationMode = null }
            }
            return
        }
        if (Build.VERSION.SDK_INT >= 29 &&
            context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        val dynamic = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("dynamic", false)
        val moving = ContextEventQueue.currentActivity(context) in setOf("IN_VEHICLE", "ON_BICYCLE", "WALKING", "RUNNING", "ON_FOOT")
        val hardware = MotionSensing.hardwareAvailable(context)
        val nearWifi = MotionSensing.nearKnownPlaceWifi(context)
        val highAccuracy = !nearWifi && (moving || hardware)
        val frequent = moving || dynamic || hardware
        val mode = "$highAccuracy:$frequent"
        if (locationMode == mode) return
        locationMode = mode
        val request = LocationRequest.Builder(if (highAccuracy) Priority.PRIORITY_HIGH_ACCURACY else Priority.PRIORITY_BALANCED_POWER_ACCURACY, if (frequent) 30_000L else 120_000L)
            .setMinUpdateIntervalMillis(if (frequent) 15_000L else 60_000L)
            .setMinUpdateDistanceMeters(if (moving || hardware) 20f else 50f)
            .setMaxUpdateAgeMillis(0)
            .build()
        LocationServices.getFusedLocationProviderClient(context)
            .requestLocationUpdates(request, locationPendingIntent(context))
            .addOnSuccessListener {
                if (!JarvisPower.enabled(context)) LocationServices.getFusedLocationProviderClient(context).removeLocationUpdates(locationPendingIntent(context))
                else Log.i("JarvisPassive", "Passive location registered")
            }
            .addOnFailureListener { locationMode = null; Log.w("JarvisPassive", "Location subscription unavailable", it) }
    }

    fun register(context: Context, onSuccess: () -> Unit = {}, onFailure: (Exception) -> Unit = {}) {
        if (!JarvisPower.enabled(context)) { onFailure(IllegalStateException("Jarvis is powered off")); return }
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
                if (!JarvisPower.enabled(context)) { unregister(context, {}, {}); onFailure(IllegalStateException("Jarvis is powered off")); return@addOnSuccessListener }
                setEnabled(context, true)
                AmbientNetworkMonitor.start(context)
                // Clean up the old app's two-minute activity sampler.
                client.removeActivityUpdates(pendingIntent(context))
                sampling = null // Reconcile persisted subscriptions after a process restart.
                locationMode = null
                MonitoringService.ensure(context)
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
        sampling = null
        locationMode = null
        MotionSensing.reset()
        AmbientNetworkMonitor.stop(context)
        ContextEventQueue.stopMonitoring(context)
        val client = ActivityRecognition.getClient(context)
        client.removeActivityUpdates(pendingIntent(context))
        client.removeActivityUpdates(samplePendingIntent(context))
        context.stopService(Intent(context, MonitoringService::class.java))
        LocationServices.getFusedLocationProviderClient(context)
            .removeLocationUpdates(locationPendingIntent(context))
        client.removeActivityTransitionUpdates(pendingIntent(context))
            .addOnSuccessListener { onSuccess() }
            .addOnFailureListener(onFailure)
    }
}
