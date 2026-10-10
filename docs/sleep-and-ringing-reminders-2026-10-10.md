# Sleep lookup and ringing reminders

## Observed sleep failure

The latest Jarvis chat at 08:38 IST on 10 October 2026 asked "How I slept?".
Its immediate local reply reported missing Health Connect sleep read access.
`HealthService.isHealthQuestion` matched the request; `hasSleepAccess` returned
false, so no sleep query was performed. This was not a backend memory lookup
failure and is not evidence that the user did not sleep.

The updated reader requests Android's sleep read permission when necessary.
Settings also contains a Sleep records connection tile. A sleep tracking app or
watch must supply sleep sessions to Health Connect. Stationary phone data does
not establish sleep. The existing reader reports the longest recorded session
since 6 PM yesterday, not sleep quality or total sleep across multiple sessions.

## Delivery options

- `notification`: existing ordinary notification behavior.
- `alarm`: an Android alarm that rings.
- `in_app_call`: a free ringing reminder screen. Answer stops ringing and reads
  the text with an installed offline English Android voice. It is neither a
  telephone call nor a live assistant conversation.

Chat create/update tools store the mode, and each active reminder has a Change
alert type menu. Examples: "Set an alarm for 7 AM tomorrow" and "Remind me in 20
minutes to leave, and ring me in-app." These are one-shot reminders; daily
recurrence is not implemented.

Time-only ringing reminders are persisted on Android and scheduled with
`AlarmManager.setAlarmClock`. They survive process exit and are restored after
reboot, app updates, clock changes, and granting exact-alarm access. The phone
must first download the reminder. Changes made on another device cannot cancel
an offline phone's previously downloaded alarm until it syncs.

Context conditions are never converted into a plain time alarm. Activity,
location and activity-delay reminders continue through the existing backend
notification outbox and FCM/polling, and require connectivity. No new calling
provider, account, paid voice API, or subscription was added. Existing Jarvis
backend/inference costs are unchanged.

Notifications, Alarms & reminders, and full-screen access are exposed in
Settings. Android may show a heads-up alert while the phone is unlocked rather
than opening the whole screen. Sound follows the user's channel, volume and
Do Not Disturb settings. Android force-stop or a powered-off device prevents
normal alarm delivery. Ringing expires after two minutes; alerts arriving more
than 15 minutes late are shown silently as missed reminders. Snooze is five
minutes and requires exact-alarm permission.

Local time alarms and cloud notifications share a normalized occurrence key to
avoid ringing twice. Pause/delete cancels downloaded pending alarms; snoozes
are also cancelled when their reminder is paused, removed, or changes alert
type. Delivery acknowledgement remains separate from the user's Answer/Dismiss.

## Release and verification

Code changes are uncommitted. On 10 October 2026, the backend was deployed as
`jarvis-backend-00090-r9p` with 100% traffic. Its health check is healthy, the
live schema exposes all three delivery modes, and GET /reminders returns 200.
The tested APK was installed on the connected phone without clearing app data.
It launches without matching fatal/SQLite/plugin errors in the inspected startup
logs. Android 13 reports exact-alarm and full-screen permissions granted.
The APK SHA-256 is `7007e866e6c6088f964db788918d8571020d3e251c55e7038770682a33fd329a`.

Checks passed: 32 backend tests, five focused Flutter tests, three Android alarm
policy tests, Flutter static analysis, and the final APK build. Device behavior
including audible locked-screen ringing, snooze, reboot restoration and the
Health Connect permission UI still needs an acceptance run. No test alarm or
call was created during deployment.

Primary references:
- https://developer.android.com/develop/background-work/services/alarms
- https://developer.android.com/about/versions/14/behavior-changes-14#secure-fsi
- https://developer.android.com/reference/android/app/Notification#FLAG_INSISTENT
- https://developer.android.com/health-and-fitness/health-connect/experiences/sleep
