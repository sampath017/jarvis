package com.jarvis.jarvis_collector

import android.content.Context
import android.app.NotificationManager
import android.os.SystemClock
import org.json.JSONObject
import java.util.UUID

/** Explicit clock-only mode; creates/deletes only its own UUID-labelled clock items. */
object ClockDeviceChecks {
    fun run(c:Context) {
        val powerBefore=JarvisPower.enabled(c)
        val tag="clock-verification-"+UUID.randomUUID()
        val owned=mutableListOf<String>()
        fun item(id:String)=JarvisClock.snapshot(c).getJSONArray("timers").let {rows->(0 until rows.length()).map {rows.getJSONObject(it)}.first {it.getString("id")==id}}
        try {
            // Exercise the real master switch and restore its original setting in finally.
            val first=JarvisClock.execute(c,"timer.start",JSONObject().put("seconds",60).put("label",tag).put("__requestId",tag))
            val rows=first.getJSONArray("timers")
            val t=(0 until rows.length()).map {rows.getJSONObject(it)}.single {it.optString("label")==tag}
            val id=t.getString("id");owned.add(id)
            // An already-running timer/notification must survive assistant shutdown.
            if(powerBefore) JarvisPower.setEnabled(c,false)
            check(!JarvisPower.enabled(c))
            check(item(id).optString("status")=="running")
            check(c.getSystemService(NotificationManager::class.java).activeNotifications.any {it.tag==JarvisClock.TAG && it.id==id.hashCode()}) {"Power-off removed the running timer notification"}
            val replay=JarvisClock.execute(c,"timer.start",JSONObject().put("seconds",60).put("label",tag).put("__requestId",tag))
            check(replay.getBoolean("replayed")) {"Device receipt did not deduplicate a replay"}
            JarvisClock.execute(c,"timer.pause",JSONObject().put("id",id));val paused=item(id).getLong("remaining")
            check(item(id).getString("status")=="paused" && paused in 1..60_000)
            JarvisClock.execute(c,"timer.add",JSONObject().put("id",id).put("seconds",60))
            check(item(id).getLong("remaining")==paused+60_000)
            JarvisClock.execute(c,"timer.resume",JSONObject().put("id",id))
            check(item(id).getString("status")=="running")
            val notification=c.getSystemService(NotificationManager::class.java).activeNotifications.any {it.tag==JarvisClock.TAG && it.id==id.hashCode()}
            check(notification) {"Running timer notification missing"}
            val shortLabel=tag+"-ring"
            val short=JarvisClock.execute(c,"timer.start",JSONObject().put("seconds",3).put("label",shortLabel)).getJSONArray("timers")
            val ring=(0 until short.length()).map {short.getJSONObject(it)}.single {it.optString("label")==shortLabel}.getString("id")
            owned.add(ring)
            val deadline=SystemClock.elapsedRealtime()+10_000
            while(SystemClock.elapsedRealtime()<deadline && item(ring).optString("status")!="ringing") Thread.sleep(200)
            check(item(ring).optString("status")=="ringing") {"Native alarm did not fire while Flutter was absent"}
            check(JarvisClock.ringing(c).any {it.getString("id")==ring})
            Thread.sleep(600)
            check(c.getSystemService(NotificationManager::class.java).activeNotifications.any {it.tag==JarvisClock.TAG && it.id==ring.hashCode()}) {"Ringing notification missing"}
            JarvisClock.execute(c,"dismiss",JSONObject().put("id",ring))
            check(item(ring).optString("status")=="finished")
            check(!JarvisPower.enabled(c)) {"Clock changed the assistant power switch"}
        } finally {
            for(id in owned) runCatching {JarvisClock.execute(c,"delete",JSONObject().put("id",id))}
            if(powerBefore) JarvisPower.setEnabled(c,true)
        }
    }
}
