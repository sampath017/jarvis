package com.jarvis.jarvis_collector

/** Pure turn rules shared by capture, playback and regression tests. */
object VoiceTurnPolicy {
    const val GREETING = "Hi, how can I help you?"
    const val IDLE_MS = 120_000L
    const val END_SILENCE_SAMPLES = 12_800
    fun newConversation(text:String)=text.lowercase().trim().trimEnd('.', '!', '?') in
        setOf("new voice chat", "new voice conversation", "new conversation", "start a new conversation")
    private fun words(text:String)=Regex("[a-z']+").findAll(text.lowercase()).map{it.value}.toList()
    fun endConversation(text:String)=text.lowercase().trim().trimEnd('.', '!', '?') in
        setOf("end conversation", "goodbye", "bye jarvis", "that's all", "go to sleep")
    fun isInterruption(partial:String, spoken:String, speechSamples:Int, echoCancelled:Boolean):Boolean {
        val heard=words(partial)
        if(speechSamples < 4_096 || heard.isEmpty()) return false
        val echo=words(spoken).toSet()
        if(heard.all {it in echo}) return false
        return echoCancelled || heard.size>=2 || VoicePolicy.hasWake(partial)
    }
}

/** Old completion callbacks cannot resume listening over a newer turn. */
class VoicePlaybackToken {
    private var generation=0L
    fun next():String="jarvis_reply_${++generation}"
    fun invalidate(){generation++}
    fun isCurrent(id:String?)=id=="jarvis_reply_$generation"
}
