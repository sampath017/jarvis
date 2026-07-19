package com.jarvis.edge.data.repository

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Small, device-local preferences used by the dashboard and motion tracker. */
class AppSettingsRepository(context: Context) {

    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE
    )

    private val _vehicleProfile = MutableStateFlow(
        preferences.getString(KEY_VEHICLE_PROFILE, PROFILE_AUTOMATIC) ?: PROFILE_AUTOMATIC
    )
    val vehicleProfile: StateFlow<String> = _vehicleProfile

    fun setVehicleProfile(profile: String) {
        preferences.edit().putString(KEY_VEHICLE_PROFILE, profile).apply()
        _vehicleProfile.value = profile
    }

    companion object {
        const val PROFILE_AUTOMATIC = "Automatic detection"
        const val PROFILE_HUNTER = "Hunter 350"
        const val PROFILE_MOTORCYCLE = "Other motorcycle"
        const val PROFILE_CAR = "Car"

        val vehicleProfiles = listOf(
            PROFILE_AUTOMATIC,
            PROFILE_HUNTER,
            PROFILE_MOTORCYCLE,
            PROFILE_CAR
        )

        private const val PREFERENCES_NAME = "jarvis_app_settings"
        private const val KEY_VEHICLE_PROFILE = "vehicle_profile"
    }
}
