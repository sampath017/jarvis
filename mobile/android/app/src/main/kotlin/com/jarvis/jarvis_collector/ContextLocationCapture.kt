package com.jarvis.jarvis_collector

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.android.gms.tasks.Tasks
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/** One bounded fresh fix for a broadcast batch, never a continuous GPS stream. */
object ContextLocationCapture {
    private const val MAX_AGE_MS = 30_000L

    private fun occurred(event: JSONObject): Long? = runCatching {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.parse(event.getString("occurred_at"))?.time
    }.getOrNull()

    fun capture(context: Context, events: List<JSONObject>, durationMs: Long): List<JSONObject> {
        if (events.isEmpty()) return events
        if (Build.VERSION.SDK_INT >= 29 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return events
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return events

        val client = LocationServices.getFusedLocationProviderClient(context)
        var location: Location? = null
        val now = System.currentTimeMillis()
        if (events.any { occurred(it)?.let { at -> abs(now - at) <= MAX_AGE_MS } == true }) {
            val cancellation = CancellationTokenSource()
            try {
                val request = CurrentLocationRequest.Builder()
                    .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
                    .setMaxUpdateAgeMillis(0)
                    .setDurationMillis(durationMs)
                    .build()
                location = Tasks.await(client.getCurrentLocation(request, cancellation.token),
                    durationMs + 500, TimeUnit.MILLISECONDS)
            } catch (error: Exception) {
                Log.d("JarvisLocation", "Fresh fix unavailable: ${error.message}")
            } finally {
                cancellation.cancel()
            }
        }
        // A recent system fix is a fallback only; always try a new fix first.
        if (location == null || !location.hasAccuracy() || location.accuracy > 250f) {
            location = runCatching { Tasks.await(client.lastLocation, 1, TimeUnit.SECONDS) }.getOrNull()
        }
        val fix = location ?: return events
        if (!fix.hasAccuracy() || fix.accuracy > 250f) return events
        for (event in events) {
            val at = occurred(event) ?: continue
            // Never attach today's location to an older queued transition.
            if (abs(fix.time - at) > MAX_AGE_MS) continue
            event.put("location", JSONObject().apply {
                put("latitude", fix.latitude)
                put("longitude", fix.longitude)
                put("accuracy_m", fix.accuracy.toDouble())
                put("timestamp", ContextEventQueue.occurredAt(fix.time))
            })
        }
        return events
    }
}
