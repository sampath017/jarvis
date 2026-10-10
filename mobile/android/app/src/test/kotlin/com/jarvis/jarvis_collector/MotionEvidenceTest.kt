package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class MotionEvidenceTest {
    @Test fun isolatedWalkingClaimIsNotAccepted() {
        assertEquals("UNKNOWN", MotionEvidence.accepted("WALKING", 100, 100000, "IN_VEHICLE", 100, 70000))
    }
    @Test fun twoRecentHighConfidenceVehicleSamplesAreAccepted() {
        assertEquals("IN_VEHICLE", MotionEvidence.accepted("IN_VEHICLE", 95, 100000, "IN_VEHICLE", 90, 70000))
        // Play Services can deliver distinct measurements faster than requested.
        assertEquals("STILL", MotionEvidence.accepted("STILL", 99, 74000, "STILL", 99, 70000))
    }
    @Test fun lowConfidenceOldAndDuplicateSamplesCannotConfirmActivity() {
        assertEquals("UNKNOWN", MotionEvidence.accepted("STILL", 70, 100000, "STILL", 90, 70000))
        assertEquals("UNKNOWN", MotionEvidence.accepted("STILL", 95, 300000, "STILL", 90, 70000))
        assertEquals("UNKNOWN", MotionEvidence.accepted("STILL", 95, 70000, "STILL", 90, 70000))
        assertFalse(MotionEvidence.fresh(1000, 122000))
        assertFalse(MotionEvidence.fresh(1000, 999))
    }
}
