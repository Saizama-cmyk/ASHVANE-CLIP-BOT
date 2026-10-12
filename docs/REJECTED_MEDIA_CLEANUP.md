# Surge rejected-media cleanup

Surge automatically checks rejected clips every 20 minutes (`clip.rejected_cleanup_min`).
The existing review period (`clip.keep_rejected_hours`, initially 15 minutes) applies before
automatic deletion, so a newly rejected cut normally remains reviewable for 15–35 minutes.
Setting the cleanup interval to zero turns the automatic check off. Cleanup runs while Surge
is enabled, independently of whether any publishing platform is connected.

**Delete all rejected** in the desktop source bin and phone clip list removes eligible media
immediately after confirmation. It keeps the candidate, transcript, judgement, public-copy
draft and decision evidence. A rejected record remaining in the list is therefore expected;
the record alone does not mean its video still consumes storage. Reported counts and bytes
come from successful individual file deletions, and may correctly be zero.

Only generated source cuts, saved rejected outputs, candidate-specific previews, captions,
concat lists and extracted frames qualify. Paths must match expected generated filenames and
approved work/clip locations. No shared capture segments or folders are recursively removed.
Links, junctions, hard links, other candidates' saved media, active processing, edits, uploads,
successful posts, failed clips and non-rejected stages are excluded. File deletion and complete
Studio rendering share a media lock. The regular configured long-term retention policy remains
separate from this rejected-media feature.

## Interface decisions

- Subject: help the owner reclaim Surge's rejected media without losing the decision audit.
- Ground: the source bin, rejection reviews, local files, review time and measured reclaimed bytes.
- Palette: preserve the desk's cool charcoal `#101113`, surface `#1B1D20`, paper text `#F3F0E9`,
  muted text `#A8A6A1`, divider `#343638` and ember `#FF894F`; use existing danger semantics only
  for the final destructive confirmation on the phone.
- Type: existing Bahnschrift headings, Segoe UI explanatory text and utility number treatment.
- Space: 6px within the compact cleanup controls, 14px before the gallery; keep the controls
  subordinate to the video review and publishing actions.
- Shape: existing 5px desktop controls / 8px phone surfaces; tonal separation and no new shadow.
- Motion: no new animation. Pending text, disabled controls and a live result communicate work.
- Signature: the explicit files-and-bytes result with retained decision evidence.

Critique: a generic storage card would add a second dashboard and a prominent guessed space
chart. This stays next to the rejected filter, states the actual cadence/review period and
reports observed deletion results. Confirmation, pending, success, zero-result and error states
are implemented using the existing controls.
