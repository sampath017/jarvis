package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class MotionWindowTest {
    private fun stable(): MotionWindow = MotionWindow().apply {
        for (i in 0..74) sample(1_000L+i*200, 0.0, 0.0, 9.81)
    }
    @Test fun absentSensorsAreUnknown() {
        val result = MotionWindow().result(15_000)
        assertFalse(result.usable); assertEquals("UNKNOWN", result.candidate)
    }
    @Test fun recentStationaryPhoneIsOnlyAProvisionalStillCandidate() {
        val result = stable().result(16_000)
        assertTrue(result.usable); assertEquals("STILL", result.candidate)
    }
    @Test fun oldStationaryMeasurementsDoNotProveCurrentStillness() {
        assertEquals("UNKNOWN", stable().result(60_000).candidate)
    }
    @Test fun sensorSuspensionCannotBeHiddenByManySamples() {
        val window = stable()
        for (i in 0..74) window.sample(50_000L+i*200, 0.0, 0.0, 9.81)
        val result = window.result(65_000)
        assertFalse(result.usable); assertTrue(result.maxGapMs > 30_000)
    }
    @Test fun stepsDistinguishFootMotionWithoutClaimingWalkingOrRunning() {
        val window = stable(); repeat(4) { window.step() }
        assertEquals("ON_FOOT", window.result(16_000).candidate)
    }
    @Test fun highSpeedDoesNotLookLikeStillnessEvenWithStableAcceleration() {
        assertEquals("IN_VEHICLE", stable().result(16_000, 10.0).candidate)
        assertEquals("UNKNOWN", stable().result(16_000, 2.0).candidate)
    }
    @Test fun shakingDoesNotBecomeAConfidentTravelLabel() {
        val window = MotionWindow()
        for (i in 0..74) window.sample(1_000L+i*200, 0.0, 0.0, if (i%2 == 0) 8.0 else 12.0)
        assertEquals("UNKNOWN", window.result(16_000).candidate)
    }
    @Test fun invalidAndDuplicateSamplesDoNotCreateCoverage() {
        val window = MotionWindow()
        repeat(100) { window.sample(1_000, 0.0, 0.0, 9.8) }
        window.sample(2_000, Double.NaN, 0.0, 0.0)
        assertEquals(1, window.result(2_000).samples)
        assertFalse(window.result(2_000).usable)
    }
}
