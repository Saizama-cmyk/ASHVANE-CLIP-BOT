# Final publication checks

The final gate checks every existing public-copy field for leaked editorial text,
including drafts for disabled destinations. For each enabled destination it uses
`scheduler.compose_post` and `public_snapshot`, so the reviewer also receives public
templates, credit lines, brand text, YouTube suffixes, and upload metadata limits.
Enabled destinations are included while disconnected; credentials and account
configuration are never sent to the reviewer.

The existing `honest_hook` verdict covers all public claims, including titles,
descriptions, captions, messages, hashtags and tags, against the actual finished
frames and mapped timed speech. A mandatory addendum preserves custom final-review
prompts and the existing `CUT DATA` JSON format. Private source-review evidence is
identified separately and is not presented as public copy.

Approval reuse requires the same SHA-256 media bytes, file size and timestamp,
publication policy version, public-copy bundle, saved timeline, transcript and
timed words, reviewer/frame settings, technical QC, edit/style and safety settings.
Only the resulting digest is saved. Account credentials are excluded. Changing a
description, template, tag, suffix, enabled destination, word timing or QC setting
invalidates approval even when the video file is unchanged. Replacing bytes while
preserving file size and timestamp also invalidates approval.

Saved render timelines are checked against the probed export duration using
`review.final_duration_tolerance_s`. Truncated or overlong exports are held before
frame extraction and model review. Older exports without a saved timeline retain
the stricter existing alignment rule and may require re-rendering.

These checks do not turn sampled images into proof of every caption or an audio
listening assessment. Actual listening, full caption verification and claims about
unseen frames must not be reported as completed on this evidence alone.

The opening audio check decodes bounded mono PCM from the export and its aligned
original, then compares sustained loud broadband windows. An increase introduced
by editing holds publication; already-noisy source/game effects are not rejected
merely for that characteristic. FFT size, sample rate, duration, level, flatness,
share thresholds and decode deadlines are configurable. Missing source and intros
are explicitly unavailable, not an invented listening pass. This is a conservative
artifact detector, not universal speech/music quality assessment or proof of the
cause of any previously reported static. Real AAC regression fixtures cover added
noise, unchanged noisy source, clean tone, silence and missing originals.

The manual publish fallback now saves the renderer's actual timeline, so tightened
or intro exports can be aligned and reviewed rather than treated as an unknown old cut.
