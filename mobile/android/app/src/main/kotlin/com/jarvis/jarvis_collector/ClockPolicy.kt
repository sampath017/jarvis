package com.jarvis.jarvis_collector

import java.time.Instant
import java.time.ZoneId

/** Wall time for local alarms; monotonic time for interval measurements. */
object ClockPolicy {
    fun nextAlarm(hour: Int, minute: Int, days: Set<Int>, now: Long, zone: ZoneId = ZoneId.systemDefault()): Long {
        require(hour in 0..23 && minute in 0..59 && days.all { it in 1..7 })
        val local = Instant.ofEpochMilli(now).atZone(zone)
        for (offset in 0L..8L) {
            val date = local.toLocalDate().plusDays(offset)
            if (days.isNotEmpty() && date.dayOfWeek.value !in days) continue
            val candidate = date.atTime(hour, minute).atZone(zone).toInstant().toEpochMilli()
            if (candidate > now) return candidate
        }
        error("No alarm occurrence")
    }
    fun remaining(endElapsed: Long, endWall: Long, savedBoot: Int, boot: Int, elapsed: Long, wall: Long): Long =
        maxOf(0, if (savedBoot == boot) endElapsed - elapsed else endWall - wall)
    fun measured(base: Long, startedElapsed: Long, startedWall: Long, savedBoot: Int, boot: Int, elapsed: Long, wall: Long): Long =
        base + maxOf(0, if (savedBoot == boot) elapsed - startedElapsed else wall - startedWall)
}
