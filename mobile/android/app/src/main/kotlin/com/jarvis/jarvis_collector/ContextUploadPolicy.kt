package com.jarvis.jarvis_collector

/** Selects bounded work without changing or acknowledging the durable event queue. */
object ContextUploadPolicy {
    const val MAX_LIVE_AGE_MS = 300_000L
    const val MAX_LIVE_EVENTS = 4
    const val MAX_HISTORY_EVENTS = 100
    const val MAX_RETRY_DELAY_MS = 60_000L

    data class Event(
        val id: String,
        val occurredAtMillis: Long?,
        val locationPending: Boolean = false,
    )

    enum class TimeClass { LIVE, HISTORY, INVALID, FUTURE }

    data class Plan(
        val liveIds: List<String>,
        val historyIds: List<String>,
        val invalidIds: List<String>,
        val deferredIds: List<String>,
        val locationBlockedIds: List<String>,
        val hasMoreLive: Boolean,
        val hasMoreHistory: Boolean,
    ) {
        val locationBlockedId: String? get() = locationBlockedIds.firstOrNull()
    }

    fun classify(occurredAtMillis: Long?, nowMillis: Long): TimeClass {
        if (occurredAtMillis == null) return TimeClass.INVALID
        // The API rejects a negative observation age, even for small clock skew.
        if (occurredAtMillis > nowMillis) return TimeClass.FUTURE
        val age = nowMillis - occurredAtMillis
        // A negative difference here can only be overflow from an extremely old timestamp.
        return if (age < 0 || age >= MAX_LIVE_AGE_MS) TimeClass.HISTORY else TimeClass.LIVE
    }

    fun plan(events: List<Event>, nowMillis: Long): Plan {
        val groups = events.groupBy { classify(it.occurredAtMillis, nowMillis) }
        fun chronological(kind: TimeClass) = groups[kind].orEmpty().sortedBy { it.occurredAtMillis }

        val fresh = chronological(TimeClass.LIVE)
        val ready = fresh.filterNot { it.locationPending }
        val history = chronological(TimeClass.HISTORY)
        return Plan(
            liveIds = ready.take(MAX_LIVE_EVENTS).map { it.id },
            // Old observations remain useful local history even without a captured location.
            historyIds = history.take(MAX_HISTORY_EVENTS).map { it.id },
            invalidIds = groups[TimeClass.INVALID].orEmpty().map { it.id },
            deferredIds = chronological(TimeClass.FUTURE).map { it.id },
            // An unresolved observation must not starve later observations with a valid fix.
            locationBlockedIds = fresh.filter { it.locationPending }.map { it.id },
            hasMoreLive = fresh.size > minOf(ready.size, MAX_LIVE_EVENTS),
            hasMoreHistory = history.size > MAX_HISTORY_EVENTS,
        )
    }

    /** Zero-based retry attempt; the cap also prevents integer-shift overflow. */
    fun retryDelayMillis(attempt: Int): Long = when (attempt.coerceIn(0, 4)) {
        0 -> 5_000L
        1 -> 10_000L
        2 -> 20_000L
        3 -> 40_000L
        else -> MAX_RETRY_DELAY_MS
    }
}
