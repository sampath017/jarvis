package com.jarvis.jarvis_collector

import org.junit.Assert.*
import org.junit.Test

class ReminderAlertPolicyTest {
    @Test fun localAndPushUseSameOccurrenceDespiteTimezoneOrFractionFormat() {
        assertEquals(ReminderAlertPolicy.key("r", "2026-10-10T07:30:00+05:30"),
            ReminderAlertPolicy.key("r", "2026-10-10T02:00:00.000000Z"))
        assertNotEquals(ReminderAlertPolicy.key("r", "2026-10-10T02:00:00Z"),
            ReminderAlertPolicy.key("r", "2026-10-11T02:00:00Z"))
    }
    @Test fun contextConditionsAndInactiveAlarmsCannotBecomeClockAlarms() {
        assertTrue(ReminderAlertPolicy.timeOnly("in_app_call", "ACTIVE", 1000, false))
        assertFalse(ReminderAlertPolicy.timeOnly("in_app_call", "ACTIVE", 1000, true))
        for (s in listOf("PAUSED", "DELETED", "COMPLETED")) assertFalse(ReminderAlertPolicy.timeOnly("alarm", s, 1000, false))
        assertFalse(ReminderAlertPolicy.timeOnly("notification", "ACTIVE", 1000, false))
        assertFalse(ReminderAlertPolicy.timeOnly("alarm", "ACTIVE", ReminderAlertPolicy.epoch("invalid"), false))
    }
    @Test fun oldOfflineAlertsAreSilentButFreshAlertsRing() {
        assertTrue(ReminderAlertPolicy.missed(1000, 1000 + 16 * 60_000))
        assertFalse(ReminderAlertPolicy.missed(1000, 1000 + 10_000))
    }
}
