package com.jarvis.jarvis_collector

import java.time.LocalDate

object UsageCachePolicy {
    fun shouldRefresh(day: LocalDate, today: LocalDate, version: Int, end: Long,
                      dayEnd: Long, error: Boolean, fetchedAt: Long, now: Long): Boolean {
        if (fetchedAt == 0L || fetchedAt > now) return true
        if (error) return now - fetchedAt >= if (day == today) 60_000L else ERROR_RETRY_MS
        if (version != 2) return true
        if (day < today && end >= dayEnd) return false
        // Yesterday's partial snapshot must be finalized immediately after midnight.
        if (day < today) return true
        return now - fetchedAt >= 60_000L
    }
    private const val ERROR_RETRY_MS = 6 * 60 * 60 * 1000L
}
