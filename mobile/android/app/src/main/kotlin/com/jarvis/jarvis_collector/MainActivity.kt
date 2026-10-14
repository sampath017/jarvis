package com.jarvis.jarvis_collector

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.Manifest
import android.content.pm.PackageManager
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterFragmentActivity() {
    companion object {
        @Volatile var isVisible = false
        @Volatile var visibleThreadId = ""
        var chatUpdateListener: ((String) -> Unit)? = null
        private val localWork = java.util.concurrent.Executors.newSingleThreadExecutor()
    }
    private var usageChannel: MethodChannel? = null
    private var chatChannel: MethodChannel? = null
    private var calendarAuthorization: GoogleAccountAuthorization? = null
    private var driveAuthorization: GoogleAccountAuthorization? = null
    private var attachmentPicker: ChatAttachmentPicker? = null

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        calendarAuthorization?.onActivityResult(requestCode, resultCode, data)
        driveAuthorization?.onActivityResult(requestCode, resultCode, data)
        attachmentPicker?.onActivityResult(requestCode, resultCode, data)
    }

    override fun onResume() {
        super.onResume()
        isVisible = true
        val app = applicationContext
        localWork.execute {
            runCatching {
                UsageReporting.schedule(app)
                DatabaseBackup.schedule(app)
                ReminderAlerts.restore(app)
            }.onFailure { Log.w("JarvisStartup", "Could not restore scheduled alerts") }
        }
    }
    override fun onPause() { isVisible = false; super.onPause() }
    override fun onDestroy() { chatUpdateListener = null; chatChannel = null; usageChannel = null; super.onDestroy() }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra("jarvis_usage_day")?.let {
            usageChannel?.invokeMethod("openReport", it)
            intent.removeExtra("jarvis_usage_day")
        }
        intent.getStringExtra("jarvis_thread_id")?.takeIf { it.isNotEmpty() }?.let {
            chatChannel?.invokeMethod("openChat", it)
            intent.removeExtra("jarvis_thread_id")
        }
    }
    private val CHANNEL = "com.jarvis/foreground_service"
    private val TAG = "JarvisMainActivity"
    private var legacyServiceCleared = false
    private var contextPermissionResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis/context_runtime").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "configure" -> {
                        ContextEventQueue.configureApi(applicationContext, call.argument<String>("baseUrl")!!,
                            call.argument<String>("userId")!!)
                        result.success(ContextEventQueue.uploadStatus(applicationContext))
                    }
                    "status" -> result.success(ContextEventQueue.uploadStatus(applicationContext))
                    "flush" -> { ContextEventQueue.scheduleFlush(applicationContext); result.success(true) }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) {
                result.error("context_runtime_failed", error.message, null)
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis/database_backup").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(DatabaseBackup.status(applicationContext))
                    "configure" -> { DatabaseBackup.configure(applicationContext, call.arguments as Boolean); result.success(DatabaseBackup.status(applicationContext)) }
                    "backupNow" -> { DatabaseBackup.enqueue(applicationContext); result.success(DatabaseBackup.status(applicationContext)) }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) { result.error("backup_failed", error.message, null) }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis/power").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(JarvisPower.status(applicationContext))
                    "history" -> result.success(JarvisPower.history(applicationContext))
                    "setEnabled" -> { JarvisPower.setEnabled(applicationContext, call.arguments as Boolean); result.success(true) }
                    "setCloudConfirmed" -> { JarvisPower.cloudConfirmed(applicationContext, call.arguments as Boolean); result.success(true) }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) { result.error("power_failed", "Could not update phone power", null) }
        }
        calendarAuthorization = GoogleAccountAuthorization(this, flutterEngine.dartExecutor.binaryMessenger)
        driveAuthorization = GoogleAccountAuthorization(this, flutterEngine.dartExecutor.binaryMessenger, "drive")
        attachmentPicker = ChatAttachmentPicker(this, flutterEngine.dartExecutor.binaryMessenger)
        // An explicit maintenance launch establishes a new collection boundary.
        // Ordinary app launches preserve it, and Android redeliveries before it
        // are rejected by the transition and passive-location receivers.
        val resetAt = intent.getLongExtra("jarvis_history_reset_at", 0L)
        if (resetAt > 0L && resetAt <= System.currentTimeMillis()) {
            applicationContext.getSharedPreferences("jarvis_context_events", Context.MODE_PRIVATE)
                .edit().putLong("history_reset_at", resetAt).commit()
            intent.removeExtra("jarvis_history_reset_at")
        }
        usageChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis/usage")
        usageChannel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "status" -> result.success(UsageReporting.status(applicationContext))
                "takeInitialDay" -> { val day = intent.getStringExtra("jarvis_usage_day"); intent.removeExtra("jarvis_usage_day"); result.success(day) }
                "openAccess" -> { startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).setData(Uri.parse("package:$packageName"))); result.success(true) }
                "openExactAlarm" -> {
                    if (Build.VERSION.SDK_INT >= 31) startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")))
                    result.success(true)
                }
                "setEnabled" -> { UsageReporting.setEnabled(applicationContext, call.arguments as? Boolean ?: true); result.success(true) }
                "cachedDays", "refreshCache", "read", "savedReport" -> Thread {
                    try {
                        val cache = UsageHistory.get(applicationContext)
                        val data = when (call.method) {
                            "cachedDays" -> cache.all().toString()
                            "refreshCache" -> cache.refresh(applicationContext) { day, summary ->
                                runOnUiThread { usageChannel?.invokeMethod("usageDayUpdated",
                                    mapOf("day" to day, "data" to summary.toString())) }
                            }.toString()
                            else -> {
                                val day = java.time.LocalDate.parse(call.arguments as String)
                                if (call.method == "savedReport") UsageReporting.saved(applicationContext, day.toString())
                                    ?: UsageReporting.read(applicationContext, day, true).toString()
                                else {
                                    val saved = cache.day(day)
                                    val dayEnd = day.plusDays(1).atStartOfDay(UsageReporting.zone).toInstant().toEpochMilli()
                                    if (day < java.time.LocalDate.now(UsageReporting.zone) && saved != null &&
                                        saved.optInt("calculation_version") == 2 && saved.optLong("end_ms") >= dayEnd) saved.toString()
                                    else {
                                        val fresh = UsageReporting.read(applicationContext, day)
                                        cache.save(day, fresh)
                                        (if (fresh.has("error") && saved?.has("total_ms") == true) saved else fresh).toString()
                                    }
                                }
                            }
                        }
                        runOnUiThread { result.success(data) }
                    } catch (error: Exception) { runOnUiThread { result.error("usage_unavailable", "Could not read app usage", null) } }
                }.start()
                else -> result.notImplemented()
            }
        }
        chatChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis/chat_notifications")
        chatChannel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "takeInitialThread" -> {
                    val thread = intent.getStringExtra("jarvis_thread_id")
                    intent.removeExtra("jarvis_thread_id")
                    result.success(thread)
                }
                "setVisibleThread" -> { visibleThreadId = call.arguments as? String ?: ""; result.success(true) }
                else -> result.notImplemented()
            }
        }
        chatUpdateListener = { thread -> runOnUiThread { chatChannel?.invokeMethod("chatUpdated", thread) } }

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
            if (!JarvisPower.enabled(applicationContext) && call.method in setOf("startService", "startTripwire", "showNotification", "requestContextPermissions")) {
                result.error("powered_off", "Jarvis is powered off", null)
                return@setMethodCallHandler
            }
            when (call.method) {
                "contextLocationStatus" -> {
                    val foreground = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                        checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
                    val background = foreground && (Build.VERSION.SDK_INT < 29 ||
                        checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED)
                    val manager = getSystemService(Context.LOCATION_SERVICE) as android.location.LocationManager
                    result.success(mapOf("foreground" to foreground, "background" to background,
                        "enabled" to (manager.isProviderEnabled(android.location.LocationManager.GPS_PROVIDER) ||
                            manager.isProviderEnabled(android.location.LocationManager.NETWORK_PROVIDER))))
                }
                "motionDiagnostics" -> Thread {
                    try {
                        val data = TelemetryHistory.get(applicationContext).export(applicationContext).toString()
                        runOnUiThread { result.success(data) }
                    } catch (error: Exception) {
                        runOnUiThread { result.error("motion_unavailable", "Motion history is unavailable", null) }
                    }
                }.start()
                "labelMotion" -> {
                    val label = call.argument<String>("activity") ?: "UNKNOWN"
                    val placement = call.argument<String>("placement") ?: "other"
                    val started = call.argument<Long>("startedAt") ?: 0L
                    val startedElapsed = call.argument<Long>("startedElapsedMs") ?: -1L
                    val startBoot = call.argument<Int>("bootCount") ?: -1
                    val nowElapsed = android.os.SystemClock.elapsedRealtime()
                    val duration = nowElapsed-startedElapsed
                    if (label !in setOf("STILL", "WALKING", "RUNNING", "IN_VEHICLE", "ON_BICYCLE") ||
                        placement !in setOf("pocket", "hand", "bag", "mounted", "table", "other") ||
                        duration !in 1_000..7_200_000 || startBoot != EventTiming.boot(applicationContext) || started <= 0) {
                        result.error("invalid_label", "Start a new label and record for at least one second", null)
                    } else {
                        val data = org.json.JSONObject().apply {
                            put("id", "motion_${java.util.UUID.randomUUID()}")
                            put("timestamp", ContextEventQueue.occurredAt(started)); put("label_end_at", ContextEventQueue.occurredAt(started+duration))
                            put("source", "user_label"); put("candidate", label); put("placement", placement)
                            put("provisional", true); put("model_version", "user_annotation_v1")
                            put("boot_count", startBoot); put("observed_elapsed_ms", startedElapsed)
                            put("received_elapsed_ms", nowElapsed); put("delivery_delay_ms", duration)
                        }
                        TelemetryHistory.get(applicationContext).record(applicationContext, data)
                        ContextEventQueue.scheduleFlush(applicationContext)
                        result.success(true)
                    }
                }
                "motionClock" -> result.success(mapOf("bootCount" to EventTiming.boot(applicationContext),
                    "elapsedMs" to android.os.SystemClock.elapsedRealtime(), "wallMs" to System.currentTimeMillis()))
                "openLocationSettings" -> {
                    startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                    result.success(true)
                }
                "setDynamicMonitoring" -> {
                    ActivityRecognitionRegistrar.setDynamicMonitoring(applicationContext, call.arguments as? Boolean ?: false)
                    result.success(true)
                }
                "notificationsEnabled" -> {
                    val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                    result.success(manager.areNotificationsEnabled())
                }
                "openNotificationSettings" -> {
                    val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                            putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                        }
                    } else {
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
                    }
                    startActivity(intent)
                    result.success(true)
                }
                "requestContextPermissions" -> {
                    val needed = mutableListOf<String>()
                    if (Build.VERSION.SDK_INT >= 31) {
                        for (permission in listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)) {
                            if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) needed.add(permission)
                        }
                    }
                    if (checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
                        needed.add(Manifest.permission.READ_PHONE_STATE)
                    }
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
                "showCloudNotification" -> {
                    result.success(PushDelivery.show(this, call.argument<String>("id") ?: "",
                        call.argument<String>("title") ?: "Jarvis", call.argument<String>("body") ?: "",
                        call.argument<String>("thread_id") ?: "", call.argument<String>("kind") ?: "",
                        call.argument<String>("delivery_mode") ?: "notification", call.argument<String>("reminder_id") ?: "",
                        call.argument<String>("alarm_due_at") ?: "", call.argument<String>("occurred_at") ?: ""))
                }
                "mobileContext" -> {
                    val app = applicationContext
                    val payload = call.arguments as String
                    localWork.execute {
                        try {
                            val context = MobileRecords.context(app, org.json.JSONObject(payload)).toString()
                            runOnUiThread { result.success(context) }
                        } catch (e: Exception) {
                            runOnUiThread { result.error("local_storage", "Local context is unavailable", null) }
                        }
                    }
                }
                "syncRingingReminders" -> {
                    val app = applicationContext
                    val payload = call.arguments as? String ?: "[]"
                    localWork.execute {
                        try {
                            ReminderAlerts.reconcile(app, org.json.JSONArray(payload))
                            val status = ReminderAlerts.status(app)
                            runOnUiThread { result.success(status) }
                        } catch (e: Exception) {
                            runOnUiThread { result.error("local_storage", "Could not refresh reminders", null) }
                        }
                    }
                }
                "ringingStatus" -> result.success(ReminderAlerts.status(this))
                "openFullScreenAlerts" -> {
                    if (Build.VERSION.SDK_INT >= 34) startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName")))
                    result.success(true)
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
