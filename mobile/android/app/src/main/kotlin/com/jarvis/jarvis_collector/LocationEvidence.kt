package com.jarvis.jarvis_collector

import kotlin.math.abs

/** Keep timing and retry decisions testable independently of Android providers. */
object LocationEvidence {
    fun preferFresh(activity: String, eventType: String, ageMs: Long, cachedDeltaMs: Long): Boolean =
        activity in setOf("WALKING", "RUNNING", "ON_FOOT", "ON_BICYCLE", "IN_VEHICLE") &&
        eventType in setOf("ACTIVITY_ENTER", "ACTIVITY_TRANSITION", "ACTIVITY_SAMPLE") &&
        ageMs in 0..30_000 && cachedDeltaMs > 10_000
    fun delta(eventBoot: Int?, currentBoot: Int, observedElapsed: Long?, fixElapsed: Long,
        eventWall: Long, fixWall: Long): Long {
        if (eventBoot != null && (eventBoot < 0 || eventBoot != currentBoot)) return Long.MAX_VALUE
        return if (observedElapsed != null && eventBoot != null) abs(fixElapsed-observedElapsed)
            else abs(fixWall-eventWall)
    }
    fun retry(attempts: Int, ageMs: Long, status: String): Boolean =
        attempts < 3 && ageMs in 0..90_000 && status in setOf("fix_unavailable", "low_accuracy")
}
