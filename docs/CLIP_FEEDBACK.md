# Private clip corrections

The preview's Your verdict section saves an owner label and optional note/time for the
current Surge account profile. It does not publish, requeue, change the original verdict,
or change thresholds. The separate correction table survives rejected-media cleanup and
candidate expiry. Source time ranges, transcript/visual fingerprints, prompt fingerprint,
model/request provenance when available and original decision are fixed on first save.
Older clips without saved request provenance remain unknown; current settings are
identified separately as feedback-time context. Editing a label changes only owner
feedback. This fingerprint is not a claim that deleted media was rewatched.

Source recording-hours and actual overlapping source ranges share one stable split.
Conflicting source groups quarantine a bridging new example. Existing examples never
move from training to evaluation when settings or labels change. The trial evaluator
requires enough good and bad held-out examples, complete boolean predictions on that
exact set, improved agreement and no rise in false accepts/rejections. A passing decision
trial alone cannot apply a change: model-run evidence, source regression and independent
review are still required. Automatic judge tuning is not enabled by these controls.

Corrections are an owner-selected diagnostic sample, not an unbiased estimate of judge
accuracy. Records are bounded; reaching the storage ceiling refuses new examples rather
than silently deleting old labels. Private feedback never enters public copy.

UI decisions: place these two explicit actions directly below the actual judge evidence,
using existing preview typography, spacing, buttons and fields. The saved label is shown
with pressed states and text. Loading disables input; save failures keep the note; retry
and account changes are guarded against stale responses. No new motion or navigation.
