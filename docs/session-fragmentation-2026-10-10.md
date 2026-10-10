# Session fragmentation diagnosis — October 10, 2026

Read-only investigation of the latest stored Jarvis chat, October 9 at 23:51 IST,
run `6a0eb277-ee2b-415d-8503-81d89dc19265`. The answer claimed no WALKING sessions
over the preceding two days. Raw Firestore observations, a local replay and the
live history API contradict that claim.

The live history window (October 7 23:50:54 to October 9 23:50:54 IST) returned
815 observations, 21 WALKING micromoments, 13 ON_FOOT micromoments and four
broader activity sessions. These are classifications and reconstructed
intervals, not proof of the user's actual walking duration. The result was
marked truncated. Cloud execution logs show one recall_context_history call,
followed by the final answer; no smaller-window follow-up queries were logged.

## Confirmed causes

1. `activity_sessions._moments` ends the current activity at its last observation
   whenever an `uncertain_sample` arrives. A later matching sample starts a new
   interval. Replay produced 76 endings marked `uncertain_observation` across
   all activities. This behavior was introduced by the October 9 evidence fix
   and is overly aggressive for logical session continuity.
2. `WALKING` and `ON_FOOT` are treated as mutually exclusive states. A generic
   on-foot sample closes an explicit walking interval. The normalizer tracks
   only one current label, so a later WALKING EXIT can then be called unpaired
   despite an earlier WALKING ENTER. ON_FOOT alone must not be relabelled as
   walking; it should be handled as compatible but less specific evidence when
   an explicit walking transition is already open.
3. The same reducer treats `TELEMETRY_PIPELINE_CHECK` with activity UNKNOWN as a
   motion observation. These diagnostic events close real activity intervals.
   They should carry no evidence about whether an activity ended.
4. A ten-minute gap clears the current motion state and can prevent matching a
   later exit with its recorded enter. Missing coverage should remain explicit,
   but the logical relationship between genuine transitions need not be lost.
5. The chat answer did not reliably summarize the retrieved evidence. It gave
   zero walking despite stored intervals and did not follow up the truncated
   result. The deterministic activity report currently does not cover the
   question “How much time i did walking?”, leaving the total to the model.

## Concrete examples (October 9, IST)

- 17:36:06.706 WALKING ENTER; 17:36:12.511 uncertain sample;
  17:37:12.104 WALKING EXIT. The reducer reduces this matched transition pair
  to a zero-duration walking moment because the uncertain sample clears the
  active interval before the exit arrives.
- 14:40:16.477 WALKING ENTER; 14:40:22.882 accepted ON_FOOT sample;
  14:42:21.670 WALKING EXIT. The generic label replaces WALKING, and the exit
  loses its pairing.
- 23:15:05.852 WALKING ENTER; 23:15:15.458 diagnostic pipeline check with
  UNKNOWN. The diagnostic record ends the walking interval after ten seconds.
- Accepted ON_FOOT samples from 23:21:11.774 through 23:37:40.337 form a
  16-minute-29-second observed span, with further samples from 23:38:44.053
  through 23:43:01.337. These support on-foot activity, not an exact confirmed
  walking total.

## Required correction

Keep logical transition sessions and evidence coverage separately. Match
genuine start/end events independently of noisy sample labels; retain uncertainty
inside a session instead of declaring an exit. Ignore diagnostic events in the
motion reducer. Preserve generic on-foot evidence without inventing a walking
classification. Return deterministic totals with explicit coverage limitations,
and retrieve complete smaller windows when history is truncated.

The reminder engine separately lacks a condition-relative duration trigger
that starts a durable timer at walking entry. Its missing timer support does
not mean the phone cannot observe walking exits; the chat conflated these.

No production code, saved history, reminders or deployed services were changed
during this diagnosis.

## Implemented and verified

Deployed backend revision `jarvis-backend-00089-9xf` with 100% traffic and installed
the release APK on the connected phone, preserving its data. The monitoring
service restarted and is running in the foreground.
After returning the phone to its home screen, backend request
`621d413e-aa57-4874-bca0-b3b0bc39e464` completed with a fresh location observed
at 2026-10-10 01:21:15 IST and received at 01:21:17 IST.

- Matching transitions now survive uncertain samples, diagnostic checks, generic
  ON_FOOT observations and long observation gaps. Missing evidence remains inside
  the interval as coverage gaps. Open tails end at the last positive observation
  for duration calculations. These rules cover future sessions and historical replay.
- Activity duration questions use deterministic totals from complete session
  evidence. Dense queries subdivide with a bounded budget; a capped timeline
  preview no longer makes complete session history appear incomplete. Truly
  incomplete queries cannot produce a reliable total. Uncertain coverage is
  excluded from classification-supported totals and shown in the mobile app.
- Routine learning excludes uncertain stationary spans and discards the older
  evidence-version training state.
- One-shot reminders support a durable delay after a fresh activity ENTER.
  This measures elapsed time after the start, not continuous exercise. Firestore
  reservations and named authenticated Cloud Tasks preserve the deadline through
  retries and restarts. Deleted, paused or changed policies invalidate old tasks.
  The deleted water reminder was not restored.

Validation: 94 backend tests and 8 Flutter tests passed; Android release build and
installation succeeded. Live history now returns the October 9 17:36:06–17:37:12
and 23:15:05–23:44:47 IST WALKING pairs with detected exits. The latter is one
29m41s logical interval with 6m31s of uncertain coverage, rather than being split
by the diagnostic event. The user-reported bike correction remains intact.

For the investigated two-day window, live deterministic output reports 48m06s
in classification-supported walking intervals. The much larger full boundary
span includes 4h46m13s of uncertain evidence and is explicitly excluded from that
supported total; neither figure proves actual continuous exercise duration.

An isolated test user with no registered phone verified real Cloud Tasks timer
delivery: duplicate starts preserved the deadline and exactly one notification
was created without another phone event. Test reminder, timer and outbox records
were removed afterwards. No test activity was inserted into the user's history.
