package com.jarvis.jarvis_collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.location.Location
import com.google.android.gms.location.LocationResult
import org.json.JSONObject
import kotlin.math.abs

/** Uses fixes produced by the system or other apps, without starting GPS. */
class PassiveLocationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val result = LocationResult.extractResult(intent) ?: return
        val prefs = context.getSharedPreferences("jarvis_passive_location", Context.MODE_PRIVATE)
        for (location in result.locations) {
            if (location.accuracy > 150f || abs(System.currentTimeMillis() - location.time) > 300_000) continue
            val lastTime = prefs.getLong("time", 0L)
            if (location.time <= lastTime) continue
            if (lastTime != 0L) {
                val previous = Location("jarvis").apply {
                    latitude = Double.fromBits(prefs.getLong("latitude", 0L))
                    longitude = Double.fromBits(prefs.getLong("longitude", 0L))
                }
                if (previous.distanceTo(location) < 100f) continue
            }
            val activity = ContextEventQueue.currentActivity(context).ifEmpty { "UNKNOWN" }
            val event = ContextEventQueue.newEvent("CONTEXT_CHECKPOINT", activity, "ENTER", location.time)
            event.put("location", JSONObject().apply {
                put("latitude", location.latitude)
                put("longitude", location.longitude)
                put("accuracy_m", location.accuracy.toDouble())
                put("timestamp", ContextEventQueue.occurredAt(location.time))
            })
            ContextEventQueue.add(context, event)
            check(prefs.edit()
                .putLong("time", location.time)
                .putLong("latitude", location.latitude.toBits())
                .putLong("longitude", location.longitude.toBits())
                .commit())
        }
    }
}
