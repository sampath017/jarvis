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
import java.util.concurrent.CompletableFuture

/** One bounded fresh fix for a broadcast batch, never a continuous GPS stream. */
object ContextLocationCapture {
    private const val MAX_AGE_MS = 120_000L

    private fun occurred(event: JSONObject): Long? = runCatching {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.parse(event.getString("occurred_at"))?.time
    }.getOrNull()

    fun capture(context: Context, events: List<JSONObject>, durationMs: Long): List<JSONObject> {
        if (!JarvisPower.enabled(context)) return events
        if (events.isEmpty()) return events
        // Wi-Fi and existing connections provide context without waiting for a
        // Bluetooth scan that this phone's background policy repeatedly denies.
        val ambient = CompletableFuture.supplyAsync { AmbientContextCapture.capture(context) }
        val captured = captureLocation(context, events, durationMs)
        val snapshot = runCatching { ambient.get(3, TimeUnit.SECONDS) }.getOrNull()
        if (snapshot != null) captured.forEach { event ->
            // Keep the original event-time snapshot when a worker runs late.
            // Today's Wi-Fi must not overwrite an offline outing's evidence.
            val at = occurred(event)
            if (at != null && abs(System.currentTimeMillis() - at) <= 60_000L) {
                event.put("ambient_context", snapshot)
            }
        }
        return captured
    }

    private fun captureLocation(context: Context, events: List<JSONObject>, durationMs: Long): List<JSONObject> {
        if (events.isEmpty()) return events
        if (Build.VERSION.SDK_INT >= 29 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return events.onEach { it.put("location_status", "background_permission_required") }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) return events.onEach { it.put("location_status", "location_permission_required") }

        val history = TelemetryHistory.get(context)
        val fallbacks = mutableMapOf<String, JSONObject>()
        val remaining = events.filter { event ->
            if (event.has("location") && !event.isNull("location")) false
            else {
                val historical = history.nearest(context, event)
                val eventAt = occurred(event)
                val historicalAt = historical?.optString("timestamp")?.let { runCatching { java.time.Instant.parse(it).toEpochMilli() }.getOrNull() }
                val preferFresh = eventAt != null && historicalAt != null && LocationEvidence.preferFresh(
                    event.optString("activity"), event.optString("event_type"), System.currentTimeMillis()-eventAt, abs(historicalAt-eventAt))
                if (historical != null && !preferFresh) {
                    event.put("location", historical).put("location_status", "historical_event_fix")
                    false
                } else {
                    if (historical != null) fallbacks[event.getString("event_id")] = historical
                    true
                }
            }
        }
        if (remaining.isEmpty()) return events

        val client = LocationServices.getFusedLocationProviderClient(context)
        var location: Location? = null
        val now = System.currentTimeMillis()
        if (remaining.any { occurred(it)?.let { at -> abs(now - at) <= MAX_AGE_MS } == true }) {
            val cancellation = CancellationTokenSource()
            JarvisPower.trackLocation(context, cancellation)
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
                JarvisPower.releaseLocation(cancellation)
            }
        }
        // A recent system fix is a fallback only; always try a new fix first.
        if (!JarvisPower.enabled(context)) return events
        if (location == null || !location.hasAccuracy() || location.accuracy > 250f) {
            location = runCatching { Tasks.await(client.lastLocation, 1, TimeUnit.SECONDS) }.getOrNull()
        }
        val fix = location ?: run {
            remaining.forEach { event ->
                val saved = fallbacks[event.optString("event_id")]
                if (saved != null) event.put("location", saved).put("location_status", "historical_event_fix")
                else event.put("location_status", "fix_unavailable")
            }
            return events
        }
        if (!fix.hasAccuracy() || fix.accuracy > 250f) { remaining.forEach { it.put("location_status", "low_accuracy") }; return events }
        history.remember(context, fix)
        for (event in remaining) {
            val at = occurred(event) ?: continue
            // Never attach today's location to an older queued transition.
            val timing = event.optJSONObject("telemetry_diagnostics")
            val delta = LocationEvidence.delta(timing?.optInt("boot_count", -1), EventTiming.boot(context),
                timing?.optLong("observed_elapsed_ms", -1), fix.elapsedRealtimeNanos/1_000_000, at, fix.time)
            if (delta > MAX_AGE_MS) {
                event.put("location_status", "fix_outside_event_window")
                continue
            }
            event.put("location_status", if (delta <= 30_000L) "available" else "near_event_time")
            event.put("location", JSONObject().apply {
                put("latitude", fix.latitude)
                put("longitude", fix.longitude)
                put("accuracy_m", fix.accuracy.toDouble())
                if (fix.hasSpeed()) put("speed_mps", fix.speed.toDouble())
                put("timestamp", ContextEventQueue.occurredAt(fix.time))
            })
        }
        return events
    }

    /** Retry only while another fix could still describe the event. */
    fun finishAttempt(event: JSONObject): Boolean {
        if (event.has("location") && !event.isNull("location")) { event.remove("location_pending"); return false }
        val attempts = event.optInt("location_attempts") + 1
        event.put("location_attempts", attempts)
        val age = occurred(event)?.let { System.currentTimeMillis()-it } ?: Long.MAX_VALUE
        val retry = LocationEvidence.retry(attempts, age, event.optString("location_status"))
        if (!retry) event.remove("location_pending")
        return retry
    }
}
