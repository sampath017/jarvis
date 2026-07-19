package com.jarvis.edge.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.jarvis.edge.data.remote.ContextEventRequest
import com.jarvis.edge.data.remote.FeatureSummary
import com.jarvis.edge.data.remote.LocationSnapshot

@Entity(tableName = "outbox_events")
data class OutboxEntity(
    @PrimaryKey val eventId: String,
    val occurredAt: String,
    val activity: String,
    val transition: String,
    
    // Nullable location fields
    val latitude: Double? = null,
    val longitude: Double? = null,
    val locationAccuracy: Float? = null,
    val locationSpeed: Float? = null,
    val locationBearing: Float? = null,
    
    // Nullable sensor features
    val dominantFreqHz: Double? = null,
    val spectralEnergy: Double? = null,
    val zRms: Double? = null,
    val harmonicRatio: Double? = null,
    val accelMagnitudeMean: Double? = null,
    val motionRms: Double? = null,
    val gyroRms: Double? = null,
    val vehicleClassHint: String? = null,
    val classificationConfidence: Double? = null,
    
    val sessionHint: String? = null
) {
    fun toRequest(): ContextEventRequest {
        val loc = if (latitude != null && longitude != null && locationAccuracy != null) {
            LocationSnapshot(
                latitude = latitude,
                longitude = longitude,
                accuracyM = locationAccuracy,
                speedMps = locationSpeed,
                bearingDeg = locationBearing,
                timestamp = occurredAt
            )
        } else null

        val feat = if (dominantFreqHz != null) {
            FeatureSummary(
                dominantFreqHz = dominantFreqHz,
                spectralEnergy = spectralEnergy ?: 0.0,
                zRms = zRms ?: 0.0,
                harmonicRatio = harmonicRatio ?: 0.0,
                accelMagnitudeMean = accelMagnitudeMean ?: 0.0,
                motionRms = motionRms ?: 0.0,
                gyroRms = gyroRms ?: 0.0,
                vehicleClassHint = vehicleClassHint ?: "",
                classificationConfidence = classificationConfidence ?: 0.0
            )
        } else null

        return ContextEventRequest(
            eventId = eventId,
            occurredAt = occurredAt,
            activity = activity,
            transition = transition,
            featureSummary = feat,
            location = loc,
            sessionHint = sessionHint
        )
    }

    companion object {
        fun fromRequest(req: ContextEventRequest): OutboxEntity {
            return OutboxEntity(
                eventId = req.eventId,
                occurredAt = req.occurredAt,
                activity = req.activity,
                transition = req.transition,
                latitude = req.location?.latitude,
                longitude = req.location?.longitude,
                locationAccuracy = req.location?.accuracyM,
                locationSpeed = req.location?.speedMps,
                locationBearing = req.location?.bearingDeg,
                dominantFreqHz = req.featureSummary?.dominantFreqHz,
                spectralEnergy = req.featureSummary?.spectralEnergy,
                zRms = req.featureSummary?.zRms,
                harmonicRatio = req.featureSummary?.harmonicRatio,
                accelMagnitudeMean = req.featureSummary?.accelMagnitudeMean,
                motionRms = req.featureSummary?.motionRms,
                gyroRms = req.featureSummary?.gyroRms,
                vehicleClassHint = req.featureSummary?.vehicleClassHint,
                classificationConfidence = req.featureSummary?.classificationConfidence,
                sessionHint = req.sessionHint
            )
        }
    }
}
