package com.jarvis.edge.domain.classifier

import com.jarvis.edge.data.remote.FeatureSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VehicleClassifierTest {

    @Test
    fun `stationary burst is never classified as Hunter`() {
        val classification = VehicleClassifier.classify(
            FeatureSummary(
                dominantFreqHz = 30.0,
                spectralEnergy = 0.15,
                zRms = 10.2,
                harmonicRatio = 0.30,
                motionRms = 0.04
            )
        )

        assertEquals("NOT_VEHICLE", classification.vehicleClass)
        assertFalse(classification.isMatch)
        assertEquals(0.0, classification.confidence, 0.0)
    }

    @Test
    fun `moving burst can still match the Hunter profile`() {
        val classification = VehicleClassifier.classify(
            FeatureSummary(
                dominantFreqHz = 30.0,
                spectralEnergy = 0.15,
                zRms = 10.2,
                harmonicRatio = 0.30,
                motionRms = 0.5
            )
        )

        assertEquals("HUNTER_350", classification.vehicleClass)
        assertTrue(classification.isMatch)
    }
}
