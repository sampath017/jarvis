# Session continuity and evidence coverage

The October 10 investigation found that logical activity sessions were being
fragmented by uncertain samples, generic ON_FOOT labels, diagnostic events and
observation gaps. Retrieved history was also being summarized incorrectly when
truncated. The useful distinction remains: transition boundaries and observed
coverage are separate facts.

For example, WALKING ENTER followed by a low-confidence sample and a genuine
WALKING EXIT must not become a zero-duration interval merely because the sample
was uncertain. A generic ON_FOOT sample can be compatible with an existing
explicit WALKING transition; it does not independently prove walking. Diagnostic
pipeline checks provide no motion boundary. Long gaps remain unknown coverage
without inventing an EXIT or continuous activity.

Current evidence normalization and `activity_sessions` reducers preserve these
relationships. Open tails end at the last supported observation for duration
calculations. Supported totals exclude uncertainty; full logical boundary spans
must not be presented as confirmed continuous exercise. Truncated queries require
smaller windows before a complete recap. User reports retain their attribution
and do not fabricate sensor/GPS observations.

Explicit phone power-off intervals additionally break activity pairing across
disabled monitoring and explain only the missing monitoring coverage. One-shot
delays after fresh activity ENTER are a separate reminder feature: mobile mode
converts a satisfied trigger into an Android clock reminder. It measures elapsed
time since entry, not verified uninterrupted exercise.

Sources: `backend/src/backend/activity_evidence.py`, `activity_sessions.py`,
`context_history.py`, `power_history.py` and `services/activity_reminder_timers.py`.
Regressions include session continuity, sparse context, motion evidence, power
history and delayed-reminder policy. These checks do not establish real-world
classification accuracy or guaranteed Android background delivery.
