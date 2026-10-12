# ChatSpiked channel and rejection audit — 11 October 2026

Your screenshots demonstrate real reach: 30.1K channel views, 147 likes, 3 comments,
3 shares and 2 subscribers. The best shown Short has 6,959 views; the latest had
2,091 after roughly four hours. This supports keeping the working clip format.
It does not establish consistent 100K performance, revenue, or whether rejected
clips would have performed better. Likes divided by the displayed total views
are about 0.49%; subscriber conversion is visibly limited. These counts have
different possible refresh windows, so neither ratio is a controlled benchmark.

The connected read-only YouTube Data API confirmed the channel is
[ChatSpiked](https://youtube.com/channel/UCVXx2jn3cLXwFngjMSV31nQ).
Its separate snapshot returned 27,348 views, 2 subscribers and 18 videos, while
the uploads playlist returned 19 entries. These differences do not invalidate
the screenshots. Public/API counters can differ in refresh and counting; the
19 returned uploads had a median of 622 views. Private engaged views, retention,
viewed-versus-swiped and revenue were not available through this Data API audit.
No uploads were changed or published during the audit.

## What actually needed fixing

The local database snapshot contained 514 rejected records. Their recorded reasons
included 214 dead-air decisions, 128 moment decisions, **91 model-output errors**,
39 technical-QC decisions and 31 final-review decisions. Only five of the dead-air
decisions came from the early speech/loudness shortcut; most came from the model.
These are recorded categories, not independently confirmed clip-quality labels.

Concrete defects found and addressed:

- Invalid model responses were labelled rejected. They now become visible failures
  held from publishing, separate from editorial rejections and their cleanup.
- Pause removal shortened a finished clip, but final review still expected the
  original length and source timestamps. Renders now save their edit map, and
  review checks that duration and maps speech/evidence into final-video time.
  Older shortened exports without an edit map require Studio re-rendering rather
  than receiving a false quality rejection.
- Silence tightening could remove quiet action around the judged payoff. The
  payoff now has a configurable protected interval, including Studio re-renders.
- High-confidence clips could fail merely for model-invented genre preferences
  such as `no_joke` or `low_stakes`. Explicit observed defects still veto clips;
  hook, context, payoff, pacing, evidence and confidence requirements remain.
- Near-miss second look was disabled in the live configuration. It is enabled,
  uses more frames and the proper imported-clip threshold, and accepts a worse
  second assessment too. It does not retry genuine failures until approved.
- The final reviewer exhausting its evidence-repair budget is now unavailable,
  rather than a quality rejection eligible for rejected-media cleanup.

There were no surviving raw files at the 514 rejected records' saved source paths,
but **31 rejected finished videos** still existed. Five finals and their decisions
were copied into the private audit folder before cleanup. Metadata alone is not
hundreds of large videos. The cleanup reports actual deleted files and bytes.

One preserved Pangi final was examined at 0/3/6/9 seconds: face/game split,
reaction and Dutch captions are present. The rejection partly inferred missing
speech from the words absent on sampled caption frames. That is not reliable:
captions at four sampled instants cannot establish the full spoken content.
This sample does not independently prove the joke is strong; no continuous
audio evaluation was available.

## Keep, measure, and improve

Keep readable captions and the reaction/source split when both matter. The
[streamer benchmark](SURGE-QUALITY-BENCHMARK-20261011.md) compared ten popular
Shorts, a popular TikTok, an Instagram contrast and two actual ChatSpiked uploads.
It supports quiet banter, prediction, skill and useful information as legitimate
viewer value, and identifies crowded hook overlays and source cropping as
specific editing concerns. This patch fixes selection/timeline faults; it does
not claim an automatic content-aware crop overhaul has been delivered.

Only the new bridge upload had a local posting record in this database snapshot;
the learning cache had zero mature measured posts. Older public channel history
was not connected to those local decisions. Consequently, the existing feedback
system was not learning from all the channel's historical uploads. A longer
connected history and private Shorts metrics are needed before judging changes
by retention or subscriber conversion. No claim that these fixes ensure 100K
views is supported.

Rejected media is now checked every 20 minutes, with the existing 15-minute
review grace period; see [cleanup details](REJECTED_MEDIA_CLEANUP.md). Decisions
remain available after media deletion.

## Gaps

API data and local database were snapshots on 11 October 2026. Counters change;
aggregate refresh differences were not reconciled. Private retention, engaged
views, revenue and viewer experiments were not collected. Most rejected raw
videos were already gone, so no false-rejection rate can be calculated. Five
final exports were preserved; one was sampled directly in this audit and the
external benchmark separately examined two published uploads. Sound and exact
comic timing remain partly unverified. No titles, rights, or monetization status
of old posts were adjudicated. Detailed story findings and actual preview limits
are in [the Hollow audit](HOLLOW_QUALITY_AUDIT.md). Social Studio currently creates
ideas, scripts and captions; it does not yet render or publish finished videos.
