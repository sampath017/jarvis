package com.jarvis.jarvis_collector

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest

/** Wi-Fi joins/leaves trigger a context snapshot while the process is alive. */
object AmbientNetworkMonitor {
    private var callback: ConnectivityManager.NetworkCallback? = null
    @Synchronized fun start(context: Context) {
        if (callback != null) return
        val app = context.applicationContext
        val listener = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { changed(app, "WIFI_CONNECTED") }
            override fun onLost(network: Network) { changed(app, "WIFI_DISCONNECTED") }
        }
        try {
            (app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager)
                .registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), listener)
            callback = listener
        } catch (_: Exception) { /* Motion events still capture radio context. */ }
    }
    private fun changed(c: Context, type: String) {
        if (!ActivityRecognitionRegistrar.isEnabled(c)) return
        ContextEventQueue.add(c, ContextEventQueue.newEvent(type,
            ContextEventQueue.currentActivity(c).ifEmpty { "UNKNOWN" }, "ENTER"))
    }
    @Synchronized fun stop(c: Context) {
        callback?.let { listener -> runCatching {
            (c.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).unregisterNetworkCallback(listener)
        } }
        callback = null
    }
}
