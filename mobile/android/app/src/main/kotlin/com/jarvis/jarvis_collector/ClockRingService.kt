package com.jarvis.jarvis_collector

import android.app.*
import android.content.*
import android.graphics.Color
import android.media.*
import android.net.Uri
import android.os.*
import android.view.*
import android.widget.*
import androidx.core.app.NotificationCompat
import org.json.JSONObject

/** Clock sound/vibration survive Flutter disposal and assistant power-off. */
class ClockRingService: Service() {
    private var player: MediaPlayer?=null
    private var vibrator: Vibrator?=null
    private var current=""
    private val handler=Handler(Looper.getMainLooper())
    private var openedAt=0L
    companion object {
        private const val CHANNEL="jarvis_clock_ringing_v1"
        private const val FOREGROUND=0xC10C
        private fun channel(c: Context) {
            c.getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"Clock alarms & timers",NotificationManager.IMPORTANCE_HIGH).apply {
                setSound(null,null);enableVibration(false);lockscreenVisibility=Notification.VISIBILITY_PUBLIC
            })
        }
        private fun action(c:Context,id:String,action:String)=PendingIntent.getBroadcast(c,0,Intent(c,ClockReceiver::class.java).setAction(action).setData(Uri.parse("jarvis-clock:"+Uri.encode(id))).putExtra("id",id),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        private fun screen(c:Context,id:String)=PendingIntent.getActivity(c,0,Intent(c,ClockAlertActivity::class.java).setData(Uri.parse("jarvis-clock:"+Uri.encode(id))).putExtra("id",id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        private fun notice(c:Context,item:JSONObject):Notification {
            channel(c);val id=item.getString("id")
            return NotificationCompat.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setContentTitle(item.optString("label","Clock")).setContentText(if(item.optString("kind")=="timers") "Timer finished" else "Alarm")
                .setCategory(NotificationCompat.CATEGORY_ALARM).setPriority(NotificationCompat.PRIORITY_MAX).setOngoing(true)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC).setContentIntent(screen(c,id)).setFullScreenIntent(screen(c,id),true)
                .addAction(0,"Snooze",action(c,id,"snooze")).addAction(0,"Stop",action(c,id,"dismiss")).build()
        }
        fun windDown(c:Context,item:JSONObject) {
            val channel="jarvis_clock_bedtime"
            val nm=c.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(channel,"Bedtime wind-down",NotificationManager.IMPORTANCE_DEFAULT))
            nm.notify(JarvisClock.TAG,item.getString("id").hashCode(),NotificationCompat.Builder(c,channel).setSmallIcon(android.R.drawable.ic_lock_idle_alarm).setContentTitle("Time to wind down").setContentText("Your bedtime routine is ready. Open Clock for sleep sounds.").setContentIntent(JarvisClock.open(c)).setAutoCancel(true).build())
        }
    }
    override fun onBind(i:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        val items=JarvisClock.ringing(this)
        if(items.isEmpty()) {stopSelf();return START_NOT_STICKY}
        startForeground(FOREGROUND,notice(this,items.first()))
        val nm=getSystemService(NotificationManager::class.java)
        items.forEach {nm.notify(JarvisClock.TAG,it.getString("id").hashCode(),notice(this,it))}
        val first=items.first();val id=first.getString("id")
        if(id!=current) {
            stopAudio();current=id;openedAt=SystemClock.elapsedRealtime()
            val settings=JarvisClock.snapshot(this).getJSONObject("settings")
            val chosen=first.optString("sound").ifBlank {settings.optString("sound")}
            val uri=if(chosen.isBlank()) RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) else Uri.parse(chosen)
            if(chosen!="silent") {
                fun play(source:Uri) {
                    player=MediaPlayer().apply {
                        setWakeMode(this@ClockRingService,PowerManager.PARTIAL_WAKE_LOCK)
                        setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                        setDataSource(this@ClockRingService,source);isLooping=true;prepare()
                        val v=if(settings.optBoolean("gradual")) .05f else settings.optDouble("volume",1.0).toFloat()
                        setVolume(v,v);start()
                    }
                }
                runCatching {play(uri)}.onFailure {player?.release();player=null;runCatching {play(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM))}}
            }
            if(first.optBoolean("vibrate",true)) {
                @Suppress("DEPRECATION")
                vibrator=getSystemService(VIBRATOR_SERVICE) as Vibrator
                vibrator?.vibrate(VibrationEffect.createWaveform(longArrayOf(0,600,500),0))
            }
            handler.post(object:Runnable {
                override fun run() {
                    if(current!=id)return
                    val seconds=(SystemClock.elapsedRealtime()-openedAt)/1000
                    if(seconds>=settings.optInt("silenceMinutes",10)*60) {
                        JarvisClock.execute(this@ClockRingService,"dismiss",JSONObject().put("id",id));return
                    }
                    if(settings.optBoolean("gradual")) {val v=(settings.optDouble("volume",1.0)*(seconds/30.0).coerceIn(.05,1.0)).toFloat();player?.setVolume(v,v)}
                    handler.postDelayed(this,1000)
                }
            })
        }
        return START_NOT_STICKY
    }
    private fun stopAudio(){handler.removeCallbacksAndMessages(null);player?.stop();player?.release();player=null;vibrator?.cancel();vibrator=null}
    override fun onDestroy(){stopAudio();super.onDestroy()}
}

