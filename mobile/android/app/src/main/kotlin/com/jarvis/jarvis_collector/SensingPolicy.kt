package com.jarvis.jarvis_collector

/** Movement starts collection; it is not itself a walking/departure classification. */
object SensingPolicy {
    fun moving(activity: String) = activity in setOf("WALKING", "RUNNING", "ON_FOOT", "ON_BICYCLE", "IN_VEHICLE")
    fun recentMotion(observed: Long, now: Long) = observed >= 0 && now - observed in 0..60_000L
    fun collect(hardwareAvailable: Boolean, activity: String, motionRecent: Boolean) =
        !hardwareAvailable || moving(activity) || motionRecent
    fun nearKnownWifi(known: Boolean, rssi: Int) = known && rssi in -67..-1
}
