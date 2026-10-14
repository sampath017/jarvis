package com.jarvis.jarvis_collector

import org.junit.Assert.assertEquals
import org.junit.Test

class UsageAccumulatorTest {
    @Test fun clipsMidnightAndStopsAtScreenOff() {
        val c = UsageAccumulator(100, 200)
        c.resume("instagram", "main", 80)
        c.screenOff(130)
        assertEquals(mapOf("instagram" to 30L), c.finish())
    }
    @Test fun switchingAppsDoesNotDoubleCount() {
        val c = UsageAccumulator(0, 100)
        c.resume("a", "first", 10)
        c.resume("b", "main", 30)
        c.pause("a", "first", 40)
        c.pause("b", "main", 70)
        assertEquals(mapOf("a" to 20L, "b" to 40L), c.finish())
    }
    @Test fun oldActivityPauseAndDuplicateResumeDoNotResetNewActivity() {
        val c = UsageAccumulator(0, 100)
        c.resume("a", "first", 10)
        c.resume("a", "second", 30)
        c.pause("a", "first", 40)
        c.resume("a", "second", 50)
        assertEquals(mapOf("a" to 90L), c.finish())
    }
    @Test fun resumedActivitiesWhileLockedDoNotCountAsScreenTime() {
        val c = UsageAccumulator(0, 100)
        c.resume("instagram", "main", 10)
        c.lock(20)
        c.resume("wallpaper", "main", 30)
        c.screenOff(40)
        c.resume("other", "main", 50)
        c.screenOn(60)
        c.unlock(70)
        c.resume("instagram", "main", 80)
        assertEquals(mapOf("instagram" to 30L, "other" to 10L), c.finish())
    }
    @Test fun noObservationDoesNotInventUsage() {
        assertEquals(emptyMap<String,Long>(), UsageAccumulator(0, 100).finish())
    }
    @Test fun resumeBeforeUnlockCountsOnlyAfterUnlock() {
        val c = UsageAccumulator(0, 100)
        c.lock(5)
        c.resume("instagram", "main", 10)
        c.unlock(20)
        c.pause("instagram", "main", 80)
        assertEquals(mapOf("instagram" to 60L), c.finish())
    }
    @Test fun resumeBeforeScreenInteractiveDoesNotLoseTheSession() {
        val c = UsageAccumulator(0, 100)
        c.screenOff(5)
        c.lock(6)
        c.resume("youtube", "main", 10)
        c.unlock(20)
        c.screenOn(30)
        c.pause("youtube", "main", 80)
        assertEquals(mapOf("youtube" to 50L), c.finish())
    }
}
