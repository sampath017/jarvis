package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class SensingPolicyTest {
    @Test fun hardwareMovementStartsCollectionBeforeGoogleClassifiesWalking() {
        assertFalse(SensingPolicy.collect(true, "STILL", false))
        assertTrue(SensingPolicy.collect(true, "STILL", true))
        assertTrue(SensingPolicy.collect(true, "UNKNOWN", true))
        assertTrue(SensingPolicy.collect(true, "WALKING", false))
    }
    @Test fun quietPhoneStopsPollingButUnsupportedHardwareRetainsRecovery() {
        assertFalse(SensingPolicy.collect(true, "UNKNOWN", false))
        assertTrue(SensingPolicy.collect(false, "STILL", false))
    }
    @Test fun newHardwareMovementRequestsFreshPositionWithoutInventingAnActivityLabel() {
        assertTrue(LocationEvidence.preferFresh("UNKNOWN", "CONTEXT_CHECKPOINT", 1_000, 80_000, hardwareMotion = true))
        assertFalse(LocationEvidence.preferFresh("UNKNOWN", "CONTEXT_CHECKPOINT", 1_000, 80_000))
        assertFalse(LocationEvidence.preferFresh("UNKNOWN", "CONTEXT_CHECKPOINT", 90_000, 80_000, hardwareMotion = true))
        assertFalse(LocationEvidence.preferFresh("UNKNOWN", "CONTEXT_CHECKPOINT", 1_000, 2_000, hardwareMotion = true))
    }
    @Test fun everyNewMovementCanReactivateWithoutACooldown() {
        val first = 100_000L
        assertTrue(SensingPolicy.recentMotion(first, first + 59_000))
        assertFalse(SensingPolicy.recentMotion(first, first + 61_000))
        assertTrue(SensingPolicy.recentMotion(first + 61_001, first + 61_001))
        assertFalse(SensingPolicy.recentMotion(-1, 10))
        assertFalse(SensingPolicy.recentMotion(first, 100))
    }
    @Test fun wifiRequiresBothKnownIdentityAndUsableSignal() {
        assertTrue(SensingPolicy.nearKnownWifi(true, -55))
        assertFalse(SensingPolicy.nearKnownWifi(false, -45))
        assertFalse(SensingPolicy.nearKnownWifi(true, -85))
        assertFalse(SensingPolicy.nearKnownWifi(true, -127))
        assertFalse(SensingPolicy.nearKnownWifi(true, 0))
    }
}
