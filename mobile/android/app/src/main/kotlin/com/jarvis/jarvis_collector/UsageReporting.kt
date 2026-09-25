package com.jarvis.jarvis_collector

import android.Manifest
import android.app.*
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process
import android.os.UserManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import org.json.JSONArray
import org.json.JSONObject
import java.time.*
import java.util.concurrent.TimeUnit

object UsageReporting {
    val zone: ZoneId = ZoneId.of("Asia/Kolkata")
    private fun prefs(c: Context) = c.getSharedPreferences("jarvis_usage", Context.MODE_PRIVATE)
    fun allowed(c: Context): Boolean {
        val ops = c.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        return ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), c.packageName) == AppOpsManager.MODE_ALLOWED
    }
    fun exact(c: Context) = Build.VERSION.SDK_INT < 31 || (c.getSystemService(Context.ALARM_SERVICE) as AlarmManager).canScheduleExactAlarms()
    fun enabled(c: Context) = prefs(c).getBoolean("enabled", true)
    fun status(c: Context) = mapOf("allowed" to allowed(c), "enabled" to enabled(c), "exact" to exact(c))
    fun setEnabled(c: Context, value: Boolean) { prefs(c).edit().putBoolean("enabled", value).commit(); schedule(c) }
    fun duration(ms: Long): String {
        if (ms == 0L) return "0 min"
        val minutes = ms / 60000
        return if (minutes < 1) "less than 1 min" else if (minutes < 60) "$minutes min" else "${minutes / 60}h ${minutes % 60}m"
    }
    fun read(c: Context, day: LocalDate, cutoff: Boolean = false): JSONObject {
        if (!allowed(c)) return JSONObject().put("error", "usage_access_required")
        if (!(c.getSystemService(Context.USER_SERVICE) as UserManager).isUserUnlocked) return JSONObject().put("error", "phone_locked_after_restart")
        val now = System.currentTimeMillis()
        val dayStart = day.atStartOfDay(zone).toInstant().toEpochMilli()
        // Screen time is a day total; activity-history resets do not clip Android's retained usage.
        val start = dayStart
        val end = minOf(now, (if (cutoff) day.atTime(23, 0).atZone(zone) else day.plusDays(1).atStartOfDay(zone)).toInstant().toEpochMilli())
        if (start >= end || day < LocalDate.now(zone).minusDays(6)) return JSONObject().put("error", "date_unavailable")
        val manager = c.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val events = manager.queryEvents(start - 86400000L, end) ?: return JSONObject().put("error", "records_unavailable")
        val counter = UsageAccumulator(start, end)
        val event = UsageEvents.Event()
        var count = 0
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.timeStamp >= start) count++
            when (event.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> counter.resume(event.packageName ?: "", event.className, event.timeStamp)
                UsageEvents.Event.ACTIVITY_PAUSED, UsageEvents.Event.ACTIVITY_STOPPED -> counter.pause(event.packageName ?: "", event.className, event.timeStamp)
                UsageEvents.Event.SCREEN_INTERACTIVE -> counter.screenOn(event.timeStamp)
                UsageEvents.Event.KEYGUARD_HIDDEN -> counter.unlock(event.timeStamp)
                UsageEvents.Event.KEYGUARD_SHOWN -> counter.lock(event.timeStamp)
                UsageEvents.Event.SCREEN_NON_INTERACTIVE,
                UsageEvents.Event.DEVICE_SHUTDOWN, UsageEvents.Event.DEVICE_STARTUP -> counter.screenOff(event.timeStamp)
            }
        }
        if (count == 0) return JSONObject().put("error", "no_records")
        val home = c.packageManager.resolveActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo?.packageName
        val apps = JSONArray()
        for ((pkg, ms) in counter.finish().entries.sortedByDescending { it.value }) {
            if (pkg.isBlank() || pkg == home || pkg == "com.android.systemui" || pkg == "android" || pkg == "com.miui.android.fashiongallery") continue
            val label = try { c.packageManager.getApplicationLabel(c.packageManager.getApplicationInfo(pkg, 0)).toString() } catch (_: Exception) { pkg }
            apps.put(JSONObject().put("package", pkg).put("name", label).put("milliseconds", ms))
        }
        val total = (0 until apps.length()).sumOf { apps.getJSONObject(it).getLong("milliseconds") }
        val text = buildString {
            val from = if (start == dayStart) "Midnight" else Instant.ofEpochMilli(start).atZone(zone).toLocalTime().withSecond(0).withNano(0).toString()
            append("App usage · $day\n$from to ${Instant.ofEpochMilli(end).atZone(zone).toLocalTime().withSecond(0).withNano(0)} IST\n")
            append("Day total screen time: ${if (total == 0L) "0 min" else duration(total)}\n\n")
            for (i in 0 until apps.length()) {
                val app = apps.getJSONObject(i)
                append("${i + 1}. ${app.getString("name")}: ${duration(app.getLong("milliseconds"))}\n")
            }
            append("\nEstimated from Android activity events. Excludes the home and lock screens; background audio and downloads are not screen time.")
        }
        return JSONObject().put("day", day.toString()).put("total_ms", total).put("apps", apps).put("text", text).put("start_ms", start).put("end_ms", end).put("calculation_version", 2)
    }
    fun scheduledDay(c: Context): String = Instant.ofEpochMilli(prefs(c).getLong("scheduled_at", System.currentTimeMillis())).atZone(zone).toLocalDate().toString()
    fun saved(c: Context, day: String): String? {
        val previous = prefs(c).getString("report:$day", null) ?: return null
        // Recompute older summaries with the corrected counter while raw records are retained.
        return if (JSONObject(previous).optInt("calculation_version") == 2) previous else null
    }
    private fun alarmIntent(c: Context) = PendingIntent.getBroadcast(c, 2300, Intent(c, UsageReportReceiver::class.java).setAction("com.jarvis.USAGE_REPORT"), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    fun schedule(c: Context) {
        val alarms = c.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarms.cancel(alarmIntent(c))
        WorkManager.getInstance(c).cancelUniqueWork("jarvis_usage_backup")
        if (!enabled(c)) return
        val now = ZonedDateTime.now(zone)
        val missed = prefs(c).getLong("scheduled_at", 0)
        if (missed > 0 && missed <= now.toInstant().toEpochMilli() && now.toInstant().toEpochMilli() - missed < 86400000L) {
            val day = Instant.ofEpochMilli(missed).atZone(zone).toLocalDate().toString()
            if (!prefs(c).getBoolean("sent:$day", false)) enqueue(c, day, 0, "jarvis_usage_catchup")
        }
        var next = now.toLocalDate().atTime(23, 0).atZone(zone)
        if (!next.isAfter(now)) next = next.plusDays(1)
        val at = next.toInstant().toEpochMilli()
        prefs(c).edit().putLong("scheduled_at", at).commit()
        try {
            if (exact(c)) alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, alarmIntent(c))
            else alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, alarmIntent(c))
        } catch (_: SecurityException) { alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, alarmIntent(c)) }
        enqueue(c, next.toLocalDate().toString(), at - System.currentTimeMillis() + 120000, "jarvis_usage_backup")
    }
    private fun enqueue(c: Context, day: String, delay: Long, name: String) {
        val work = OneTimeWorkRequestBuilder<UsageReportWorker>().setInputData(workDataOf("day" to day))
            .setInitialDelay(maxOf(0, delay), TimeUnit.MILLISECONDS).build()
        WorkManager.getInstance(c).enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, work)
    }
    @Synchronized fun deliver(c: Context, day: String): Boolean {
        if (!enabled(c) || prefs(c).getBoolean("sent:$day", false)) return true
        if (!allowed(c)) return true
        val report = read(c, LocalDate.parse(day), true)
        if (report.optString("error") == "before_reset") return true
        if (report.has("error")) return false
        prefs(c).edit().putString("report:$day", report.toString()).commit()
        val manager = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (!manager.areNotificationsEnabled() || (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(c, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)) return false
        manager.createNotificationChannel(NotificationChannel("jarvis_usage_reports", "Daily screen time", NotificationManager.IMPORTANCE_DEFAULT))
        if (manager.getNotificationChannel("jarvis_usage_reports").importance == NotificationManager.IMPORTANCE_NONE) return false
        val intent = Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra("jarvis_usage_day", day)
        val tap = PendingIntent.getActivity(c, day.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        manager.notify("usage:$day".hashCode(), NotificationCompat.Builder(c, "jarvis_usage_reports")
            .setSmallIcon(android.R.drawable.ic_menu_recent_history).setContentTitle("Your 11 PM screen-time report")
            .setContentText("${duration(report.getLong("total_ms"))} across your apps today")
            .setStyle(NotificationCompat.BigTextStyle().bigText(report.getString("text").take(3500)))
            .setContentIntent(tap).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build())
        prefs(c).edit().putBoolean("sent:$day", true).commit()
        // Retain a month of report summaries, not an indefinite event log.
        val oldest = LocalDate.now(zone).minusDays(31).toString()
        val editor = prefs(c).edit()
        prefs(c).all.keys.filter { (it.startsWith("report:") || it.startsWith("sent:")) && it.substringAfter(':') < oldest }.forEach { editor.remove(it) }
        editor.apply()
        return true
    }
}

class UsageReportReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "com.jarvis.USAGE_REPORT") { UsageReporting.schedule(context); return }
        val pending = goAsync()
        Thread {
            try { UsageReporting.deliver(context, UsageReporting.scheduledDay(context)) }
            catch (_: Exception) { /* Durable backup retries collection. */ }
            finally { try { UsageReporting.schedule(context) } finally { pending.finish() } }
        }.start()
    }
}
class UsageReportWorker(c: Context, p: WorkerParameters) : Worker(c, p) {
    override fun doWork(): Result { return try {
        val day = inputData.getString("day") ?: return Result.failure()
        if (UsageReporting.deliver(applicationContext, day)) Result.success() else if (runAttemptCount < 4) Result.retry() else Result.failure()
    } catch (_: Exception) { if (runAttemptCount < 4) Result.retry() else Result.failure() } }
}
