package com.jarvis.models

/**
 * Represents the current physical/environmental context of the user.
 * Combines location, motion, vehicle, and place data.
 */
data class JarvisContext(
    val timestamp: Long = System.currentTimeMillis(),
    val location: LocationContext? = null,
    val motion: MotionState = MotionState.UNKNOWN,
    val vehicleSession: VehicleSession? = null,
    val placeContext: PlaceContext? = null,
    val battery: BatteryContext? = null,
)

data class LocationContext(
    val latitude: Double,
    val longitude: Double,
    val accuracy: Float,
    val speed: Float = 0f,         // m/s
    val bearing: Float = 0f,
    val altitude: Double = 0.0,
    val provider: String = "fused",
)

enum class MotionState {
    UNKNOWN,
    STILL,
    WALKING,
    RUNNING,
    ON_BICYCLE,
    IN_VEHICLE,
    TILTING,
}

/**
 * Vehicle session tracks a specific vehicle ride from start to park to resume.
 * Implements the Stop-Shop-Return state machine from the Jarvis spec.
 */
data class VehicleSession(
    val sessionId: String,
    val vehicleIdentity: String,           // e.g. "Hunter_350"
    val confidence: Float,
    val state: VehicleSessionState,
    val startedAt: Long,
    val lastSeenAt: Long,
    val parkedLocation: LocationContext? = null,
)

enum class VehicleSessionState {
    IDLE,
    POSSIBLE_VEHICLE,
    CLASSIFYING_VEHICLE,
    ACTIVE_RIDING,
    PARKED_CANDIDATE,
    PARKED_NEARBY,
    RESUME_CHECK,
}

data class PlaceContext(
    val placeId: String? = null,
    val label: String,                     // e.g. "Home", "Grocery_Shop"
    val placeType: PlaceType,
    val confidence: Float,
    val evidence: List<String> = emptyList(),
    val dwellMinutes: Int = 0,
)

enum class PlaceType {
    HOME,
    OFFICE,
    FRIEND_HOUSE,
    SHOP,
    RESTAURANT,
    GYM,
    PHARMACY,
    UNKNOWN_ERRAND,
    CUSTOM,
}

data class BatteryContext(
    val level: Int,
    val isCharging: Boolean,
    val temperature: Float = 0f,
)
