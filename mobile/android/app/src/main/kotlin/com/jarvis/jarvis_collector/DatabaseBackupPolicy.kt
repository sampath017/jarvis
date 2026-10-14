package com.jarvis.jarvis_collector

import java.time.DayOfWeek
import java.time.Duration
import java.time.ZonedDateTime
import java.time.temporal.TemporalAdjusters

object DatabaseBackupPolicy {
    const val FILE_NAME = "jarvis_db_backup.db"
    const val LEGACY_FILE_NAME = "jarvis_db_backup"
    fun nextRun(now: ZonedDateTime): ZonedDateTime {
        val sunday = now.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
            .withHour(3).withMinute(0).withSecond(0).withNano(0)
        return if (sunday.isAfter(now)) sunday else sunday.plusWeeks(1)
    }
    fun delay(now: ZonedDateTime) = Duration.between(now, nextRun(now)).toMillis()
    fun oldRevisions(ids: List<String>, head: String): List<String> {
        require(head.isNotBlank())
        return ids.distinct().filter { it != head }
    }
}
