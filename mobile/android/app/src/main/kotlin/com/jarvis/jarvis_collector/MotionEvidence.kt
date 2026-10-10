package com.jarvis.jarvis_collector

/** Confidence alone is not confirmation: require two recent agreeing samples. */
object MotionEvidence {
    fun accepted(activity: String, confidence: Int, at: Long, previous: String,
                 previousConfidence: Int, previousAt: Long): String =
        if (activity in setOf("STILL", "WALKING", "RUNNING", "ON_FOOT", "IN_VEHICLE", "ON_BICYCLE") &&
            confidence >= 80 && previousConfidence >= 80 && activity == previous &&
            at - previousAt in 1L..120_000L) activity else "UNKNOWN"

    fun fresh(at: Long, now: Long): Boolean = at > 0 && now - at in 0L..120_000L
}
