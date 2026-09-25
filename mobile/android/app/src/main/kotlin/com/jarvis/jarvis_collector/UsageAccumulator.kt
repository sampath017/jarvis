package com.jarvis.jarvis_collector

/** Single foreground timeline: clips day boundaries and never counts overlapping apps twice. */
class UsageAccumulator(private val start: Long, private val end: Long) {
    private var active: String? = null
    private var activityClass: String? = null
    private var since = start
    private var interactive = true
    private var unlocked = true
    val totals = mutableMapOf<String, Long>()
    private fun close(at: Long) {
        active?.let { pkg ->
            val duration = (minOf(at, end) - maxOf(since, start)).coerceAtLeast(0)
            if (interactive && unlocked) totals[pkg] = (totals[pkg] ?: 0) + duration
        }
        active = null
        activityClass = null
    }
    fun resume(pkg: String, clazz: String?, at: Long) {
        if (at >= end) return
        if (active == pkg && activityClass == clazz) return
        close(at)
        active = pkg; activityClass = clazz; since = at
    }
    fun pause(pkg: String, clazz: String?, at: Long) {
        if (active == pkg && (clazz == null || activityClass == clazz)) close(at)
    }
    fun screenOff(at: Long) { close(at); interactive = false }
    fun screenOn(at: Long) { interactive = true; since = maxOf(since, at) }
    fun lock(at: Long) { close(at); unlocked = false }
    fun unlock(at: Long) { unlocked = true; since = maxOf(since, at) }
    fun finish(): Map<String, Long> { close(end); return totals.filterValues { it > 0 } }
}
