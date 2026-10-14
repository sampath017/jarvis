package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class ContextUploadPolicyTest {
    private val now = 1_000_000L

    @Test fun fiveMinuteBoundarySeparatesLiveWorkFromLocalHistory() {
        assertEquals(ContextUploadPolicy.TimeClass.LIVE, ContextUploadPolicy.classify(now, now))
        assertEquals(ContextUploadPolicy.TimeClass.LIVE, ContextUploadPolicy.classify(now - 299_999, now))
        assertEquals(ContextUploadPolicy.TimeClass.HISTORY, ContextUploadPolicy.classify(now - 300_000, now))
        assertEquals(ContextUploadPolicy.TimeClass.HISTORY, ContextUploadPolicy.classify(now - 300_001, now))
    }

    @Test fun malformedAndFutureTimesNeverEnterTheLiveBatch() {
        val plan = ContextUploadPolicy.plan(listOf(
            ContextUploadPolicy.Event("missing-time", null),
            ContextUploadPolicy.Event("far-future", now + 120_001),
            ContextUploadPolicy.Event("small-clock-skew", now + 1),
        ), now)
        assertEquals(ContextUploadPolicy.TimeClass.INVALID, ContextUploadPolicy.classify(null, now))
        assertEquals(ContextUploadPolicy.TimeClass.FUTURE, ContextUploadPolicy.classify(now + 1, now))
        assertTrue(plan.liveIds.isEmpty())
        assertTrue(plan.historyIds.isEmpty())
        assertEquals(listOf("missing-time"), plan.invalidIds)
        assertEquals(listOf("small-clock-skew", "far-future"), plan.deferredIds)
    }

    @Test fun mixedBacklogDoesNotPutOldNetworkWorkAheadOfFreshTransitions() {
        val plan = ContextUploadPolicy.plan(listOf(
            ContextUploadPolicy.Event("old-later", now - 400_000),
            ContextUploadPolicy.Event("fresh-later", now - 1_000),
            ContextUploadPolicy.Event("old-first", now - 500_000, locationPending = true),
            ContextUploadPolicy.Event("fresh-first", now - 2_000),
        ), now)
        assertEquals(listOf("fresh-first", "fresh-later"), plan.liveIds)
        assertEquals(listOf("old-first", "old-later"), plan.historyIds)
        assertTrue(plan.locationBlockedIds.isEmpty())
        assertFalse(plan.hasMoreLive)
        assertFalse(plan.hasMoreHistory)
    }

    @Test fun boundedBatchesLeaveUnselectedEventsForTheNextPlan() {
        val live = (0 until 7).map { ContextUploadPolicy.Event("live-$it", now - 10_000 + it) }
        val old = (0 until 103).map { ContextUploadPolicy.Event("old-$it", now - 500_000 + it) }
        val events = (old + live).reversed()
        val plan = ContextUploadPolicy.plan(events, now)
        assertEquals(listOf("live-0", "live-1", "live-2", "live-3"), plan.liveIds)
        assertEquals(100, plan.historyIds.size)
        assertEquals("old-0", plan.historyIds.first())
        assertEquals("old-99", plan.historyIds.last())
        assertTrue(plan.hasMoreLive)
        assertTrue(plan.hasMoreHistory)

        val completed = (plan.liveIds + plan.historyIds).toSet()
        val next = ContextUploadPolicy.plan(events.filterNot { it.id in completed }, now)
        assertEquals(listOf("live-4", "live-5", "live-6"), next.liveIds)
        assertEquals(listOf("old-100", "old-101", "old-102"), next.historyIds)
        assertFalse(next.hasMoreLive)
        assertFalse(next.hasMoreHistory)
        assertEquals(110, events.size)
    }

    @Test fun unresolvedFreshHeadDoesNotStarveLaterReadyEvents() {
        val plan = ContextUploadPolicy.plan(listOf(
            ContextUploadPolicy.Event("waiting-head", now - 3_000, locationPending = true),
            ContextUploadPolicy.Event("ready-first", now - 2_000),
            ContextUploadPolicy.Event("waiting-later", now - 1_500, locationPending = true),
            ContextUploadPolicy.Event("ready-next", now - 1_000),
        ), now)
        assertEquals(listOf("ready-first", "ready-next"), plan.liveIds)
        assertEquals(listOf("waiting-head", "waiting-later"), plan.locationBlockedIds)
        assertEquals("waiting-head", plan.locationBlockedId)
        assertTrue(plan.hasMoreLive)
    }

    @Test fun equalObservationTimesKeepTheirPersistedQueueOrder() {
        val plan = ContextUploadPolicy.plan(listOf(
            ContextUploadPolicy.Event("second-lexically", now - 1_000),
            ContextUploadPolicy.Event("first-lexically", now - 1_000),
        ), now)
        assertEquals(listOf("second-lexically", "first-lexically"), plan.liveIds)
    }

    @Test fun extremelyOldTimestampCannotOverflowIntoLiveWork() {
        assertEquals(ContextUploadPolicy.TimeClass.HISTORY, ContextUploadPolicy.classify(Long.MIN_VALUE, now))
        assertEquals(ContextUploadPolicy.TimeClass.FUTURE, ContextUploadPolicy.classify(Long.MAX_VALUE, now))
    }

    @Test fun retryDelayBacksOffAndCapsWithoutOverflow() {
        assertEquals(listOf(5_000L, 10_000L, 20_000L, 40_000L, 60_000L, 60_000L),
            (0..5).map { ContextUploadPolicy.retryDelayMillis(it) })
        assertEquals(60_000L, ContextUploadPolicy.retryDelayMillis(Int.MAX_VALUE))
        assertEquals(5_000L, ContextUploadPolicy.retryDelayMillis(-1))
    }
}
