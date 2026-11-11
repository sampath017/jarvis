package com.jarvis.jarvis_collector

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.ComponentName
import android.widget.RemoteViews
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class ClockWidget: AppWidgetProvider() {
    override fun onUpdate(c:Context,manager:AppWidgetManager,ids:IntArray) { update(c,manager,ids) }
    companion object {
        fun updateAll(c:Context) { val manager=AppWidgetManager.getInstance(c);update(c,manager,manager.getAppWidgetIds(ComponentName(c,ClockWidget::class.java))) }
        private fun update(c:Context,manager:AppWidgetManager,ids:IntArray) {
            if(ids.isEmpty())return
            val alarms=JarvisClock.snapshot(c).getJSONArray("alarms")
            val next=(0 until alarms.length()).map {alarms.getJSONObject(it)}.filter {it.optBoolean("enabled")}.minByOrNull {it.optLong("nextAt")}
            val label=next?.let { "Alarm · "+Instant.ofEpochMilli(it.optLong("nextAt")).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("EEE HH:mm")) } ?: "Open Jarvis Clock"
            for(id in ids) manager.updateAppWidget(id,RemoteViews(c.packageName,R.layout.clock_widget).apply {setTextViewText(R.id.clock_next,label);setOnClickPendingIntent(R.id.clock_widget,JarvisClock.open(c))})
        }
    }
}
