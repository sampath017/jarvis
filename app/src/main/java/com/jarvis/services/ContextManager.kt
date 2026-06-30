package com.jarvis.services

import android.annotation.SuppressLint
import android.content.Context
import android.location.Geocoder
import android.os.Looper
import com.google.android.gms.location.*
import com.jarvis.models.LocationContext
import com.jarvis.models.PlaceContext
import com.jarvis.models.PlaceType
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.*

/**
 * ContextManager gathers environmental context from native Android APIs:
 * - Fused Location Provider for GPS
 * - Geocoder for reverse geocoding
 * - Personal place memory for semantic place classification
 *
 * Implements the location/place context layer from the Jarvis Simulation doc.
 */
class ContextManager(private val context: Context) {

    private val fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
    private val geocoder = Geocoder(context, Locale.getDefault())

    private val _currentLocation = MutableStateFlow<LocationContext?>(null)
    val currentLocation: StateFlow<LocationContext?> = _currentLocation.asStateFlow()

    private val _currentPlace = MutableStateFlow<PlaceContext?>(null)
    val currentPlace: StateFlow<PlaceContext?> = _currentPlace.asStateFlow()

    private val _isTracking = MutableStateFlow(false)
    val isTracking: StateFlow<Boolean> = _isTracking.asStateFlow()

    // Personal place memory – known labelled locations
    private val knownPlaces = mutableListOf<KnownPlace>()

    private var locationCallback: LocationCallback? = null

    /**
     * Start continuous location tracking.
     */
    @SuppressLint("MissingPermission")
    fun startLocationTracking() {
        val request = LocationRequest.Builder(
            Priority.PRIORITY_HIGH_ACCURACY,
            5_000L // update every 5 seconds
        ).apply {
            setMinUpdateIntervalMillis(2_000L)
            setWaitForAccurateLocation(false)
        }.build()

        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.lastLocation?.let { location ->
                    val locContext = LocationContext(
                        latitude = location.latitude,
                        longitude = location.longitude,
                        accuracy = location.accuracy,
                        speed = location.speed,
                        bearing = location.bearing,
                        altitude = location.altitude,
                        provider = location.provider ?: "fused",
                    )
                    _currentLocation.value = locContext

                    // Resolve place context
                    resolvePlace(locContext)
                }
            }
        }

        locationCallback = callback
        fusedLocationClient.requestLocationUpdates(request, callback, Looper.getMainLooper())
        _isTracking.value = true
    }

    /**
     * Stop location tracking.
     */
    fun stopLocationTracking() {
        locationCallback?.let { fusedLocationClient.removeLocationUpdates(it) }
        locationCallback = null
        _isTracking.value = false
    }

    /**
     * Resolve the semantic meaning of a location.
     * Checks personal place memory first, then falls back to geocoding.
     */
    private fun resolvePlace(location: LocationContext) {
        // Check personal known places first
        val matchedPlace = knownPlaces.find { place ->
            distanceBetween(
                location.latitude, location.longitude,
                place.latitude, place.longitude
            ) < place.radiusM
        }

        if (matchedPlace != null) {
            _currentPlace.value = PlaceContext(
                placeId = matchedPlace.id,
                label = matchedPlace.label,
                placeType = matchedPlace.type,
                confidence = 0.95f,
                evidence = listOf("matched_known_place", "radius=${matchedPlace.radiusM}m"),
            )
            return
        }

        // Fallback: try reverse geocode
        try {
            @Suppress("DEPRECATION")
            val addresses = geocoder.getFromLocation(location.latitude, location.longitude, 1)
            if (!addresses.isNullOrEmpty()) {
                val address = addresses[0]
                _currentPlace.value = PlaceContext(
                    label = address.featureName ?: address.getAddressLine(0) ?: "Unknown",
                    placeType = PlaceType.UNKNOWN_ERRAND,
                    confidence = 0.5f,
                    evidence = listOf("reverse_geocode"),
                )
            }
        } catch (_: Exception) {
            // Geocoding failure – keep previous place context
        }
    }

    /**
     * Add a known personal place to memory.
     */
    fun addKnownPlace(
        id: String,
        label: String,
        latitude: Double,
        longitude: Double,
        radiusM: Float = 100f,
        type: PlaceType = PlaceType.CUSTOM,
    ) {
        knownPlaces.add(
            KnownPlace(id, label, latitude, longitude, radiusM, type)
        )
    }

    /**
     * Remove a known place.
     */
    fun removeKnownPlace(id: String) {
        knownPlaces.removeAll { it.id == id }
    }

    /**
     * Get all known places.
     */
    fun getKnownPlaces(): List<KnownPlace> = knownPlaces.toList()

    /**
     * Calculate distance between two coordinates in meters (Haversine).
     */
    private fun distanceBetween(
        lat1: Double, lon1: Double,
        lat2: Double, lon2: Double,
    ): Float {
        val results = FloatArray(1)
        android.location.Location.distanceBetween(lat1, lon1, lat2, lon2, results)
        return results[0]
    }
}

data class KnownPlace(
    val id: String,
    val label: String,
    val latitude: Double,
    val longitude: Double,
    val radiusM: Float = 100f,
    val type: PlaceType = PlaceType.CUSTOM,
)
