package com.jarvis.jarvis_collector

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.Manifest
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.app.NotificationCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.jarvis/foreground_service"
    private val TAG = "JarvisMainActivity"
    private var legacyServiceCleared = false
    private var contextPermissionResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
        ActivityTransitionReceiver.sampleListener = { activity, confidence ->
            runOnUiThread {
                channel.invokeMethod("onActivitySample", mapOf("activity" to activity, "confidence" to confidence))
            }
        }

        // Wire listener from ActivityTransitionReceiver back to Flutter
        ActivityTransitionReceiver.transitionListener = { activity, transition ->
            runOnUiThread {
                channel.invokeMethod(
                    "onActivityTransition",
                    mapOf(
                        "activity" to activity,
                        "transition" to transition
                    )
                )
            }
        }

        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "requestContextPermissions" -> {
                    val needed = mutableListOf<String>()
                    if (Build.VERSION.SDK_INT >= 29 && checkSelfPermission(Manifest.permission.ACTIVITY_RECOGNITION) != PackageManager.PERMISSION_GRANTED) {
                        needed.add(Manifest.permission.ACTIVITY_RECOGNITION)
                    }
                    if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                        needed.add(Manifest.permission.POST_NOTIFICATIONS)
                    }
                    if (needed.isEmpty()) result.success(true)
                    else if (contextPermissionResult != null) result.success(false)
                    else {
                        contextPermissionResult = result
                        requestPermissions(needed.toTypedArray(), 4102)
                    }
                }
                "startService" -> {
                    val title = call.argument<String>("title") ?: "Jarvis Active"
                    val content = call.argument<String>("content") ?: "Collecting 50Hz sensor telemetry in background"

                    val intent = Intent(this, TelemetryForegroundService::class.java).apply {
                        action = TelemetryForegroundService.ACTION_START
                        putExtra(TelemetryForegroundService.EXTRA_TITLE, title)
                        putExtra(TelemetryForegroundService.EXTRA_CONTENT, content)
                    }

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        startForegroundService(intent)
                    } else {
                        startService(intent)
                    }
                    result.success(true)
                }
                "stopService" -> {
                    val intent = Intent(this, TelemetryForegroundService::class.java).apply {
                        action = TelemetryForegroundService.ACTION_STOP
                    }
                    stopService(intent)
                    result.success(true)
                }
                "startTripwire" -> {
                    if (!legacyServiceCleared) {
                        // Stop a persistent service left running by earlier app versions.
                        stopService(Intent(this, TelemetryForegroundService::class.java))
                        legacyServiceCleared = true
                    }
                    startActivityRecognitionUpdates(result)
                }
                "stopTripwire" -> {
                    stopActivityRecognitionUpdates(result)
                }
                "showSystemNotification" -> {
                    val id = call.argument<Int>("id") ?: ((System.currentTimeMillis() % 100000).toInt())
                    val title = call.argument<String>("title") ?: "Reminder"
                    val content = call.argument<String>("content") ?: call.argument<String>("body") ?: ""
                    showSystemNotification(id, title, content)
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 4102) {
            contextPermissionResult?.success(grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED })
            contextPermissionResult = null
        }
    }

    private fun showSystemNotification(id: Int, title: String, content: String) {
        val channelId = "jarvis_reminders_channel"
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Jarvis Reminders",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "System notifications for context reminders"
                enableLights(true)
                enableVibration(true)
            }
            notificationManager.createNotificationChannel(channel)
        }

        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = PendingIntent.getActivity(
            this,
            id,
            launchIntent,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            } else {
                PendingIntent.FLAG_UPDATE_CURRENT
            }
        )

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        notificationManager.notify(id, notification)
    }

    private fun startActivityRecognitionUpdates(result: MethodChannel.Result) {
        try {
            ActivityRecognitionRegistrar.register(this,
                onSuccess = {
                    Log.i(TAG, "Successfully registered Google Activity Recognition tripwire")
                    result.success(true)
                },
                onFailure = { e ->
                    Log.e(TAG, "Failed to register Google Activity Recognition tripwire: ${e.message}")
                    result.error("GAR_ERROR", e.message, null)
                },
            )
        } catch (e: Exception) {
            Log.e(TAG, "Exception starting tripwire: ${e.message}")
            result.error("GAR_EXCEPTION", e.message, null)
        }
    }

    private fun stopActivityRecognitionUpdates(result: MethodChannel.Result) {
        try {
            ActivityRecognitionRegistrar.unregister(this,
                onSuccess = {
                    Log.i(TAG, "Successfully removed Google Activity Recognition tripwire")
                    result.success(true)
                },
                onFailure = { e ->
                    result.error("GAR_ERROR", e.message, null)
                },
            )
        } catch (e: Exception) {
            result.error("GAR_EXCEPTION", e.message, null)
        }
    }
}
