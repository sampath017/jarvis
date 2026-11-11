# Jarvis Clock

Clock is a personal app inside Apps, alongside Notes. Both remain available in the local Apps view when the Jarvis assistant is off. Clock timing, sounds and state are owned by Android rather than a backend process or Flutter timers.

## Features

- Alarms: named one-time/repeating alarms, ISO weekdays, enable/disable, skip next, edit/delete, custom system-picker alarm sounds, vibration, snooze, volume buttons and gradual volume.
- Timers: multiple named countdowns, presets, pause/resume/reset, add time, running countdown notifications with actions, native ringing and stop/snooze controls.
- Stopwatch: monotonic elapsed time, pause/resume, lap and total times, reset and share.
- World clocks: searchable Android IANA timezone catalog, live local dates/times, UTC offsets, time differences and removal. Timezone database rules supply DST handling.
- Bedtime: wind-down notifications and recurring wake alarms, correctly shifted weekdays for bedtime before the next morning; original offline rain/ocean/brown-noise sounds with a 30-minute sleep timer, bedside display and a link to Android quiet-hours settings.
- Home-screen widget: live digital time/date and the next alarm; tap opens Clock.
- Settings: local volume, gradual ringing, snooze length, automatic silence duration, volume-key action, default sound and Android permission links.
- Chat controls: `get_clock`, `create_clock_timer` and `update_clock` use the existing private phone action channel. Stable device receipts protect creation on network retries.

Google account/media integrations, Pixel-specific sunrise/Wellbeing grayscale, Wear OS and OS-level default-assistant privileges are not provided by this local feature set. The app does not claim exact Google-product parity.

## Timing and power

`jarvis_clock` preferences hold committed clock state independently of the master assistant switch. Alarms use AlarmManager wall-clock scheduling; timers and the stopwatch use elapsedRealtime within one boot. Timer wall deadlines provide restart recovery. Native ringing uses a foreground playback service; Clock notifications are excluded from the assistant's notification cleanup. Clock state survives app updates and process loss. Android force-stop, revoked alarm/notification permissions and OEM restrictions still affect delivery. A missed timer after reboot is shown finished instead of ringing retroactively.

Native boot, package-replacement, wall-clock/timezone and exact-alarm-permission receivers restore schedules. A foreground permission sheet makes failures explicit: Clock does not silently replace exact timing with inexact alarms. Model-selected clock writes report success only after a phone receipt. Notes retain normal SQLite storage and skip assistant sync while power is off.

The clock store is local preferences. The existing SQLite-only Drive backup does not yet include clock preferences; do not describe it as a Clock backup.

## Validation and deployment

The 10 November 2026 update targets the documented full-history-debug endpoint. Backend Clock tools are on development revision `jarvis-backend-00201-mif`; production traffic remains on its previous revision. Phone installation uses `adb install -r`, retaining the original data.

Native policy tests cover weekdays, DST, monotonic timing and reboot deadline conversion. All 182 Flutter tests passed, including Clock navigation and controls with assistant power off. Fifty-five focused backend checks passed for clock tools, phone tools and write approvals. The full backend suite was interrupted after it stalled in the existing command-reconnection test; no full-backend success is claimed.

Phone clock-only instrumentation created UUID-labelled test timers, checked duplicate receipts, pause/resume, extension, native notification/ringing while the assistant was off, then removed its own test items and restored power. Personal note/reminder/place/chat rows matched the pre-install snapshot. Actual reboot/OEM long-duration timing and physical daylight-saving transitions were not tested.
