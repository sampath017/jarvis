package com.jarvis.jarvis_collector

import android.content.Context
import android.os.SystemClock
import org.json.JSONObject

object EventTiming {
    fun boot(context: Context): Int = android.provider.Settings.Global.getInt(
        context.contentResolver, android.provider.Settings.Global.BOOT_COUNT, -1)

    fun mark(context: Context, event: JSONObject, observedElapsedMs: Long? = null) {
        val received = SystemClock.elapsedRealtime()
        val observed = observedElapsedMs ?: received
        event.put("telemetry_diagnostics", JSONObject().apply {
            put("boot_count", boot(context))
            put("observed_elapsed_ms", observed)
            put("received_elapsed_ms", received)
            if (received >= observed) put("delivery_delay_ms", received - observed)
        })
    }
}
