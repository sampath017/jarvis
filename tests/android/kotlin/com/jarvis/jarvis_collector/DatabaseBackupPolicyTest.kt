package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

class DatabaseBackupPolicyTest {
    private val zone = ZoneId.of("Asia/Kolkata")
    @Test fun schedulesNextSundayAtThree() {
        val now = ZonedDateTime.of(2026, 10, 28, 12, 0, 0, 0, zone)
        val next = DatabaseBackupPolicy.nextRun(now)
        assertEquals("2026-11-01T03:00+05:30[Asia/Kolkata]", next.toString())
        assertTrue(DatabaseBackupPolicy.delay(now) > 0)
    }
    @Test fun sundayBeforeThreeRunsTodayAndAtThreeRunsNextWeek() {
        val sunday = ZonedDateTime.of(2026, 11, 1, 2, 0, 0, 0, zone)
        assertEquals(1, DatabaseBackupPolicy.nextRun(sunday).dayOfMonth)
        assertEquals(8, DatabaseBackupPolicy.nextRun(sunday.withHour(3)).dayOfMonth)
    }
    @Test fun pruneNeverDeletesCurrentRevisionAndDeduplicatesOldOnes() {
        assertEquals(listOf("one", "two"), DatabaseBackupPolicy.oldRevisions(listOf("one", "head", "two", "one"), "head"))
        assertEquals(emptyList<String>(), DatabaseBackupPolicy.oldRevisions(listOf("head"), "head"))
    }
    @Test(expected = IllegalArgumentException::class) fun noPruneWithoutVerifiedHead() {
        DatabaseBackupPolicy.oldRevisions(listOf("only-copy"), "")
    }
}
