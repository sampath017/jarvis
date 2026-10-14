# Sleep records and ringing reminders

This guide describes current behavior; the filename is retained for existing links.

## Sleep and steps

The shared chat agent selects `get_health_records` for explicit date windows.
Android `HealthService` reads Health Connect only on request. Steps and sleep have
separate read permissions, granted through Settings/Health Connect. A read cannot
grant missing access. A watch or other health app must supply the requested
records; absent sleep sessions mean unknown coverage, not proof of no sleep.
Stationary phone data and movement duration are not substitutes for these datasets.

The phone returns structured days/sessions and source/coverage information for
model synthesis. Sleep windows are aligned to the requested IST day and capped at
now; multi-day requests remain bounded. This is not a local keyword-generated
sleep-quality answer or a background health polling loop.

## Alert modes and delivery

Reminders support ordinary `notification`, ringing `alarm`, and `in_app_call`.
The last is a local reminder screen: Answer stops ringing and reads the saved text
with an installed Android voice. It does not dial a telephone or start a live
assistant conversation.

Android owns reminder records. Time-only ACTIVE reminders are reconciled into
AlarmManager schedules, including process-exit/reboot/update restoration. Context
conditions require fresh eligible activity/location evidence and successful
processing. After a genuine fresh activity ENTER satisfies a one-shot elapsed
activity delay, the backend returns a time-only reminder; Android then owns the
remaining deadline without a continued server connection.

Keep notification, exact-alarm and (when used) full-screen permissions enabled.
Android channel/volume/Do Not Disturb settings affect presentation. A foreground
phone may use a heads-up alert. Jarvis Off, force-stop or a powered-off phone can
prevent normal delivery; WorkManager processing is not an exact timer.

Occurrence keys deduplicate local-clock and returned context notifications.
Pause/delete cancels applicable alarms/snoozes. Ringing expires after two minutes;
arrivals more than 15 minutes late become silent missed reminders. Snooze is five
minutes and needs exact-alarm access.

Main sources: `health_service.dart`, `phone_data_executor.dart`,
`activity_reminder_timers.py`, `ReminderAlerts.kt` and `ReminderAlertPolicy.kt`.
See [background delivery](background-context-delivery.md) and
[phone power](runtime-power-2026-10-13.md). Unit/widget tests exercise contracts and
policy; audible ringing, OEM restrictions and permission presentation require
real-device acceptance checks.
