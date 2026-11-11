package com.jarvis.jarvis_collector

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.*
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import org.json.JSONObject
import org.vosk.Model
import org.vosk.android.StorageService
import java.util.concurrent.Executors

/** Local wake/greeting and interruptible speech, with network-backed command turns. */
class JarvisVoiceService:Service(),TextToSpeech.OnInitListener {
    companion object {
        @Volatile var running=false
        @Volatile var phase="Off"
        @Volatile var detail=""
        const val NOTIFICATION=JarvisOngoingNotification.ID
        fun disable(c:Context) {
            check(VoiceChatStore.prefs(c).edit().putBoolean("resumeListening",false).commit())
            c.stopService(Intent(c,JarvisVoiceService::class.java))
        }
        fun status(c:Context):JSONObject = JSONObject().put("running",running).put("phase",phase).put("detail",detail)
            .put("microphoneGranted",c.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)
            .put("thread",VoiceChatStore.prefs(c).getString("thread",null) ?: JSONObject.NULL)
            .put("speakReplies",VoiceChatStore.prefs(c).getBoolean("speakReplies",true))
    }
    private var model:Model?=null
    private var speech:VoiceAudioCapture?=null
    private var tts:TextToSpeech?=null
    private var ttsReady=false
    private var pendingSpeech:Pair<String,Boolean>?=null
    private var speaking=false
    private var busy=false
    @Volatile private var turn=0L
    @Volatile private var client:VoiceCommandClient?=null
    private val playback=VoicePlaybackToken()
    private var standbyAfterSpeech=false
    private val handler=Handler(Looper.getMainLooper())
    private val worker=Executors.newSingleThreadExecutor()
    private val wake by lazy {getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"Jarvis:Voice").apply{setReferenceCounted(false)}}
    override fun onBind(i:Intent?)=null
    private fun state(value:String,message:String="") {
        if(phase==value && detail==message)return
        phase=value;detail=message
        android.util.Log.i("JarvisVoice","State: $value")
        if(running)getSystemService(NotificationManager::class.java).notify(NOTIFICATION,JarvisOngoingNotification.build(this))
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action=="stop"){disable(this);return START_NOT_STICKY}
        if(!JarvisPower.enabled(this) || checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){stopSelf();return START_NOT_STICKY}
        if(running)return START_NOT_STICKY
        running=true;phase="Loading offline speech"
        startForeground(NOTIFICATION,JarvisOngoingNotification.build(this))
        check(VoiceChatStore.prefs(this).edit().putBoolean("resumeListening",true).commit())
        wake.acquire();tts=TextToSpeech(this,this)
        StorageService.unpack(this,"vosk-model-small-en-us-0.15","jarvis-voice-model",{loaded ->
            if(!running){loaded.close();return@unpack}
            try {
                model=loaded
                speech=VoiceAudioCapture(loaded,applicationContext,
                    {audio,local -> handler.post {receive(audio,local)}},
                    {handler.post {if(running){interrupt();say(VoiceTurnPolicy.GREETING)}}},
                    {handler.post {if(running)interrupt()}},
                    {value -> handler.post {if(running && !busy && !speaking)state(value)}},
                    {failure -> handler.post {if(running){state("Voice unavailable",failure.message ?: "Microphone stopped");stopSelf()}}}
                ).also{it.start()}
            } catch(e:Exception){state("Voice unavailable",e.message ?: "Microphone could not start");stopSelf()}
        },{e -> state("Voice unavailable",e.message ?: "Speech model could not load");stopSelf()})
        return START_NOT_STICKY
    }
    override fun onInit(status:Int) {
        if(!running)return
        if(status!=TextToSpeech.SUCCESS){pendingSpeech=null;state("Voice unavailable","Offline speech playback could not initialize");return}
        val voice=tts?.voices?.filter{!it.isNetworkConnectionRequired && it.locale.language=="en"}?.maxByOrNull{it.quality}
        if(voice!=null){tts?.voice=voice;ttsReady=true}
        tts?.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
        tts?.setOnUtteranceProgressListener(object:UtteranceProgressListener(){
            override fun onStart(id:String?){}
            override fun onDone(id:String?){handler.post{if(playback.isCurrent(id))finishSpeaking()}}
            @Deprecated("Android callback") override fun onError(id:String?){handler.post{if(playback.isCurrent(id))finishSpeaking()}}
        })
        val pending=pendingSpeech;pendingSpeech=null
        if(pending!=null)say(pending.first,pending.second)
    }
    private fun finishSpeaking() {
        if(!running)return
        speaking=false
        if(standbyAfterSpeech){speech?.standby();state("Waiting for Jarvis")}
        else {speech?.resume();state("Listening for your next command")}
    }
    private fun interrupt() {
        turn++;playback.invalidate();pendingSpeech=null
        tts?.stop();speaking=false;busy=false;standbyAfterSpeech=false
        client?.close();client=null
        // Capture already switched to LISTEN and retained the interrupting audio.
        android.util.Log.i("JarvisVoice","Turn interrupted; old playback invalidated")
    }
    private fun say(text:String,standby:Boolean=false) {
        if(!running)return
        standbyAfterSpeech=standby
        if(!VoiceChatStore.prefs(this).getBoolean("speakReplies",true)){finishSpeaking();return}
        if(!ttsReady) {
            if(tts?.voices==null){pendingSpeech=text to standby;return}
            finishSpeaking();state(phase,"Install an offline English voice for spoken replies.");return
        }
        val clean=text.replace(Regex("[`*_#]"),"").trim()
        if(clean.isEmpty()){finishSpeaking();return}
        val id=playback.next()
        speaking=true;speech?.speaking(clean);state("Speaking — you can interrupt")
        val chunks=clean.chunked(TextToSpeech.getMaxSpeechInputLength()-1)
        for((i,chunk) in chunks.withIndex()) {
            if(tts?.speak(chunk,if(i==0)TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD,null,
                    if(i==chunks.lastIndex)id else "${id}_part_$i")!=TextToSpeech.SUCCESS){finishSpeaking();break}
        }
    }
    private fun online():Boolean {
        val manager=getSystemService(ConnectivityManager::class.java)
        return manager.getNetworkCapabilities(manager.activeNetwork)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)==true
    }
    private fun localControl(text:String):Boolean {
        if(VoiceTurnPolicy.newConversation(text)){VoiceChatStore.newThread(this);say("New voice conversation. How can I help?");return true}
        if(VoiceTurnPolicy.endConversation(text)){say("Okay. Say Hey Jarvis when you need me.",true);return true}
        if(VoicePolicy.stop(text)){disable(this);return true}
        if(VoicePolicy.isWakeGreeting(text)){say(VoiceTurnPolicy.GREETING);return true}
        return false
    }
    private fun receive(audio:ByteArray,local:String) {
        if(!running){audio.fill(0);return}
        if(localControl(local)){audio.fill(0);return}
        if(!online()){audio.fill(0);say("I'm offline. I can hear my wake word, but I need a connection to answer questions.",true);return}
        val requestTurn=++turn
        busy=true;state("Transcribing")
        worker.execute {
            val request=VoiceCommandClient(applicationContext){running && turn==requestTurn && JarvisPower.enabled(applicationContext)}
            var submitted=false
            try {
                if(!running || turn!=requestTurn)return@execute
                client=request
                val transcript=request.transcribe(audio)
                if(!running || turn!=requestTurn)return@execute
                // Controls are handled on the main thread; all callbacks are scoped
                // to this turn so interrupted results cannot speak over the user.
                if(VoiceTurnPolicy.newConversation(transcript) || VoiceTurnPolicy.endConversation(transcript) || VoicePolicy.stop(transcript) || VoicePolicy.isWakeGreeting(transcript)) {
                    handler.post{if(running && turn==requestTurn){busy=false;localControl(transcript)}}
                } else {
                    val command=VoicePolicy.command(transcript,true).orEmpty()
                    if(command.isBlank())handler.post{if(running && turn==requestTurn){busy=false;say("Please say that again.")}}
                    else {
                        submitted=true
                        val answer=request.send(command){progress -> handler.post{if(running && turn==requestTurn)state("Working",progress)}}
                        handler.post{if(running && turn==requestTurn){busy=false;say(answer)}}
                    }
                }
            } catch(e:Exception) {
                val message=if(submitted) "I couldn't confirm the result. Please check the chat before repeating an action."
                    else "I couldn't hear that clearly or reach transcription. Please try again when connected."
                handler.post{if(running && turn==requestTurn){busy=false;say(message)}}
            } finally {request.close();if(client===request)client=null;audio.fill(0)}
        }
    }
    override fun onDestroy() {
        running=false;turn++;playback.invalidate();client?.close();speech?.close();model?.close()
        tts?.stop();tts?.shutdown();handler.removeCallbacksAndMessages(null);worker.shutdownNow()
        if(wake.isHeld)wake.release();phase="Off"
        stopForeground(STOP_FOREGROUND_DETACH);JarvisOngoingNotification.refresh(this);super.onDestroy()
    }
}
