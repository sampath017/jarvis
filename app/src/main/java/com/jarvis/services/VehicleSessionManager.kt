package com.jarvis.services

import com.jarvis.models.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

/**
 * VehicleSessionManager implements the Stop-Shop-Return state machine
 * from the Jarvis Simulation document.
 *
 * State machine:
 *   IDLE → POSSIBLE_VEHICLE → CLASSIFYING_VEHICLE → ACTIVE_RIDING
 *   → PARKED_CANDIDATE → PARKED_NEARBY → RESUME_CHECK → ACTIVE_RIDING
 *
 * Manages parking session TTL and resume confidence.
 */
class VehicleSessionManager {

    private val _currentSession = MutableStateFlow<VehicleSession?>(null)
    val currentSession: StateFlow<VehicleSession?> = _currentSession.asStateFlow()

    private val _sessionHistory = MutableStateFlow<List<VehicleSession>>(emptyList())
    val sessionHistory: StateFlow<List<VehicleSession>> = _sessionHistory.asStateFlow()

    private val _events = MutableStateFlow<List<JarvisEvent>>(emptyList())
    val events: StateFlow<List<JarvisEvent>> = _events.asStateFlow()

    // TTL settings (in minutes)
    private val defaultErrandTtl = 45
    private val homeParkingTtl = 720       // 12 hours
    private val officeParkingTtl = 600     // 10 hours
    private val mallParkingTtl = 240       // 4 hours
    private val shortShopTtl = 30

    /**
     * Handle a motion state transition from the Activity Recognition API.
     */
    fun onMotionStateChanged(newState: MotionState, location: LocationContext?) {
        val session = _currentSession.value

        when {
            // No active session and user is now in vehicle → start classification
            session == null && newState == MotionState.IN_VEHICLE -> {
                startNewSession()
            }

            // Active session riding and user stops
            session != null &&
                session.state == VehicleSessionState.ACTIVE_RIDING &&
                (newState == MotionState.STILL || newState == MotionState.WALKING) -> {
                transitionTo(VehicleSessionState.PARKED_CANDIDATE, location)
            }

            // Parked candidate and user starts walking → confirmed park
            session != null &&
                session.state == VehicleSessionState.PARKED_CANDIDATE &&
                newState == MotionState.WALKING -> {
                transitionTo(VehicleSessionState.PARKED_NEARBY, location)
            }

            // Parked nearby and user gets back in vehicle → resume check
            session != null &&
                (session.state == VehicleSessionState.PARKED_NEARBY ||
                    session.state == VehicleSessionState.PARKED_CANDIDATE) &&
                newState == MotionState.IN_VEHICLE -> {
                transitionTo(VehicleSessionState.RESUME_CHECK, location)
            }
        }
    }

    /**
     * Called after a successful IMU classification burst.
     */
    fun onClassificationResult(result: ClassificationResult) {
        val session = _currentSession.value ?: return

        when (session.state) {
            VehicleSessionState.CLASSIFYING_VEHICLE -> {
                if (result.confidence > 0.6f) {
                    _currentSession.value = session.copy(
                        vehicleIdentity = result.vehicleIdentity,
                        confidence = result.confidence,
                        state = VehicleSessionState.ACTIVE_RIDING,
                    )
                    addEvent(
                        JarvisEvent.RidingEvent(
                            vehicleIdentity = result.vehicleIdentity,
                            vehicleConfidence = result.confidence,
                            imuClassifier = result.vehicleIdentity,
                        )
                    )
                } else {
                    // Low confidence – end session
                    endSession()
                }
            }

            VehicleSessionState.RESUME_CHECK -> {
                val resumeConf = calculateResumeConfidence(session)
                if (resumeConf > 0.7f || (result.isVerification && result.confidence > 0.6f)) {
                    // Resume the previous session
                    _currentSession.value = session.copy(
                        state = VehicleSessionState.ACTIVE_RIDING,
                        lastSeenAt = System.currentTimeMillis(),
                    )
                    addEvent(
                        JarvisEvent.ResumeEvent(
                            vehicleIdentity = session.vehicleIdentity,
                            resumeConfidence = resumeConf,
                        )
                    )
                } else {
                    // Different vehicle or expired – start fresh
                    endSession()
                    startNewSession()
                }
            }

            else -> {}
        }
    }

    /**
     * Start a new vehicle session.
     */
    private fun startNewSession() {
        val newSession = VehicleSession(
            sessionId = "vehicle_session_${UUID.randomUUID().toString().take(8)}",
            vehicleIdentity = "unknown",
            confidence = 0f,
            state = VehicleSessionState.CLASSIFYING_VEHICLE,
            startedAt = System.currentTimeMillis(),
            lastSeenAt = System.currentTimeMillis(),
        )
        _currentSession.value = newSession
    }

    /**
     * Transition the current session to a new state.
     */
    private fun transitionTo(newState: VehicleSessionState, location: LocationContext?) {
        val session = _currentSession.value ?: return

        _currentSession.value = when (newState) {
            VehicleSessionState.PARKED_CANDIDATE,
            VehicleSessionState.PARKED_NEARBY -> {
                session.copy(
                    state = newState,
                    lastSeenAt = System.currentTimeMillis(),
                    parkedLocation = location,
                )
            }
            else -> {
                session.copy(
                    state = newState,
                    lastSeenAt = System.currentTimeMillis(),
                )
            }
        }
    }

    /**
     * End the current session and archive it.
     */
    private fun endSession() {
        _currentSession.value?.let { session ->
            _sessionHistory.value = _sessionHistory.value + session
        }
        _currentSession.value = null
    }

    /**
     * Calculate resume confidence based on time decay and distance decay.
     */
    private fun calculateResumeConfidence(session: VehicleSession): Float {
        val pauseMinutes = ((System.currentTimeMillis() - session.lastSeenAt) / 60_000).toInt()
        val ttl = getTtlForContext(session)

        return ResumeConfidence.calculate(
            previousVehicleConfidence = session.confidence,
            pauseMinutes = pauseMinutes,
            distanceM = 0f, // Would need current location to calculate
            maxTtlMinutes = ttl,
        )
    }

    /**
     * Get TTL based on the place context where the vehicle is parked.
     */
    private fun getTtlForContext(session: VehicleSession): Int {
        // In production, this would check against known places
        return defaultErrandTtl
    }

    /**
     * Check if the current session has expired.
     */
    fun isSessionExpired(): Boolean {
        val session = _currentSession.value ?: return true
        if (session.state != VehicleSessionState.PARKED_NEARBY &&
            session.state != VehicleSessionState.PARKED_CANDIDATE
        ) return false

        val elapsedMinutes = ((System.currentTimeMillis() - session.lastSeenAt) / 60_000).toInt()
        return elapsedMinutes > getTtlForContext(session)
    }

    private fun addEvent(event: JarvisEvent) {
        _events.value = _events.value + event
    }
}
