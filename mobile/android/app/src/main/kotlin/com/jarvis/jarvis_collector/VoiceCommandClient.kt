package com.jarvis.jarvis_collector

import android.content.Context
import org.json.JSONObject
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.SecureRandom
import java.util.UUID

/** Same command protocol as text chat, with durable voice-only thread ownership. */
class VoiceCommandClient(private val c:Context,private val alive:()->Boolean) {
    private val connections=java.util.Collections.synchronizedSet(mutableSetOf<HttpURLConnection>())
    private val p=VoiceChatStore.prefs(c)
    private val session:String= p.getString("sessionKey",null) ?: ByteArray(32).also {SecureRandom().nextBytes(it)}.joinToString(""){"%02x".format(it.toInt() and 255)}.also {check(p.edit().putString("sessionKey",it).commit())}
    private fun open(path:String,body:JSONObject?=null):HttpURLConnection {
        check(alive() && JarvisPower.enabled(c)) {"Voice request stopped"}
        val base=ContextEventQueue.apiUrl(c) ?: error("Open a Jarvis chat once to configure its backend.")
        val connection=URL(base.trimEnd('/')+path).openConnection() as HttpURLConnection
        connection.connectTimeout=10_000;connection.readTimeout=40_000
        connection.setRequestProperty("Content-Type","application/json");connection.setRequestProperty("X-User-ID",ContextEventQueue.apiUser(c));connection.setRequestProperty("X-Calendar-Session",session)
        JarvisPower.track(c,connection);connections.add(connection)
        if(body!=null){connection.requestMethod="POST";connection.doOutput=true;connection.outputStream.use {it.write(body.toString().toByteArray(Charsets.UTF_8))}}
        return connection
    }
    private fun release(connection:HttpURLConnection){JarvisPower.release(connection);connections.remove(connection)}
    fun close(){synchronized(connections){connections.toList().forEach{it.disconnect()};connections.clear()}}
    private fun action(data:JSONObject,request:String) {
        val id=data.getString("action_id");val expiry=data.optString("expires_at")
        val result=try {
            check(alive() && JarvisPower.enabled(c))
            if(expiry.isNotBlank())check(java.time.Instant.parse(expiry).isAfter(java.time.Instant.now())) {"Voice action expired"}
            when(data.optString("operation")) {
                "clock_action" -> JarvisClock.execute(c,data.optString("clock_action","snapshot"),(data.optJSONObject("arguments") ?: JSONObject()).put("__requestId",id))
                "local_read" -> JSONObject().put("status","ok").put("state",VoiceChatStore.readTool(c,data.getString("tool"),data.optJSONObject("arguments") ?: JSONObject()))
                "location_read" -> {
                    val event=ContextEventQueue.newEvent("BACKEND_CONTEXT_REQUEST","UNKNOWN","ENTER")
                    val captured=ContextLocationCapture.capture(c,listOf(event),5_000).first()
                    if(captured.has("location"))JSONObject().put("status","ok").put("gps",captured.getJSONObject("location")).put("observed_at",captured.getJSONObject("location").optString("timestamp"))
                    else JSONObject().put("status","unavailable").put("message","The phone did not return a fresh location.")
                }
                else -> JSONObject().put("status","needs_user_input").put("message","This action needs an on-screen permission, account connection or approval. Ask the user to open Jarvis; do not claim it was executed.")
            }
        } catch(e:Exception){JSONObject().put("status","failed").put("message",e.message ?: "The phone action failed")}
        val conn=open("/commands/requests/"+URLEncoder.encode(request,"UTF-8")+"/calendar-result",JSONObject().put("action_id",id).put("result",result))
        try{check(conn.responseCode in 200..299) {"The phone action receipt was not acknowledged"};conn.inputStream.close()}finally{release(conn)}
    }
    fun transcribe(audio:ByteArray):String {
        val context=MobileRecords.context(c,JSONObject())
        val body=JSONObject().put("audio",android.util.Base64.encodeToString(audio,android.util.Base64.NO_WRAP))
            .put("_mobile_state",JSONObject().put("budget",context.getJSONObject("budget")))
        val connection=open("/voice/transcribe",body)
        connection.readTimeout=75_000
        try {
            val code=connection.responseCode
            val raw=(if(code in 200..299)connection.inputStream else connection.errorStream)?.bufferedReader()?.use{it.readText()} ?: "{}"
            val result=JSONObject(raw)
            result.optJSONObject("_mobile_changes")?.let{MobileRecords.apply(c,it)}
            check(code in 200..299) {result.optString("detail","Speech transcription failed ($code)")}
            check(alive()) {"Voice request stopped"}
            return result.getString("text")
        } finally {release(connection)}
    }
    fun send(text:String,progress:(String)->Unit):String {
        require(text.isNotBlank() && text.length<=2000) {"Say a command of at most 2000 characters."}
        val thread=VoiceChatStore.thread(c);val id="voice_cmd_"+UUID.randomUUID()
        val history=VoiceChatStore.history(c,thread)
        VoiceChatStore.message(c,thread,"usr_$id","user",text)
        val context=MobileRecords.context(c,JSONObject())
        val body=JSONObject().put("request_id",id).put("thread_id",thread).put("text",text).put("history",history).put("timestamp",ContextEventQueue.occurredAt()).put("device_approvals",true).put("calendar_connected",false)
            .put("_mobile_state",JSONObject().put("budget",context.getJSONObject("budget")))
        p.edit().putString("pendingRequest",id).commit()
        val completedActions=mutableSetOf<String>()
        try {
            // A reconnect reuses the immutable ID/body; it never creates a second command.
            repeat(2) {attempt ->
                var finished:JSONObject?=null
                val connection=open("/commands/stream",body)
                try {
                    check(connection.responseCode==200) {"Voice backend returned HTTP ${connection.responseCode}"}
                    val reader=connection.inputStream.bufferedReader()
                    var event="";val data=StringBuilder()
                    while(alive()) {
                        val line=reader.readLine() ?: break
                        if(line.isEmpty()) {
                            if(data.isNotEmpty()) {
                                val frame=JSONObject(data.toString())
                                frame.optJSONObject("_mobile_changes")?.let {MobileRecords.apply(c,it)}
                                when(event){
                                    "progress" -> progress(frame.optString("message","Working…"))
                                    "calendar_action" -> if(frame.optString("action_id") !in completedActions){action(frame,id);completedActions.add(frame.getString("action_id"))}
                                    "result" -> {finished=frame;break}
                                }
                            }
                            event="";data.setLength(0)
                        } else if(line.startsWith("event:")) event=line.substringAfter(':').trim()
                        else if(line.startsWith("data:")){if(data.isNotEmpty())data.append('\n');data.append(line.substringAfter(':').trimStart())}
                    }
                } catch(e:Exception) {if(attempt==1 || !alive())throw e} finally {release(connection)}
                if(finished!=null) {
                    val result=finished!!;val response=if(result.optString("status","ok")=="ok") result.optString("message").ifBlank {"Done."} else result.optString("error").ifBlank {result.optString("message","The request could not be completed.")}
                    VoiceChatStore.message(c,thread,"asst_$id","assistant",response)
                    p.edit().remove("pendingRequest").commit();return response
                }
            }
            error("Connection ended before the voice reply was confirmed. Check saved changes before repeating the command.")
        } catch(e:Exception) {
            val answer=e.message ?: "The voice request was interrupted. Check saved changes before repeating it."
            VoiceChatStore.message(c,thread,"err_$id","assistant",answer)
            throw e
        }
    }
}
