package com.jarvis.jarvis_collector

import java.time.Instant

/** Shared identity across the local clock and cloud delivery, independent of timezone formatting. */
object ReminderAlertPolicy {
    fun epoch(value: String): Long = runCatching { Instant.parse(value).toEpochMilli() }.getOrDefault(0)
    fun key(id: String, due: String) = "reminder:$id:${epoch(due)}"
    fun ringing(mode: String) = mode == "alarm" || mode == "in_app_call"
    fun timeOnly(mode: String, status: String, due: Long, hasContext: Boolean) =
        ringing(mode) && status == "ACTIVE" && due > 0 && !hasContext
    fun missed(at: Long, now: Long) = at > 0 && now - at > 15 * 60_000
}
