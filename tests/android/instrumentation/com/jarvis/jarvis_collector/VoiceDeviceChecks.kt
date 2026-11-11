package com.jarvis.jarvis_collector

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.StorageService
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Decode generated, offline test speech. No microphone or private audio is used. */
object VoiceDeviceChecks {
    fun command(c:Context) {
        check(JarvisPower.enabled(c)) {"Enable the assistant before checking the voice backend connection"}
        val p=VoiceChatStore.prefs(c);val previous=p.getString("thread",null)
        val thread="voice_check_"+java.util.UUID.randomUUID()
        check(p.edit().putString("thread",thread).commit())
        try {
            val answer=VoiceCommandClient(c){true}.send("This is a voice setup connection test. Reply with Voice connection verified. Do not use tools or change any records."){}
            check(answer.contains("Voice connection verified",ignoreCase=true)) {"Unexpected voice backend reply: $answer"}
            val history=VoiceChatStore.history(c,thread)
            check(history.length()==2 && history.getJSONObject(0).getString("role")=="user" && history.getJSONObject(1).getString("role")=="assistant") {"Voice exchange was not saved in its own thread"}
        } finally {
            val edit=p.edit();if(previous==null)edit.remove("thread") else edit.putString("thread",previous);edit.commit()
            android.database.sqlite.SQLiteDatabase.openDatabase(c.getDatabasePath("jarvis_mobile.db").path,null,android.database.sqlite.SQLiteDatabase.OPEN_READWRITE).use {db->
                // Exact UUID-owned test chat only; never replace or clear personal tables.
                db.delete("chat_messages","thread_id=?",arrayOf(thread));db.delete("chat_sessions","id=?",arrayOf(thread))
            }
        }
    }
    fun run(c:Context, cloud:Boolean=false, vadCheck:Boolean=false) {
        val path=StorageService.sync(c,"vosk-model-small-en-us-0.15","jarvis-voice-model")
        val initialized=CountDownLatch(1);var status=-1
        val tts=TextToSpeech(c){value->status=value;initialized.countDown()}
        val files=mutableListOf<File>()
        try {
            check(initialized.await(20,TimeUnit.SECONDS) && status==TextToSpeech.SUCCESS) {"Text-to-speech initialization failed"}
            val voice=tts.voices.filter{!it.isNetworkConnectionRequired && it.locale.language=="en"}.maxByOrNull{it.quality}
            check(voice!=null) {"Install an offline English text-to-speech voice to run the acoustic check"}
            tts.voice=voice;tts.setSpeechRate(.85f)
            Model(path).use {model->
                val commands = listOf("Hey Jarvis start a five minute timer","Hello Jarvis what time is it","Jarvis make a note")
                val unrelated = listOf("The weather is nice today", "Please start a timer", "Services are ready")
                val phrases = if (cloud || vadCheck) commands else commands +
                    listOf("Hey Jarvis", "Hi Jarvis", "Hey, what's up Jarvis?", "Jarvis") + unrelated
                for(phrase in phrases) {
                    val out=File.createTempFile("jarvis-voice-check-",".wav",c.cacheDir);files.add(out)
                    val done=CountDownLatch(1);var failed=false
                    tts.setOnUtteranceProgressListener(object:UtteranceProgressListener(){
                        override fun onStart(id:String?){}
                        override fun onDone(id:String?){done.countDown()}
                        @Deprecated("Android callback") override fun onError(id:String?){failed=true;done.countDown()}
                    })
                    check(tts.synthesizeToFile(phrase,Bundle(),out,"test")==TextToSpeech.SUCCESS)
                    check(done.await(20,TimeUnit.SECONDS) && !failed)
                    val wav=out.readBytes();check(String(wav,0,4)=="RIFF")
                    val data=ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
                    var offset=12;var rate=0;var channels=0;var bits=0;var pcm=ByteArray(0)
                    while(offset+8<=wav.size) {
                        val name=String(wav,offset,4);val size=data.getInt(offset+4)
                        if(name=="fmt "){channels=data.getShort(offset+10).toInt();rate=data.getInt(offset+12);bits=data.getShort(offset+22).toInt()}
                        if(name=="data"){pcm=wav.copyOfRange(offset+8,minOf(wav.size,offset+8+size));break}
                        offset+=8+size+(size%2)
                    }
                    check(rate>0 && bits==16 && channels>=1)
                    val source=ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN)
                    val sourceCount=pcm.size/(2*channels);val count=(sourceCount.toLong()*16000/rate).toInt()
                    val resampled=ShortArray(count)
                    for(i in 0 until count){val sample=minOf(sourceCount-1,(i.toLong()*rate/16000).toInt());resampled[i]=source.getShort(sample*2*channels)}
                    if(!cloud && !vadCheck && phrase !in unrelated) {
                        Recognizer(model,16000f).use {local ->
                            val text=StringBuilder();var offset=0
                            while(offset<resampled.size) {
                                val chunk=resampled.copyOfRange(offset,minOf(offset+512,resampled.size))
                                if(local.acceptWaveForm(chunk,chunk.size))text.append(org.json.JSONObject(local.result).optString("text")).append(' ')
                                offset+=chunk.size
                            }
                            text.append(org.json.JSONObject(local.finalResult).optString("text"))
                            check(VoicePolicy.isWakeGreeting(text.toString()) == (phrase !in commands)) {
                                "Local greeting classification failed: $phrase -> $text"
                            }
                        }
                    }
                    if(vadCheck) {
                        SpeechDetector(c).use {vad ->
                            var speechFrames=0
                            var offset=0
                            while(offset+512<=resampled.size) {
                                if(vad.probability(resampled.copyOfRange(offset,offset+512))>=0.6f) speechFrames++
                                offset+=512
                            }
                            check(speechFrames>=7) {"Speech detector missed synthesized speech"}
                            val random=java.util.Random(42)
                            var tailSpeech=0
                            repeat(160) {frame ->
                                val noise=ShortArray(512) { (random.nextGaussian()*2000).toInt().coerceIn(-32768,32767).toShort() }
                                val probability=vad.probability(noise)
                                if(frame>=128 && probability>=0.6f)tailSpeech++
                            }
                            check(tailSpeech<=2) {"Noise kept speech detector active after speech: $tailSpeech frames"}
                            vad.reset()
                            var falseSpeech=0
                            repeat(160) {frame ->
                                val hum=ShortArray(512) {i -> (5000*kotlin.math.sin(2*Math.PI*120*(frame*512+i)/16000)).toInt().toShort() }
                                if(vad.probability(hum)>=0.6f)falseSpeech++
                            }
                            check(falseSpeech<8) {"Loud steady hum was mistaken for speech"}
                        }
                    }
                    if(cloud) {
                        val bytes=ByteBuffer.allocate(resampled.size*2).order(ByteOrder.LITTLE_ENDIAN)
                        for(sample in resampled) bytes.putShort(sample)
                        val client=VoiceCommandClient(c){true}
                        try {
                            val transcript=client.transcribe(VoiceAudioCapture.wav(bytes.array())).lowercase()
                            val expected=if(phrase.contains("timer")) "timer" else if(phrase.contains("time")) "time" else "note"
                            check(transcript.contains(expected)) {"Whisper did not transcribe the command: $transcript"}
                        } finally {client.close()}
                    }
                    Recognizer(model,16000f,VoicePolicy.WAKE_GRAMMAR).use {recognizer->
                        // Match production's 32ms partial/final checks, with trailing
                        // silence rather than forcing a final result at end of file.
                        val padded=resampled.copyOf(resampled.size+32000)
                        var detected=false;var start=0
                        while(start+512<=padded.size) {
                            val chunk=padded.copyOfRange(start,start+512)
                            val final=recognizer.acceptWaveForm(chunk,chunk.size)
                            val text=org.json.JSONObject(if(final) recognizer.result else recognizer.partialResult)
                                .optString(if(final) "text" else "partial")
                            if(VoicePolicy.hasWake(text))detected=true
                            start+=512
                        }
                        check(detected == (phrase !in unrelated)) {"Unexpected wake detection ($detected): $phrase"}
                    }
                }
            }
        } finally {tts.shutdown();files.forEach {it.delete()}}
    }
}
