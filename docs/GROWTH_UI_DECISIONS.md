# Growth dashboard decisions

Subject: Ashvane's owner needs to compare measured content performance with the local production system, then choose a useful next action.

Ground: a panoramic media observatory. The upper strip answers what has been measured; the central band compares a time chart, the actual supervisor roster and live production telemetry. Tables carry the evidence below. The chart does not pretend that platform reporting is live.

Palette: blue-biased void #070A10, hull #111925, text #DFE8ED, secondary telemetry #98A9BA, rails #304353, accretion amber #DAA66B. Additional chart series use muted blue #8DAFD0, sage #93B6A3, rose #C99AAB and lavender #ADA5C5 so individual posts remain distinguishable by labels as well as color.

Type: Bahnschrift instrument headings; Segoe UI reading and controls; tabular figures for comparable metrics. No oversized marketing numbers or decorative headings.

Space: 8/12 inside controls and evidence rows; 24/36 between sections. Three primary columns use panoramic screens without stretching paragraphs. Below tablet width, the reading order becomes metrics, chart, supervisor, local production and evidence tables.

Shape: 8-pixel corners, tonal elevation only. Straight chart baselines and table rows contrast with one compact orbital supervisor map.

Motion: 120 ms press and selection feedback only. No moving graph lines or fabricated processing pulses. Reduced motion removes spatial button feedback.

Signature: a compact real supervisor constellation between timestamped platform measurements and live local telemetry. It links directly to the shared Supervisor page rather than duplicating controls or inventing a fifth business.

Critique: a generic analytics page would fill a monitor with rising sparklines and percentage changes. Here every number comes from a report or local state, missing values stay unknown, and the time chart plots actual per-post captures rather than implying daily views from cumulative totals. At 3400x1440 the three-column instrument band and wide evidence table provide a panoramic working surface; smaller displays use the same data in a readable stack.

Data policy: poll only while Growth is visible, every five seconds, using cached /api/growth. That request must not contact platform APIs. The explicit YouTube sync action reads the owner's linked channel metadata/statistics, never downloads videos or imports source clips. Existing Twitch import remains in the clip library. Analytics capture times and local fetch times have different labels. Filters derive only from returned platforms/content; no fabricated account selector when the payload lacks account identities.

Validation: growth.js and all inline JavaScript pass syntax checks. HTML parsing confirms 472 unique IDs and all 24 Growth references resolve. Code checks with a mocked DOM/API pass visible-only cached polling, actual capture-point chart data, unknown measurements, escaped titles and safe links, local timing/roster/channel rendering, profile-bound sync and rejection of stale responses after profile changes. The original Twitch import handler remains attached to exactly one button inside Clips. UTF-8 checks confirm no mojibake in the new Growth or Supervisor assets. The skill checker reports zero findings for Growth. No UI automation, paid services or external media generation were used.
# Watch-outcome addition, 13 October

Preserve the existing quiet Growth layout and its typography/spacing. Add the actual
watch duration, percentage and subscriber gains as a secondary line below each tracked
post's title, with the report's requested dates and capture timestamp. This avoids
turning the main table into a wide wall of columns on phone. A single status line near
learning comparisons explains permission required, unavailable/empty data, disabled,
or ready. Never show missing metrics as zero; percentages may exceed 100 for replays.
No new animation or navigation. Account changes clear these fields with the existing
loading state; failures use existing notices and refresh controls. Existing connect
actions handle Google consent. The neural network remains the page's visual signature.

