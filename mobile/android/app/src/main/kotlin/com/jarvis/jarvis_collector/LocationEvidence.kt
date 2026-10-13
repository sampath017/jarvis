package com.jarvis.jarvis_collector

import kotlin.math.abs

/** Keep timing and retry decisions testable independently of Android providers. */
object LocationEvidence {
    fun delta(eventBoot: Int?, currentBoot: Int, observedElapsed: Long?, fixElapsed: Long,
        eventWall: Long, fixWall: Long): Long {
        if (eventBoot != null && (eventBoot < 0 || eventBoot != currentBoot)) return Long.MAX_VALUE
        return if (observedElapsed != null && eventBoot != null) abs(fixElapsed-observedElapsed)
            else abs(fixWall-eventWall)
    }
    fun retry(attempts: Int, ageMs: Long, status: String): Boolean =
        attempts < 3 && ageMs in 0..90_000 && status in setOf("fix_unavailable", "low_accuracy")
}
