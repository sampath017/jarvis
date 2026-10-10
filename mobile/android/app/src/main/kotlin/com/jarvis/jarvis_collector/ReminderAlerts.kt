package com.jarvis.jarvis_collector

import android.app.*
import android.content.*
import android.graphics.Color
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.WindowManager
import android.widget.*
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject

/** Android owns timing and looping audio, so neither Flutter nor a network request
 * needs to stay alive for a downloaded time alarm. Never uses the telephone API. */
object ReminderAlerts {
    private const val PREFS = "jarvis_ringing_alerts"
    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun manager(c: Context) = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private fun alarms(c: Context) = c.getSystemService(Context.ALARM_SERVICE) as AlarmManager
    fun epoch(value: String) = ReminderAlertPolicy.epoch(value)
    fun key(id: String, due: String) = ReminderAlertPolicy.key(id, due)
    fun ringing(mode: String) = ReminderAlertPolicy.ringing(mode)
    fun status(c: Context): Map<String, Any> = mapOf(
        "exact" to (Build.VERSION.SDK_INT < 31 || alarms(c).canScheduleExactAlarms()),
        "full_screen" to (Build.VERSION.SDK_INT < 34 || manager(c).canUseFullScreenIntent()),
        "notifications" to manager(c).areNotificationsEnabled(),
        "scheduled" to JSONObject(prefs(c).getString("scheduled", "{}")!!).length())

