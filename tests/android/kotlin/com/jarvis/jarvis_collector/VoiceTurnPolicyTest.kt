package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class VoiceTurnPolicyTest {
    @Test fun playbackCompletionFromInterruptedReplyCannotResumeTheMicrophone() {
        val tokens=VoicePlaybackToken()
        val old=tokens.next()
        tokens.invalidate()
        assertFalse(tokens.isCurrent(old))
        val next=tokens.next()
        assertFalse(tokens.isCurrent(old))
        assertFalse(tokens.isCurrent("${next}_part_0"))
        assertTrue(tokens.isCurrent(next))
    }
    @Test fun ownSpokenReplyAndBriefNoiseDoNotInterrupt() {
        val reply="The weather tomorrow will be sunny and warm"
        assertFalse(VoiceTurnPolicy.isInterruption("tomorrow will be sunny",reply,16000,true))
        assertFalse(VoiceTurnPolicy.isInterruption("no wait",reply,512,true))
        assertFalse(VoiceTurnPolicy.isInterruption("",reply,16000,true))
        assertTrue(VoiceTurnPolicy.isInterruption("no wait",reply,8192,true))
        assertTrue(VoiceTurnPolicy.isInterruption("tell me something else",reply,8192,false))
        assertFalse(VoiceTurnPolicy.isInterruption("noise",reply,8192,false))
    }
    @Test fun endingConversationIsDifferentFromDisablingTheMicrophone() {
        assertTrue(VoiceTurnPolicy.endConversation("Goodbye!"))
        assertTrue(VoiceTurnPolicy.endConversation("end conversation"))
        assertFalse(VoiceTurnPolicy.endConversation("stop the timer"))
        assertFalse(VoiceTurnPolicy.endConversation("stop listening"))
        assertTrue(VoicePolicy.stop("stop listening"))
    }
}
