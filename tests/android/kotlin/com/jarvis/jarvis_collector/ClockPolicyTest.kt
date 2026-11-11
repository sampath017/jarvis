package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

class ClockPolicyTest {
    private fun at(value:String)=Instant.parse(value).toEpochMilli()
    @Test fun oneTimeAlarmAfterItsTimeMovesToTomorrow() {
        assertEquals(at("2026-11-10T01:30:00Z"),ClockPolicy.nextAlarm(7,0,emptySet(),at("2026-11-09T02:00:00Z"),ZoneId.of("Asia/Kolkata")))
    }
    @Test fun weekdaysSkipTheWeekend() {
        assertEquals(at("2026-11-09T01:30:00Z"),ClockPolicy.nextAlarm(7,0,setOf(1,2,3,4,5),at("2026-11-06T04:00:00Z"),ZoneId.of("Asia/Kolkata")))
    }
    @Test fun dstGapResolvesToAnExistingLocalTime() {
        assertEquals(at("2026-03-08T07:30:00Z"),ClockPolicy.nextAlarm(2,30,emptySet(),at("2026-03-08T05:00:00Z"),ZoneId.of("America/New_York")))
    }
    @Test fun timerIgnoresWallClockChangesWithinABoot() {
        assertEquals(8_000L,ClockPolicy.remaining(10_000,20_000,3,3,2_000,999_000))
        assertEquals(0L,ClockPolicy.remaining(10_000,20_000,3,3,12_000,1))
    }
    @Test fun rebootUsesPersistedTimerDeadline() {
        assertEquals(5_000L,ClockPolicy.remaining(10_000,20_000,3,4,100,15_000))
    }
    @Test fun stopwatchDoesNotCountThePausedPeriod() {
        assertEquals(7_000L,ClockPolicy.measured(5_000,10_000,50_000,3,3,12_000,999_000))
    }
}
