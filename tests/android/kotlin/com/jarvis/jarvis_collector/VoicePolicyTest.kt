package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class VoicePolicyTest {
    @Test fun shortWakeGreetingsCannotBecomeUnrelatedCommands() {
        for(text in listOf("Hey Jarvis", "Hi Jarvis!", "Hey, what's up Jarvis?", "Jarvis"))
            assertTrue(text, VoicePolicy.isWakeGreeting(text))
        assertFalse(VoicePolicy.isWakeGreeting("Hey Jarvis stop"))
        assertFalse(VoicePolicy.isWakeGreeting("Jarvis what time is it"))
        assertFalse(VoicePolicy.acceptsActivatedTranscript("Teşekkürler.",true))
        assertFalse(VoicePolicy.acceptsActivatedTranscript("I enjoyed this.",true))
        assertFalse(VoicePolicy.acceptsActivatedTranscript("Hey Google",true))
        assertTrue(VoicePolicy.acceptsActivatedTranscript("Hey Jarvis start a timer",true))
        assertTrue(VoicePolicy.acceptsActivatedTranscript("start a timer",false))
    }
    @Test fun restoreRequiresPriorListeningAndAllPermissions() {
        assertTrue(VoicePolicy.shouldRestore(true,true,false,true,true))
        assertFalse(VoicePolicy.shouldRestore(false,true,false,true,true))
        assertFalse(VoicePolicy.shouldRestore(true,false,false,true,true))
        assertFalse(VoicePolicy.shouldRestore(true,true,true,true,true))
        assertFalse(VoicePolicy.shouldRestore(true,true,false,false,true))
        assertFalse(VoicePolicy.shouldRestore(true,true,false,true,false))
    }
    @Test fun requestedGreetingsWakeWithoutACommand() {
        for (phrase in listOf("Hey Jarvis", "Hi Jarvis", "Hey, what's up Jarvis?", "Jarvis")) {
            assertTrue(phrase, VoicePolicy.hasWake(phrase))
            assertEquals(phrase, "", VoicePolicy.command(phrase, false))
        }
    }
    @Test fun wakePhrasesPreserveTheActualCommand() {
        assertEquals("start a five minute timer",VoicePolicy.command("Hey Jarvis start a five minute timer",false))
        assertEquals("what time is it",VoicePolicy.command("hello jarvis what time is it",false))
        assertEquals("make a note",VoicePolicy.command("jarvis make a note",false))
    }
    @Test fun unrelatedSpeechIsNotACommand() {
        assertNull(VoicePolicy.command("start a timer",false))
        assertNull(VoicePolicy.command("the jarvison family",false))
        assertFalse(VoicePolicy.hasWake("services are ready"))
    }
    @Test fun followupsAreRestrictedToAnArmedConversation() {
        assertEquals("add another minute",VoicePolicy.command("add another minute",true))
        assertNull(VoicePolicy.command("add another minute",false))
        assertEquals("",VoicePolicy.command("hello jarvis",false))
        assertTrue(VoicePolicy.stop("stop listening"))
        assertFalse(VoicePolicy.stop("stop the timer"))
    }
}
