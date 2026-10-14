package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class LocationEvidenceTest {
    @Test fun freshMovingBoundaryDoesNotReuseAnOldIndoorFixFirst() {
        assertTrue(LocationEvidence.preferFresh("WALKING", "ACTIVITY_ENTER", 500, 89_000))
        assertTrue(LocationEvidence.preferFresh("ON_FOOT", "ACTIVITY_SAMPLE", 500, 30_000))
        assertFalse(LocationEvidence.preferFresh("WALKING", "ACTIVITY_ENTER", 500, 5_000))
        assertFalse(LocationEvidence.preferFresh("WALKING", "ACTIVITY_ENTER", 180_000, 89_000))
        assertFalse(LocationEvidence.preferFresh("UNKNOWN", "CONTEXT_CHECKPOINT", 500, 89_000))
    }
    @Test fun wallClockJumpDoesNotRejectContemporaneousMonotonicFix() {
        assertEquals(1_000L, LocationEvidence.delta(5, 5, 20_000, 21_000, 100_000, 3_700_000))
    }
    @Test fun matchingWallTimeDoesNotHideStaleMonotonicFix() {
        assertEquals(300_000L, LocationEvidence.delta(5, 5, 20_000, 320_000, 100_000, 100_000))
    }
    @Test fun previousBootFixCannotMatchEvenWhenElapsedValuesCoincide() {
        assertEquals(Long.MAX_VALUE, LocationEvidence.delta(4, 5, 20_000, 20_000, 100_000, 100_000))
        assertEquals(Long.MAX_VALUE, LocationEvidence.delta(-1, -1, 20_000, 20_000, 100_000, 100_000))
    }
    @Test fun legacyEventsUseMeasuredWallTime() {
        assertEquals(60_000L, LocationEvidence.delta(null, 5, null, 20_000, 100_000, 160_000))
    }
    @Test fun retriesAreBoundedAndCannotRefreshOldEventsWithCurrentLocation() {
        assertTrue(LocationEvidence.retry(1, 30_000, "fix_unavailable"))
        assertTrue(LocationEvidence.retry(2, 50_000, "low_accuracy"))
        assertFalse(LocationEvidence.retry(3, 50_000, "low_accuracy"))
        assertFalse(LocationEvidence.retry(1, 120_000, "fix_unavailable"))
        assertFalse(LocationEvidence.retry(1, -1, "fix_unavailable"))
        assertFalse(LocationEvidence.retry(1, 30_000, "background_permission_required"))
    }
}