    private fun operation(c: Context, key: String) = PendingIntent.getBroadcast(c, 0,
        Intent(c, ReminderAlertReceiver::class.java).setAction("FIRE").setData(Uri.parse("jarvis-alert:" + Uri.encode(key)))
            .putExtra("key", key), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private fun screen(c: Context, key: String, answer: Boolean = false) = PendingIntent.getActivity(c, 0,
        Intent(c, ReminderAlertActivity::class.java).setData(Uri.parse("jarvis-alert:" + Uri.encode(key) + if (answer) ":answer" else ":show"))
            .putExtra("key", key).putExtra("answer", answer).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private fun action(c: Context, key: String, action: String) = PendingIntent.getBroadcast(c, 0,
        Intent(c, ReminderAlertReceiver::class.java).setAction(action).setData(Uri.parse("jarvis-alert:" + Uri.encode(key)))
            .putExtra("key", key), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private fun schedule(c: Context, key: String, at: Long): Boolean {
        if (Build.VERSION.SDK_INT >= 31 && !alarms(c).canScheduleExactAlarms()) return false
        return runCatching {
            val preview = PendingIntent.getActivity(c, 0, Intent(c, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            alarms(c).setAlarmClock(AlarmManager.AlarmClockInfo(at, preview), operation(c, key))
        }.isSuccess
    }

    /** Full authoritative snapshot; an absent, paused or edited alarm is cancelled. */
    @Synchronized fun reconcile(c: Context, records: JSONArray) {
        val p = prefs(c)
        val old = JSONObject(p.getString("scheduled", "{}")!!)
        val next = JSONObject()
        val reminders = (0 until records.length()).map { records.getJSONObject(it) }.associateBy { it.optString("id") }
        // Stop an already ringing alert when its reminder is removed or paused.
        for ((savedKey, value) in p.all) {
            if (!savedKey.startsWith("record:") || value !is String) continue
            val saved = runCatching { JSONObject(value) }.getOrNull() ?: continue
            val id = saved.optString("reminder_id")
            val current = reminders[id]
            if (id.isNotEmpty() && (current == null || current.optString("status") in listOf("PAUSED", "DELETED"))) {
                dismiss(c, saved.optString("key"))
            }
        }
        val snoozed = JSONObject(p.getString("snoozed", "{}")!!)
        for (key in snoozed.keys().asSequence().toList()) {
            val item = snoozed.getJSONObject(key)
            val id = item.optString("reminder_id")
            val current = reminders[id]
            if (id.isNotEmpty() && (current == null || current.optString("status") in listOf("PAUSED", "DELETED") ||
                    current.optString("delivery_mode", "notification") != item.optString("mode"))) {
                alarms(c).cancel(operation(c, key))
                snoozed.remove(key)
            }
        }
        p.edit().putString("snoozed", snoozed.toString()).commit()
        val now = System.currentTimeMillis()
        for (i in 0 until records.length()) {
            val r = records.getJSONObject(i)
            val mode = r.optString("delivery_mode", "notification")
            // Time + context is a conjunction; only the backend can decide it.
            val hasContext = r.optInt("activity_delay_seconds", 0) > 0 || listOf("activity", "location_name", "latitude", "longitude", "dynamic_policy").any {
                !r.isNull(it) && r.optString(it).isNotBlank()
            }
            val due = epoch(r.optString("due_at"))
            if (!ReminderAlertPolicy.timeOnly(mode, r.optString("status"), due, hasContext)) continue
            val key = key(r.getString("id"), r.getString("due_at"))
            if (p.contains("seen:$key")) continue
            val record = JSONObject().put("key", key).put("title", r.optString("title", "Jarvis"))
                .put("body", r.optString("body")).put("mode", mode).put("at", due).put("reminder_id", r.getString("id"))
            next.put(key, record)
        }
        for (key in old.keys()) if (!next.has(key)) alarms(c).cancel(operation(c, key))
        p.edit().putString("scheduled", next.toString()).commit()
        for (key in next.keys()) {
            val r = next.getJSONObject(key)
            val at = r.getLong("at")
            if (at <= now) fire(c, key) else schedule(c, key, at)
        }
    }

    @Synchronized fun restore(c: Context) {
        val p = prefs(c)
        for (bucket in listOf("scheduled", "snoozed")) {
            val records = JSONObject(p.getString(bucket, "{}")!!)
            for (key in records.keys()) {
                val at = records.getJSONObject(key).getLong("at")
                if (at <= System.currentTimeMillis()) fire(c, key) else schedule(c, key, at)
            }
        }
    }

    @Synchronized fun fire(c: Context, key: String) {
        val p = prefs(c)
        for (bucket in listOf("snoozed", "scheduled")) {
            val records = JSONObject(p.getString(bucket, "{}")!!)
            val r = records.optJSONObject(key) ?: continue
            if (r.getLong("at") > System.currentTimeMillis() + 1000) return
            if (show(c, key, r.optString("title"), r.optString("body"), r.optString("mode"), r.getLong("at"), r.optString("reminder_id"))) {
                records.remove(key)
                p.edit().putString(bucket, records.toString()).commit()
            }
            return
        }
    }

    fun record(c: Context, key: String): JSONObject? = prefs(c).getString("record:$key", null)?.let { JSONObject(it) }

    @Synchronized fun show(c: Context, key: String, title: String, body: String, mode: String, at: Long, reminderId: String = ""): Boolean {
        val p = prefs(c)
        if (p.contains("seen:$key")) return true
        val nm = manager(c)
        if (!nm.areNotificationsEnabled()) return false
        val call = mode == "in_app_call"
        val channelId = if (call) "jarvis_in_app_calls_v1" else "jarvis_alarms_v1"
        nm.createNotificationChannel(NotificationChannel(channelId,
            if (call) "Ringing reminder calls" else "Ringing alarms", NotificationManager.IMPORTANCE_HIGH).apply {
            setSound(RingtoneManager.getDefaultUri(if (call) RingtoneManager.TYPE_RINGTONE else RingtoneManager.TYPE_ALARM),
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
            enableVibration(true)
            lockscreenVisibility = Notification.VISIBILITY_PRIVATE
        })
        if (nm.getNotificationChannel(channelId).importance == NotificationManager.IMPORTANCE_NONE) return false
        val late = ReminderAlertPolicy.missed(at, System.currentTimeMillis())
        val record = JSONObject().put("key", key).put("title", title).put("body", body).put("mode", mode).put("at", at).put("reminder_id", reminderId)
        p.edit().putString("record:$key", record.toString()).commit()
        val builder = NotificationCompat.Builder(c, channelId)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle(if (late) "Missed reminder: $title" else if (call) "Jarvis calling · $title" else title)
            .setContentText(if (call) "In-app reminder · tap Answer to hear it" else body)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX).setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(screen(c, key)).setOnlyAlertOnce(true)
            .addAction(0, "Dismiss", action(c, key, "DISMISS"))
        if (!late) {
            builder.setFullScreenIntent(screen(c, key), true).setTimeoutAfter(120_000)
                .addAction(0, "Snooze 5 min", action(c, key, "SNOOZE"))
            if (call) builder.addAction(0, "Answer", screen(c, key, true))
        } else builder.setSilent(true)
        val notification = builder.build()
        if (!late) notification.flags = notification.flags or Notification.FLAG_INSISTENT
        return runCatching {
            nm.notify(key, 1, notification)
            p.edit().putLong("seen:$key", System.currentTimeMillis()).commit()
            true
        }.getOrDefault(false)
    }

    fun dismiss(c: Context, key: String) { manager(c).cancel(key, 1) }
    @Synchronized fun snooze(c: Context, key: String): Boolean {
        val r = record(c, key) ?: return false
        if (prefs(c).contains("snoozeOf:$key")) { dismiss(c, key); return true }
        val at = System.currentTimeMillis() + 5 * 60_000
        val nextKey = "$key:snooze:$at"
        val p = prefs(c)
        val records = JSONObject(p.getString("snoozed", "{}")!!)
        records.put(nextKey, r.put("key", nextKey).put("at", at))
        p.edit().putString("snoozed", records.toString()).commit()
        if (!schedule(c, nextKey, at)) {
            records.remove(nextKey)
            p.edit().putString("snoozed", records.toString()).commit()
            return false
        }
        dismiss(c, key)
        p.edit().putString("snoozeOf:$key", nextKey).commit()
        return true
    }
}

class ReminderAlertReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, intent: Intent) {
        val key = intent.getStringExtra("key") ?: ""
        when (intent.action) {
            "FIRE" -> ReminderAlerts.fire(c, key)
            "DISMISS" -> ReminderAlerts.dismiss(c, key)
            "SNOOZE" -> if (!ReminderAlerts.snooze(c, key)) Toast.makeText(c, "Allow Alarms & reminders in Jarvis settings to snooze", Toast.LENGTH_LONG).show()
            else -> ReminderAlerts.restore(c)
        }
    }
}

class ReminderAlertActivity : Activity(), TextToSpeech.OnInitListener {
    private var speech: TextToSpeech? = null
    private var spoken = ""
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true) }
        else window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        val key = intent.getStringExtra("key") ?: run { finish(); return }
        val r = ReminderAlerts.record(this, key) ?: run { finish(); return }
        val call = r.optString("mode") == "in_app_call"
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(40, 70, 40, 70); setBackgroundColor(Color.rgb(16, 24, 40))
        }
        fun text(value: String, size: Float) { layout.addView(TextView(this).apply { text = value; textSize = size; setTextColor(Color.WHITE); gravity = Gravity.CENTER; setPadding(0, 16, 0, 16) }) }
        fun button(label: String, action: () -> Unit) { layout.addView(Button(this).apply { text = label; setOnClickListener { action() } }) }
        text(if (call) "Jarvis · In-app reminder call" else "Jarvis alarm", 22f)
        text(r.optString("title"), 30f)
        text(r.optString("body"), 18f)
        fun answer() {
            ReminderAlerts.dismiss(this, key)
            spoken = r.optString("title") + ". " + r.optString("body")
            if (speech == null) speech = TextToSpeech(this, this)
        }
        if (call) button("Answer · Read reminder") { answer() }
        button("Snooze 5 minutes") {
            if (ReminderAlerts.snooze(this, key)) finish()
            else Toast.makeText(this, "Allow Alarms & reminders in Jarvis settings first", Toast.LENGTH_LONG).show()
        }
        button("Dismiss") { ReminderAlerts.dismiss(this, key); finish() }
        setContentView(layout)
        if (intent.getBooleanExtra("answer", false)) answer()
    }
    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            // Use an installed offline voice; never invoke a paid/network voice API.
            val voice = speech?.voices?.firstOrNull { !it.isNetworkConnectionRequired && it.locale.language == "en" }
            if (voice != null) { speech?.voice = voice; speech?.speak(spoken, TextToSpeech.QUEUE_FLUSH, null, "reminder") }
            else Toast.makeText(this, "Install an English offline voice to hear reminders", Toast.LENGTH_LONG).show()
        }
    }
    override fun onDestroy() { speech?.stop(); speech?.shutdown(); super.onDestroy() }
}
