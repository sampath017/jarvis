package com.jarvis.jarvis_collector

/** Wake only on a complete word, never eavesdrop on unrelated transcripts. */
object VoicePolicy {
    fun shouldRestore(requested:Boolean, enabled:Boolean, running:Boolean, microphone:Boolean, notifications:Boolean) =
        requested && enabled && !running && microphone && notifications
    // Wake detection is a small vocabulary task. Keep unknown speech rejectable;
    // command transcription still uses Whisper after activation.
    const val WAKE_GRAMMAR = """["jarvis", "hey jarvis", "hi jarvis", "hello jarvis", "hey what's up jarvis", "service", "services", "travis", "harvest", "nervous", "[unk]"]"""
    private val wake = Regex("\\b(?:(?:hey|hello)\\s+)?jarvis\\b", RegexOption.IGNORE_CASE)
    fun hasWake(text:String)=wake.containsMatchIn(text)
    fun isWakeGreeting(text:String)=Regex("^(?:(?:hey|hi|hello)[ ,.!?]*)?(?:what['’]?s up[ ,.!?]*)?jarvis[ ,.!?]*$",RegexOption.IGNORE_CASE).matches(text.trim())
    fun acceptsActivatedTranscript(text:String, woke:Boolean)=!woke || hasWake(text)
    fun afterWake(text:String):String? {
        val match=wake.find(text) ?: return null
        return text.substring(match.range.last+1).trim(' ', ',', '.', '!', '?', ':')
    }
    fun command(text:String,followUp:Boolean):String? = afterWake(text) ?: text.trim().takeIf {followUp && it.isNotEmpty()}
    fun stop(text:String)=text.lowercase().trim().trimEnd('.', '!', '?') in setOf("stop listening","stop voice mode","turn off voice mode","go to sleep")
}
