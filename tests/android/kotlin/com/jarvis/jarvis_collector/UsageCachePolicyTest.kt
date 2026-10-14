package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class UsageCachePolicyTest {
    private val today = LocalDate.of(2026, 10, 25)
    private val now = 1_000_000_000L
    private fun refresh(day: LocalDate = today, version: Int = 2, end: Long = 100,
                        error: Boolean = false, fetched: Long = now - 10_000) =
        UsageCachePolicy.shouldRefresh(day, today, version, end, 100, error, fetched, now)

    @Test fun completedHistoryIsReusedEvenAfterAndroidEventsExpire() {
        assertFalse(refresh(day = today.minusDays(20), fetched = 1))
    }
    @Test fun yesterdayMustBeFinalizedAfterMidnight() {
        assertTrue(refresh(day = today.minusDays(1), end = 99))
        assertFalse(refresh(day = today.minusDays(1), end = 100))
    }
    @Test fun currentDayRefreshIsThrottledButKeepsCollecting() {
        assertFalse(refresh())
        assertTrue(refresh(fetched = now - 60_000))
    }
    @Test fun missingOrOutdatedCalculationIsRebuilt() {
        assertTrue(refresh(fetched = 0))
        assertTrue(refresh(day = today.minusDays(1), version = 1))
        assertTrue(refresh(fetched = now + 1))
    }
    @Test fun emptyDaysAreRetriedWithoutRepeatedHistoricalScans() {
        assertFalse(refresh(day = today.minusDays(1), error = true))
        assertTrue(refresh(day = today.minusDays(1), error = true, fetched = now - 21_600_000))
        assertTrue(refresh(error = true, fetched = now - 60_000))
    }
}
