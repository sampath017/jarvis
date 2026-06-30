package com.jarvis.models

/**
 * Events stored in Jarvis's event log for context history and reasoning.
 */
sealed class JarvisEvent {
    abstract val timestamp: Long
    abstract val eventType: String

    /**
     * Riding event – user is actively riding a classified vehicle.
     */
    data class RidingEvent(
        override val timestamp: Long = System.currentTimeMillis(),
        override val eventType: String = "RIDING",
        val vehicleIdentity: String,
        val vehicleConfidence: Float,
        val placeContext: String? = null,
        val activityApi: String = "IN_VEHICLE",
        val imuClassifier: String? = null,
        val gpsSource: String = "fused_location",
    ) : JarvisEvent()

    /**
     * Dwell event – user stopped and stayed at a location.
     */
    data class DwellEvent(
        override val timestamp: Long = System.currentTimeMillis(),
        override val eventType: String = "DWELL",
        val placeContext: String,
        val vehicleSession: String? = null,
        val parkedVehicle: String? = null,
        val distanceFromParkedVehicleM: Float = 0f,
        val dwellMinutes: Int = 0,
        val confidence: Float = 0f,
    ) : JarvisEvent()

    /**
     * Resume event – user resumed a previously parked vehicle session.
     */
    data class ResumeEvent(
        override val timestamp: Long = System.currentTimeMillis(),
        override val eventType: String = "RIDING_RESUME",
        val vehicleIdentity: String,
        val sessionAction: String = "resumed_previous_vehicle_session",
        val resumeConfidence: Float,
    ) : JarvisEvent()

    /**
     * Geofence event – user entered or exited a known place.
     */
    data class GeofenceEvent(
        override val timestamp: Long = System.currentTimeMillis(),
        override val eventType: String = "GEOFENCE",
        val placeLabel: String,
        val transition: GeofenceTransition,
    ) : JarvisEvent()

    /**
     * Generic context event for miscellaneous state changes.
     */
    data class ContextEvent(
        override val timestamp: Long = System.currentTimeMillis(),
        override val eventType: String = "CONTEXT_CHANGE",
        val description: String,
        val metadata: Map<String, String> = emptyMap(),
    ) : JarvisEvent()
}

enum class GeofenceTransition {
    ENTER,
    EXIT,
    DWELL,
}

/**
 * A task/reminder parsed by the LLM from user intent.
 */
data class JarvisTask(
    val id: String,
    val task: String,
    val triggerType: TaskTriggerType,
    val locationPhrase: String? = null,
    val vehicleContextRequired: String? = null,
    val isActive: Boolean = true,
    val createdAt: Long = System.currentTimeMillis(),
)

enum class TaskTriggerType {
    EXIT_GEOFENCE,
    ENTER_GEOFENCE,
    VEHICLE_START,
    VEHICLE_STOP,
    TIME_BASED,
    MANUAL,
}

/**
 * Resume confidence calculation result.
 */
data class ResumeConfidence(
    val previousVehicle: String,
    val pauseMinutes: Int,
    val distanceFromParkedPointM: Float,
    val placeContext: String?,
    val resumeConfidence: Float,
) {
    companion object {
        fun calculate(
            previousVehicleConfidence: Float,
            pauseMinutes: Int,
            distanceM: Float,
            maxTtlMinutes: Int = 45,
        ): Float {
            val timeDecay = (1f - (pauseMinutes.toFloat() / maxTtlMinutes)).coerceIn(0f, 1f)
            val distanceDecay = (1f - (distanceM / 500f)).coerceIn(0f, 1f)
            return previousVehicleConfidence * timeDecay * distanceDecay
        }
    }
}