class ClockAlertActivity: Activity() {
    private var id=""
    private val handler=Handler(Looper.getMainLooper())
    override fun onCreate(saved:Bundle?) {
        super.onCreate(saved);id=intent.getStringExtra("id") ?: ""
        setShowWhenLocked(true);setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val item=JarvisClock.ringing(this).firstOrNull {it.optString("id")==id}
        if(item==null){finish();return}
        val layout=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL;gravity=Gravity.CENTER;setPadding(48,64,48,64);setBackgroundColor(Color.rgb(13,18,28))}
        fun text(value:String,size:Float){layout.addView(TextView(this).apply {text=value;textSize=size;setTextColor(Color.WHITE);gravity=Gravity.CENTER;setPadding(0,22,0,22)})}
        text("JARVIS CLOCK",18f);text(item.optString("label","Clock"),36f)
        text(java.time.LocalTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")),64f)
        fun button(label:String,action:String){layout.addView(Button(this).apply {text=label;setOnClickListener {act(action)}},LinearLayout.LayoutParams(-1,-2).apply {topMargin=24})}
        button("Snooze ${JarvisClock.snapshot(this).getJSONObject("settings").optInt("snoozeMinutes",10)} minutes","snooze")
        button("Stop","dismiss");setContentView(layout)
        handler.postDelayed(object:Runnable {override fun run(){if(JarvisClock.ringing(this@ClockAlertActivity).none{it.optString("id")==id})finish() else handler.postDelayed(this,500)}},500)
    }
    private fun act(action:String){runCatching{JarvisClock.execute(this,action,JSONObject().put("id",id))}.onFailure {Toast.makeText(this,it.message,Toast.LENGTH_LONG).show()};finish()}
    override fun onKeyDown(keyCode:Int,event:KeyEvent?):Boolean {
        if(keyCode in listOf(KeyEvent.KEYCODE_VOLUME_UP,KeyEvent.KEYCODE_VOLUME_DOWN)) {
            val action=JarvisClock.snapshot(this).getJSONObject("settings").optString("volumeAction","snooze")
            if(action!="none"){act(action);return true}
        }
        return super.onKeyDown(keyCode,event)
    }
    override fun onDestroy(){handler.removeCallbacksAndMessages(null);super.onDestroy()}
}

class ClockSleepService: Service() {
    private var player:MediaPlayer?=null
    private val handler=Handler(Looper.getMainLooper())
    override fun onBind(intent:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action=="stop"){stopSelf();return START_NOT_STICKY}
        val sound=intent?.getStringExtra("sound") ?: "rain"
        val minutes=intent?.getIntExtra("minutes",30) ?: 30
        val channel="jarvis_clock_sleep"
        val nm=getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(channel,"Sleep sounds",NotificationManager.IMPORTANCE_LOW))
        val stop=PendingIntent.getService(this,5703,Intent(this,ClockSleepService::class.java).setAction("stop"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        startForeground(0xC10D,NotificationCompat.Builder(this,channel).setSmallIcon(android.R.drawable.ic_lock_idle_alarm).setContentTitle("$sound · sleep sounds").setContentText("Stops in $minutes minutes").setContentIntent(JarvisClock.open(this)).addAction(0,"Stop",stop).setOngoing(true).build())
        player?.release();player=MediaPlayer.create(this,when(sound){"ocean"->R.raw.clock_ocean;"brown"->R.raw.clock_brown;else->R.raw.clock_rain}).apply{isLooping=true;start()}
        handler.removeCallbacksAndMessages(null);handler.postDelayed({stopSelf()},minutes.coerceIn(1,480)*60_000L)
        return START_NOT_STICKY
    }
    override fun onDestroy(){handler.removeCallbacksAndMessages(null);player?.release();player=null;super.onDestroy()}
}
