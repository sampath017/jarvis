package com.jarvis.jarvis_collector

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.SystemClock
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** One microphone, local wake greeting, and echo-aware conversational turn capture. */
class VoiceAudioCapture(private val model:Model, private val context:android.content.Context,
    private val command:(ByteArray,String)->Unit, private val onWake:()->Unit,
    private val onInterrupt:()->Unit, private val status:(String)->Unit,
    private val error:(Exception)->Unit) {
    private enum class Mode { WAKE, LISTEN, BUSY, SPEAK }
    private data class Control(val mode:Mode,val spoken:String="")
    @Volatile private var control=Control(Mode.WAKE)
    @Volatile private var active=true
    @Volatile var echoCancellation=false; private set
    private var thread:Thread?=null
    private var recorder:AudioRecord?=null
    fun resume(){control=Control(Mode.LISTEN)}
    fun standby(){control=Control(Mode.WAKE)}
    fun thinking(){control=Control(Mode.BUSY)}
    fun speaking(text:String){control=Control(Mode.SPEAK,text)}
    fun start() {
        val min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
        val mic=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,
            AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,maxOf(min,6400))
        recorder=mic
        check(mic.state==AudioRecord.STATE_INITIALIZED){"Microphone could not initialize"}
        val aec=runCatching { if(AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(mic.audioSessionId) else null }.getOrNull()
        echoCancellation=runCatching {aec?.enabled=true;aec?.enabled==true}.getOrDefault(false)
        android.util.Log.i("JarvisVoice","Echo cancellation: $echoCancellation")
        mic.startRecording()
        thread=Thread({
            var wake:Recognizer?=null;var local:Recognizer?=null;var vad:SpeechDetector?=null
            try {
                val w=Recognizer(model,16000f,VoicePolicy.WAKE_GRAMMAR);wake=w
                val r=Recognizer(model,16000f);local=r
                val v=SpeechDetector(context);vad=v
                val samples=ShortArray(512)
                val recent=ByteArrayOutputStream();val audio=ByteArrayOutputStream();val text=StringBuilder()
                var seen:Control?=null;var mode=Mode.WAKE
                var consecutive=0;var silence=0;var confirmed=false;var idle=0L
                fun reset(){recent.reset();audio.reset();text.clear();w.reset();r.reset();v.reset();consecutive=0;silence=0;confirmed=false}
                fun decode(bytes:ByteArray):String {
                    val final=r.acceptWaveForm(bytes,bytes.size)
                    val part=JSONObject(if(final)r.result else r.partialResult).optString(if(final)"text" else "partial")
                    if(final)text.append(part).append(' ')
                    return text.toString()+if(final)"" else part
                }
                while(active) {
                    val n=mic.read(samples,0,samples.size,AudioRecord.READ_BLOCKING)
                    if(n<0)kotlin.error("Microphone read failed: $n")
                    if(n!=512)continue
                    val current=control
                    if(current!==seen) {
                        seen=current;mode=current.mode;reset();idle=SystemClock.elapsedRealtime()+VoiceTurnPolicy.IDLE_MS
                        if(mode==Mode.WAKE)status("Waiting for Jarvis")
                        if(mode==Mode.LISTEN)status("Listening for your command")
                    }
                    val bytes=ByteBuffer.allocate(1024).order(ByteOrder.LITTLE_ENDIAN).apply{samples.forEach{putShort(it)}}.array()
                    val voiced=v.probability(samples)>=0.65f
                    consecutive=if(voiced)consecutive+512 else 0
                    silence=if(voiced)0 else silence+512
                    if(mode==Mode.WAKE) {
                        val final=w.acceptWaveForm(samples,n)
                        val phrase=JSONObject(if(final)w.result else w.partialResult).optString(if(final)"text" else "partial")
                        if(VoicePolicy.hasWake(phrase)) {
                            control=Control(Mode.BUSY);onWake()
                        }
                        continue
                    }
                    recent.write(bytes)
                    if(recent.size()>48000){val tail=recent.toByteArray().takeLast(48000).toByteArray();recent.reset();recent.write(tail)}
                    if(mode==Mode.SPEAK || mode==Mode.BUSY) {
                        val partial=decode(bytes)
                        val interrupt=if(mode==Mode.SPEAK)
                            VoiceTurnPolicy.isInterruption(partial,current.spoken,consecutive,echoCancellation)
                        else consecutive>=4096 && partial.isNotBlank()
                        if(interrupt) {
                            val next=Control(Mode.LISTEN);control=next;seen=next;mode=Mode.LISTEN
                            audio.write(recent.toByteArray());confirmed=true;idle=SystemClock.elapsedRealtime()+VoiceTurnPolicy.IDLE_MS
                            onInterrupt();status("Listening to your interruption")
                        } else if(silence>=16000){r.reset();text.clear();recent.reset()}
                        continue
                    }
                    if(!confirmed && consecutive>=3200) {
                        confirmed=true;audio.write(recent.toByteArray());decode(recent.toByteArray())
                    } else if(confirmed){audio.write(bytes);decode(bytes)}
                    if(confirmed && (silence>=VoiceTurnPolicy.END_SILENCE_SAMPLES || audio.size()>=1_920_000)) {
                        val transcript=(text.toString()+JSONObject(r.finalResult).optString("text")).trim()
                        val payload=wav(audio.toByteArray().let{it.copyOf(minOf(it.size,1_920_000))})
                        control=Control(Mode.BUSY);command(payload,transcript)
                    } else if(!confirmed && SystemClock.elapsedRealtime()>idle)control=Control(Mode.WAKE)
                }
            } catch(e:Exception){if(active)error(e)}
            finally{vad?.close();local?.close();wake?.close();aec?.release();runCatching{mic.stop()};mic.release()}
        },"JarvisVoiceCapture").also{it.start()}
    }
    fun close(){active=false;runCatching{recorder?.stop()};thread?.join(2000)}
    companion object {
        fun wav(pcm:ByteArray):ByteArray=ByteBuffer.allocate(44+pcm.size).order(ByteOrder.LITTLE_ENDIAN).apply{
            put("RIFF".toByteArray());putInt(36+pcm.size);put("WAVEfmt ".toByteArray());putInt(16)
            putShort(1);putShort(1);putInt(16000);putInt(32000);putShort(2);putShort(16)
            put("data".toByteArray());putInt(pcm.size);put(pcm)
        }.array()
    }
}
