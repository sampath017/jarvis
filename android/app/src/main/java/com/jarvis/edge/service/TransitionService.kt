package com.jarvis.edge.service

import android.app.Notification
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.android.gms.location.DetectedActivity
import com.jarvis.edge.JarvisApp
import com.jarvis.edge.data.local.OutboxDatabase
import com.jarvis.edge.data.local.OutboxEntity
import com.jarvis.edge.data.remote.ContextEventRequest
import com.jarvis.edge.data.remote.FeatureSummary
import com.jarvis.edge.data.remote.LocationSnapshot
import com.jarvis.edge.domain.classifier.VehicleClassifier
import com.jarvis.edge.domain.features.FeatureExtractor
import com.jarvis.edge.domain.sensors.LocationProvider
import com.jarvis.edge.domain.sensors.SensorSampler
import com.jarvis.edge.sync.SyncWorker
import kotlinx.coroutines.*
import kotlinx.coroutines.tasks.await

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class TransitionService : Service() {

    private val serviceJob = SupervisorJob()
    private val serviceScope = CoroutineScope(Dispatchers.IO + serviceJob)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val activityType = intent?.getIntExtra(EXTRA_ACTIVITY_TYPE, -1) ?: -1
        val transitionType = intent?.getIntExtra(EXTRA_TRANSITION_TYPE, -1) ?: -1

        startForeground(1001, createNotification())

        serviceScope.launch {
            try {
                handleTransitionEvent(activityType, transitionType)
            } catch (exception: Exception) {
                // A transition is best-effort telemetry. Never allow a failed
                // sensor, database, or network handoff to bring down the UI.
                Log.e(TAG, "Unable to process activity transition", exception)
            } finally {
                stopSelf()
            }
        }

        return START_NOT_STICKY
    }

    private suspend fun handleTransitionEvent(activityType: Int, transitionType: Int) {
        val activityStr = mapActivityTypeToString(activityType)
        val transitionStr = if (transitionType == 0) "ENTER" else "EXIT" // 0 is enter, 1 is exit
        
        val eventId = UUID.randomUUID().toString()
        val timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())

        // 1. Get GPS Location snapshot
        val locationProvider = LocationProvider(this)
        val location = locationProvider.getCurrentLocation()
        val locSnapshot = location?.let {
            LocationSnapshot(
                latitude = it.latitude,
                longitude = it.longitude,
                accuracyM = it.accuracy,
                speedMps = it.speed,
                bearingDeg = it.bearing,
                timestamp = timestamp
            )
        }

        // 2. After a low-power Activity Recognition transition, capture one
        // bounded 10-second accelerometer/gyroscope burst for verification.
        var featureSummary: FeatureSummary? = null
        if (activityType == DetectedActivity.IN_VEHICLE && transitionType == 0) {
            val sampler = SensorSampler(this)
            try {
                val rawData = withTimeout(12_000L) {
                    sampler.collectBurst(durationSec = 10.0, samplingRateHz = 50)
                }
                val features = FeatureExtractor.extractFeatures(rawData)
                val classification = VehicleClassifier.classify(features)
                
                featureSummary = FeatureSummary(
                    dominantFreqHz = features.dominantFreqHz,
                    spectralEnergy = features.spectralEnergy,
                    zRms = features.zRms,
                    harmonicRatio = features.harmonicRatio,
                    accelMagnitudeMean = features.accelMagnitudeMean,
                    motionRms = features.motionRms,
                    gyroRms = features.gyroRms,
                    vehicleClassHint = classification.vehicleClass,
                    classificationConfidence = classification.confidence
                )
            } catch (e: Exception) {
                // Sensor collection failed or was cancelled
            }
        }

        // 3. Assemble and cache outbox event
        val request = ContextEventRequest(
            eventId = eventId,
            occurredAt = timestamp,
            activity = activityStr,
            transition = transitionStr,
            featureSummary = featureSummary,
            location = locSnapshot
        )

        val db = OutboxDatabase.getDatabase(this)
        db.outboxDao().insertEvent(OutboxEntity.fromRequest(request))

        // 4. Trigger background sync immediately
        SyncWorker.enqueueSync(this)


        // 5. Evaluate active tasks for push notifications
        try {
            val uid = com.google.firebase.auth.FirebaseAuth.getInstance().currentUser?.uid
            if (uid != null) {
                val snapshot = com.google.firebase.firestore.FirebaseFirestore.getInstance()
                    .collection("users")
                    .document(uid)
                    .collection("tasks")
                    .get()
                    .await()

                for (doc in snapshot.documents) {
                    val task = doc.data ?: continue
                    val taskId = doc.id
                    val title = task["title"]?.toString().orEmpty()
                    val category = task["trigger_category"]?.toString().orEmpty()

                    val matchesCategory = category.isNotEmpty() &&
                        (category.equals(activityStr, ignoreCase = true) ||
                         (category.equals("walking", ignoreCase = true) && activityStr.equals("WALKING", ignoreCase = true)) ||
                         (category.equals("in_vehicle", ignoreCase = true) && activityStr.equals("IN_VEHICLE", ignoreCase = true)) ||
                         (category.equals("running", ignoreCase = true) && activityStr.equals("RUNNING", ignoreCase = true)))

                    if (matchesCategory && transitionType == 0) {
                        NotificationHelper.showReminderNotification(
                            context = this,
                            taskId = taskId,
                            title = "🔔 Reminder: $title",
                            message = "Triggered because you started $activityStr"
                        )
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Unable to check reminder triggers: ${e.message}")
        }
    }



    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, JarvisApp.CHANNEL_ID_TRANSITIONS)
            .setContentTitle("Jarvis active")
            .setContentText("Processing transit telemetry context...")
            .setSmallIcon(android.R.drawable.sym_def_app_icon)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun mapActivityTypeToString(type: Int): String {
        return when (type) {
            DetectedActivity.IN_VEHICLE -> "IN_VEHICLE"
            DetectedActivity.ON_BICYCLE -> "ON_BICYCLE"
            DetectedActivity.ON_FOOT -> "ON_FOOT"
            DetectedActivity.RUNNING -> "RUNNING"
            DetectedActivity.STILL -> "STILL"
            DetectedActivity.TILTING -> "TILTING"
            DetectedActivity.WALKING -> "WALKING"
            else -> "UNKNOWN"
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceJob.cancel()
    }

    companion object {
        private const val TAG = "TransitionService"
        const val EXTRA_ACTIVITY_TYPE = "activity_type"
        const val EXTRA_TRANSITION_TYPE = "transition_type"
    }
}
