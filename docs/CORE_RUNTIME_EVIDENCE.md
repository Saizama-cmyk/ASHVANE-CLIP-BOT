# Core runtime evidence

Core now receives bounded metadata from warning/error records in known Ashvane source
modules: module identifier, source line, severity, allowlisted exception type, occurrence
count and timestamps. It never formats a record or retains its message, arguments,
traceback, locals, filenames or user-defined logger identifiers. The in-memory sample and
time window are configurable. A full sample is marked incomplete. Collection begins and
ends with Core's master switch; it does not scan historical logs.

Existing pipeline memory supplies aggregate queue phase counts, ages, slot occupancy and
GPU numbers. Missing measurements remain null. Candidate IDs, streamer identities, media
paths and transcripts are omitted. There is no new sampling process or inference task.
The director receives this evidence on its next cycle, through the existing local-only
model and bounded agent budget. While business work is active, idle-only gating continues
to prevent model requests. Existing independent reproduction/review/promotion/rollback
requirements remain unchanged. Fault counts identify investigations, not diagnoses.

Focused coverage deliberately uses a message that throws if formatted, private negative
controls, unknown logger names, full/expired samples, busy work and an actual director
input boundary. Full suite: 1,008 passed, five skipped. Frozen startup/API and source-
matching dashboard checks passed before installation on 13 October 2026.
