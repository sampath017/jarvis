package com.jarvis.jarvis_collector

import android.app.*
import android.content.*
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import androidx.core.app.NotificationCompat
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.UUID

/** Personal clock is local and deliberately independent of JarvisPower. */
object JarvisClock {
    const val PREFS = "jarvis_clock"
    const val TAG = "jarvis_clock"
    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun load(c: Context) = JSONObject(prefs(c).getString("state", null) ?: """{"version":1,"alarms":[],"timers":[],"zones":["Asia/Kolkata","Europe/London","America/New_York"],"stopwatch":{"elapsed":0,"running":false,"laps":[]},"bedtime":{},"settings":{"snoozeMinutes":10,"silenceMinutes":10,"volume":1.0,"gradual":false,"volumeAction":"snooze"}}""")
    private fun save(c: Context, s: JSONObject) { check(prefs(c).edit().putString("state", s.toString()).commit()) }
    private fun manager(c: Context) = c.getSystemService(AlarmManager::class.java)
    private fun boot(c: Context) = EventTiming.boot(c)
    private fun remaining(c: Context, t: JSONObject) = if(t.optString("status") == "running") ClockPolicy.remaining(t.optLong("endElapsed"), t.optLong("endWall"), t.optInt("boot", -1), boot(c), SystemClock.elapsedRealtime(), System.currentTimeMillis()) else t.optLong("remaining", t.optLong("duration"))
    private fun elapsed(c: Context, sw: JSONObject) = if (sw.optBoolean("running")) ClockPolicy.measured(sw.optLong("elapsed"), sw.optLong("startedElapsed"), sw.optLong("startedWall"), sw.optInt("boot", -1), boot(c), SystemClock.elapsedRealtime(), System.currentTimeMillis()) else sw.optLong("elapsed")
    private fun days(a: JSONObject): Set<Int> = a.optJSONArray("days")?.let { arr -> (0 until arr.length()).map { arr.getInt(it) }.toSet() } ?: emptySet()
    private fun operation(c: Context, id: String, action: String = "fire") = PendingIntent.getBroadcast(c, 0, Intent(c, ClockReceiver::class.java).setAction(action).setData(Uri.parse("jarvis-clock:"+Uri.encode(id))).putExtra("id", id), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    fun open(c: Context): PendingIntent = PendingIntent.getActivity(c, 5701, Intent(c, MainActivity::class.java).putExtra("jarvis_clock",true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun ensureTiming(c: Context) {
        require(Build.VERSION.SDK_INT < 31 || manager(c).canScheduleExactAlarms()) { "Allow Alarms & reminders for Jarvis in Clock permissions before starting an alarm or timer." }
        require(c.getSystemService(NotificationManager::class.java).areNotificationsEnabled()) { "Allow Jarvis notifications before starting an alarm or timer." }
    }
    private fun schedule(c: Context, item: JSONObject, timer: Boolean) {
        val id = item.getString("id")
        if (timer) {
            if (item.optString("status") != "running") { manager(c).cancel(operation(c,id)); return }
            manager(c).setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime()+remaining(c,item),operation(c,id))
        } else {
            manager(c).cancel(operation(c,id))
            if (!item.optBoolean("enabled")) return
            manager(c).setAlarmClock(AlarmManager.AlarmClockInfo(item.getLong("nextAt"), open(c)),operation(c,id))
        }
    }
    private fun find(s: JSONObject, id: String): Pair<String,JSONObject> {
        for (key in listOf("alarms","timers")) {
            val rows=s.getJSONArray(key)
            for(i in 0 until rows.length()) if(rows.getJSONObject(i).getString("id")==id) return key to rows.getJSONObject(i)
        }
        error("Clock item no longer exists")
    }
    private fun timerStart(c: Context,t:JSONObject,ms:Long) {
        require(ms>0 && ms<=31_536_000_000L) { "Choose a timer from one second to one year." }
        t.put("remaining",ms).put("ringing",false).put("status","running").put("endElapsed",SystemClock.elapsedRealtime()+ms).put("endWall",System.currentTimeMillis()+ms).put("boot",boot(c))
    }
    private fun timerNotifications(c: Context,s: JSONObject) {
        val nm=c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("jarvis_clock_countdown","Running timers",NotificationManager.IMPORTANCE_LOW).apply {setSound(null,null)})
        val timers=s.getJSONArray("timers")
        for(i in 0 until timers.length()) {
            val t=timers.getJSONObject(i);val id=t.getString("id");val status=t.optString("status")
            if(status !in listOf("running","paused")) {if(status!="ringing") nm.cancel(TAG,id.hashCode());continue}
            val running=status=="running"
            val toggle=operation(c,id,if(running)"timer.pause" else "timer.resume")
            val notification=NotificationCompat.Builder(c,"jarvis_clock_countdown").setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setContentTitle(t.optString("label","Timer")).setContentText(if(running)"Timer running" else "Timer paused")
                .setWhen(System.currentTimeMillis()+remaining(c,t)).setUsesChronometer(running).setChronometerCountDown(true)
                .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open(c))
                .addAction(0,if(running)"Pause" else "Resume",toggle).addAction(0,"+1 min",operation(c,id,"timer.add"))
                .addAction(0,"Stop",operation(c,id,"timer.reset")).build()
            nm.notify(TAG,id.hashCode(),notification)
        }
    }
    @Synchronized fun snapshot(c: Context): JSONObject {
        val s=load(c)
        val timers=s.getJSONArray("timers")
        for(i in 0 until timers.length()) timers.getJSONObject(i).put("remaining",remaining(c,timers.getJSONObject(i)))
        s.getJSONObject("stopwatch").put("displayElapsed",elapsed(c,s.getJSONObject("stopwatch")))
        val now=Instant.now(); val local=now.atZone(ZoneId.systemDefault())
        val worlds=JSONArray()
        val zones=s.getJSONArray("zones")
        for(i in 0 until zones.length()) runCatching {
            val id=zones.getString(i); val z=now.atZone(ZoneId.of(id))
            worlds.put(JSONObject().put("id",id).put("city",id.substringAfterLast('/').replace('_',' ')).put("time",z.format(DateTimeFormatter.ofPattern("HH:mm:ss"))).put("date",z.format(DateTimeFormatter.ofPattern("EEE, d MMM"))).put("offset",z.offset.id).put("differenceMinutes",(z.offset.totalSeconds-local.offset.totalSeconds)/60))
        }
        s.put("worlds",worlds).put("localTime",local.format(DateTimeFormatter.ofPattern("HH:mm:ss"))).put("localDate",local.format(DateTimeFormatter.ofPattern("EEEE, d MMMM")))
        s.put("permissions",JSONObject().put("exact",Build.VERSION.SDK_INT<31 || manager(c).canScheduleExactAlarms()).put("notifications",c.getSystemService(NotificationManager::class.java).areNotificationsEnabled()).put("fullScreen",Build.VERSION.SDK_INT<34 || c.getSystemService(NotificationManager::class.java).canUseFullScreenIntent()))
        return s
    }
    @Synchronized fun execute(c: Context,action: String, a: JSONObject): JSONObject {
        if(action=="snapshot") return snapshot(c)
        if(action=="zones") return JSONObject().put("zones",JSONArray(ZoneId.getAvailableZoneIds().sorted()))
        val s=load(c); val now=System.currentTimeMillis()
        val requestId=a.optString("__requestId")
        val receipts=s.optJSONObject("receipts") ?: JSONObject()
        if(requestId.isNotBlank() && receipts.has(requestId)) return snapshot(c).put("status","ok").put("replayed",true)
        val prior=JSONObject(s.toString())
        when(action) {
            "alarm.save" -> {
                ensureTiming(c)
                val id=a.optString("id").ifBlank { "alarm_"+UUID.randomUUID() }
                val alarm=runCatching { find(s,id).second }.getOrNull() ?: JSONObject().put("id",id).also { s.getJSONArray("alarms").put(it) }
                val h=a.getInt("hour");val m=a.getInt("minute");val selected=a.optJSONArray("days") ?: JSONArray()
                val next=ClockPolicy.nextAlarm(h,m,(0 until selected.length()).map { selected.getInt(it) }.toSet(),now)
                alarm.put("hour",h).put("minute",m).put("days",selected).put("label",a.optString("label","Alarm").take(120)).put("enabled",a.optBoolean("enabled",true)).put("vibrate",a.optBoolean("vibrate",true)).put("sound",a.optString("sound")).put("ringing",false).put("nextAt",next)
            }
            "alarm.toggle","alarm.skip" -> {
                val item=find(s,a.getString("id")).second
                val enabled=if(action=="alarm.skip") item.optBoolean("enabled") && days(item).isNotEmpty() else a.getBoolean("enabled")
                if(enabled) ensureTiming(c)
                item.put("enabled",enabled).put("ringing",false)
                if(enabled) item.put("nextAt",ClockPolicy.nextAlarm(item.getInt("hour"),item.getInt("minute"),days(item),if(action=="alarm.skip") maxOf(now,item.optLong("nextAt")) else now))
            }
            "timer.start" -> {
                ensureTiming(c)
                val ms=Math.multiplyExact(a.getLong("seconds"),1000L)
                val t=JSONObject().put("id","timer_"+UUID.randomUUID()).put("label",a.optString("label","Timer").take(120)).put("duration",ms).put("vibrate",true)
                timerStart(c,t,ms);s.getJSONArray("timers").put(t)
            }
            "timer.pause","timer.resume","timer.reset","timer.add" -> {
                val t=find(s,a.getString("id")).second
                when(action) {
                    "timer.pause" -> t.put("remaining",remaining(c,t)).put("ringing",false).put("status","paused")
                    "timer.resume" -> { ensureTiming(c); val remain=t.optLong("remaining");timerStart(c,t,if(remain>0) remain else t.getLong("duration")) }
                    "timer.reset" -> t.put("remaining",t.getLong("duration")).put("ringing",false).put("status","ready")
                    "timer.add" -> { ensureTiming(c); val ms=remaining(c,t)+a.optLong("seconds",60)*1000; if(t.optString("status")=="paused" || t.optString("status")=="ready") { require(ms>0);t.put("remaining",ms) } else timerStart(c,t,ms) }
                }
            }
            "delete" -> {
                val id=a.getString("id");val (key,_)=find(s,id);val rows=s.getJSONArray(key)
                s.put(key,JSONArray((0 until rows.length()).map { rows.getJSONObject(it) }.filter { it.getString("id")!=id }))
                manager(c).cancel(operation(c,id))
                c.getSystemService(NotificationManager::class.java).cancel(TAG,id.hashCode())
            }
            "dismiss","snooze" -> {
                val (key,t)=find(s,a.getString("id"));t.put("ringing",false)
                if(action=="snooze") {
                    ensureTiming(c); val ms=s.getJSONObject("settings").optLong("snoozeMinutes",10)*60_000
                    if(key=="timers") timerStart(c,t,ms) else t.put("enabled",true).put("nextAt",now+ms)
                } else if(key=="timers") t.put("status","finished").put("remaining",0)
                c.getSystemService(NotificationManager::class.java).cancel(TAG,t.getString("id").hashCode())
            }
            "stopwatch.start","stopwatch.pause","stopwatch.reset","stopwatch.lap" -> {
                val sw=s.getJSONObject("stopwatch");val value=elapsed(c,sw)
                when(action) {
                    "stopwatch.start" -> if(!sw.optBoolean("running")) sw.put("running",true).put("startedElapsed",SystemClock.elapsedRealtime()).put("startedWall",now).put("boot",boot(c))
                    "stopwatch.pause" -> sw.put("elapsed",value).put("running",false)
                    "stopwatch.reset" -> sw.put("elapsed",0).put("running",false).put("laps",JSONArray())
                    "stopwatch.lap" -> if(sw.optBoolean("running")) sw.getJSONArray("laps").put(value)
                }
            }
            "world.add" -> { val id=a.getString("zone");ZoneId.of(id); val zs=s.getJSONArray("zones");if((0 until zs.length()).none { zs.getString(it)==id }) zs.put(id) }
            "world.remove" -> { val zs=s.getJSONArray("zones");s.put("zones",JSONArray((0 until zs.length()).map { zs.getString(it) }.filter { it!=a.getString("zone") })) }
            "settings.save" -> {
                val settings=s.getJSONObject("settings")
                if(a.has("snoozeMinutes")) { require(a.getInt("snoozeMinutes") in 1..60);settings.put("snoozeMinutes",a.getInt("snoozeMinutes")) }
                if(a.has("silenceMinutes")) { require(a.getInt("silenceMinutes") in 1..60);settings.put("silenceMinutes",a.getInt("silenceMinutes")) }
                if(a.has("volume")) { val v=a.getDouble("volume");require(v.isFinite() && v in 0.0..1.0);settings.put("volume",v) }
                if(a.has("gradual")) settings.put("gradual",a.getBoolean("gradual"))
                if(a.has("volumeAction")) { require(a.getString("volumeAction") in listOf("snooze","dismiss","none"));settings.put("volumeAction",a.getString("volumeAction")) }
                if(a.has("sound")) settings.put("sound",a.getString("sound"))
            }
            "bedtime.save" -> {
                ensureTiming(c)
                val bedtime=a.getInt("bedHour")*60+a.getInt("bedMinute");require(bedtime in 0..1439)
                val wake=a.getInt("wakeHour")*60+a.getInt("wakeMinute");require(wake in 0..1439)
                val selected=a.optJSONArray("days") ?: JSONArray(listOf(1,2,3,4,5,6,7))
                s.put("bedtime",JSONObject(a.toString()))
                for((id,h,m,label) in listOf(listOf("bedtime_wake",a.getInt("wakeHour"),a.getInt("wakeMinute"),"Wake up"),listOf("bedtime_winddown",a.getInt("bedHour"),a.getInt("bedMinute"),"Time to wind down"))) {
                    val item=runCatching { find(s,id as String).second }.getOrNull() ?: JSONObject().put("id",id).also {s.getJSONArray("alarms").put(it)}
                    val scheduledDays=if(id=="bedtime_winddown" && bedtime>wake) JSONArray((0 until selected.length()).map { val day=selected.getInt(it);if(day==1)7 else day-1 }) else selected
                    item.put("hour",h).put("minute",m).put("days",scheduledDays).put("label",label).put("enabled",a.optBoolean("enabled",true)).put("vibrate",true).put("winddown",id=="bedtime_winddown").put("ringing",false)
                    item.put("nextAt",ClockPolicy.nextAlarm(h as Int,m as Int,days(item),now))
                }
            }
            else -> error("Unsupported clock action: $action")
        }
        if(requestId.isNotBlank()) {
            receipts.put(requestId,action)
            while(receipts.length()>2000) receipts.remove(receipts.keys().next())
            s.put("receipts",receipts)
        }
        // Persist before scheduling: process death cannot lose the user's operation.
        save(c,s)
        try {
            for(key in listOf("alarms","timers")) {
                val old=prior.getJSONArray(key);val next=s.getJSONArray(key)
                val ids=(0 until next.length()).map {next.getJSONObject(it).getString("id")}.toSet()
                for(i in 0 until old.length()) if(old.getJSONObject(i).getString("id") !in ids) manager(c).cancel(operation(c,old.getJSONObject(i).getString("id")))
                for(i in 0 until next.length()) schedule(c,next.getJSONObject(i),key=="timers")
            }
        } catch(e: Exception) {
            // Do not report a successful clock mutation if Android rejected scheduling.
            save(c,prior)
            restore(c,false)
            throw e
        }
        if(action in listOf("dismiss","snooze","delete","timer.reset","timer.add","timer.pause","timer.resume","alarm.save","alarm.toggle","alarm.skip","bedtime.save")) refreshRinging(c)
        timerNotifications(c,s)
        ClockWidget.updateAll(c)
        return snapshot(c).put("status","ok")
    }
    @Synchronized fun fire(c: Context,id: String) {
        val s=load(c);val found=runCatching {find(s,id)}.getOrNull() ?: return
        val (key,item)=found; val now=System.currentTimeMillis()
        if(key=="timers") {
            if(item.optString("status")!="running" || remaining(c,item)>1000) return
            item.put("status","ringing").put("remaining",0)
        } else {
            if(!item.optBoolean("enabled") || item.optLong("nextAt")>now+1000) return
            if(days(item).isEmpty()) item.put("enabled",false)
            else item.put("nextAt",ClockPolicy.nextAlarm(item.getInt("hour"),item.getInt("minute"),days(item),now))
        }
        item.put("ringing",!item.optBoolean("winddown"));save(c,s)
        if(key=="alarms") runCatching {schedule(c,item,false)}
        if(item.optBoolean("winddown")) {
            ClockRingService.windDown(c,item)
        } else refreshRinging(c)
        ClockWidget.updateAll(c)
    }
    @Synchronized fun ringing(c: Context): List<JSONObject> {
        val s=load(c);val result=mutableListOf<JSONObject>()
        for(key in listOf("alarms","timers")) { val rows=s.getJSONArray(key);for(i in 0 until rows.length()) if(rows.getJSONObject(i).optBoolean("ringing") || rows.getJSONObject(i).optString("status")=="ringing") result.add(rows.getJSONObject(i).put("kind",key)) }
        return result
    }
    fun refreshRinging(c: Context) {
        val intent=Intent(c,ClockRingService::class.java)
        if(ringing(c).isEmpty()) c.stopService(intent) else c.startForegroundService(intent)
    }
    @Synchronized fun restore(c: Context,recalculate: Boolean=true) {
        val s=load(c);val now=System.currentTimeMillis()
        for(key in listOf("alarms","timers")) {
            val rows=s.getJSONArray(key)
            for(i in 0 until rows.length()) {
                val item=rows.getJSONObject(i)
                if(key=="alarms" && item.optBoolean("enabled") && recalculate) item.put("nextAt",ClockPolicy.nextAlarm(item.getInt("hour"),item.getInt("minute"),days(item),now))
                if(key=="timers" && item.optString("status")=="running" && item.optInt("boot")!=boot(c)) {
                    val remain=remaining(c,item)
                    if(remain>0) timerStart(c,item,remain) else item.put("status","finished").put("remaining",0)
                }
                runCatching {schedule(c,item,key=="timers")}
            }
        }
        save(c,s);timerNotifications(c,s);ClockWidget.updateAll(c)
    }
}

class ClockReceiver: BroadcastReceiver() {
    override fun onReceive(c: Context,intent: Intent) {
        when(intent.action) {
            Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED,Intent.ACTION_TIME_CHANGED,Intent.ACTION_TIMEZONE_CHANGED,AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED -> JarvisClock.restore(c)
            "fire" -> intent.getStringExtra("id")?.let {JarvisClock.fire(c,it)}
            "dismiss","snooze","timer.pause","timer.resume","timer.reset","timer.add" -> intent.getStringExtra("id")?.let {runCatching {JarvisClock.execute(c,intent.action!!,JSONObject().put("id",it))}}
        }
    }
}
