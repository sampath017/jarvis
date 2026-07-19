package com.jarvis.edge.data.remote

import com.google.gson.annotations.SerializedName

data class LocationSnapshot(
    @SerializedName("latitude") val latitude: Double,
    @SerializedName("longitude") val longitude: Double,
    @SerializedName("accuracy_m") val accuracyM: Float,
    @SerializedName("speed_mps") val speedMps: Float? = null,
    @SerializedName("bearing_deg") val bearingDeg: Float? = null,
    @SerializedName("timestamp") val timestamp: String
)

data class FeatureSummary(
    @SerializedName("dominant_freq_hz") val dominantFreqHz: Double = 0.0,
    @SerializedName("spectral_energy") val spectralEnergy: Double = 0.0,
    @SerializedName("z_rms") val zRms: Double = 0.0,
    @SerializedName("harmonic_ratio") val harmonicRatio: Double = 0.0,
    @SerializedName("accel_magnitude_mean") val accelMagnitudeMean: Double = 0.0,
    @SerializedName("motion_rms") val motionRms: Double = 0.0,
    @SerializedName("gyro_rms") val gyroRms: Double = 0.0,
    @SerializedName("vehicle_class_hint") val vehicleClassHint: String = "",
    @SerializedName("classification_confidence") val classificationConfidence: Double = 0.0
)

data class ContextEventRequest(
    @SerializedName("event_id") val eventId: String,
    @SerializedName("occurred_at") val occurredAt: String,
    @SerializedName("activity") val activity: String,
    @SerializedName("transition") val transition: String = "ENTER",
    @SerializedName("feature_summary") val featureSummary: FeatureSummary? = null,
    @SerializedName("location") val location: LocationSnapshot? = null,
    @SerializedName("session_hint") val sessionHint: String? = null
)

data class CommandRequest(
    @SerializedName("request_id") val requestId: String,
    @SerializedName("thread_id") val threadId: String,
    @SerializedName("text") val text: String,
    @SerializedName("current_context_ref") val currentContextRef: String? = null
)

data class APIResponse(
    @SerializedName("run_id") val runId: String,
    @SerializedName("status") val status: String,
    @SerializedName("message") val message: String,
    @SerializedName("changed_records") val changedRecords: List<String> = emptyList(),
    @SerializedName("session_id") val sessionId: String? = null,
    @SerializedName("error") val error: String? = null
)
