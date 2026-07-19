package com.jarvis.edge

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.google.firebase.FirebaseApp
import com.google.firebase.appcheck.FirebaseAppCheck
import com.google.firebase.appcheck.playintegrity.PlayIntegrityAppCheckProviderFactory

class JarvisApp : Application() {

    override fun onCreate() {
        super.onCreate()
        FirebaseApp.initializeApp(this)

        val firebaseAppCheck = FirebaseAppCheck.getInstance()
        firebaseAppCheck.installAppCheckProviderFactory(
            PlayIntegrityAppCheckProviderFactory.getInstance()
        )

        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)

            val transitChannel = NotificationChannel(
                CHANNEL_ID_TRANSITIONS,
                "Transit Tracking",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Notifies when Jarvis is sampling sensors or processing journeys"
            }

            val remindersChannel = NotificationChannel(
                CHANNEL_ID_REMINDERS,
                "Task Reminders",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "High-priority push notifications for location and activity reminders"
                enableVibration(true)
            }

            manager.createNotificationChannel(transitChannel)
            manager.createNotificationChannel(remindersChannel)
        }
    }

    companion object {
        const val CHANNEL_ID_TRANSITIONS = "jarvis_transition_channel"
        const val CHANNEL_ID_REMINDERS = "jarvis_reminders_channel"
    }
}

