# Ashvane revamp

Ashvane should turn a short daily review into a steady supply of worthwhile clips and original posts. Income is an outcome to measure, never a promise in the interface.

## Product decisions

- Two content lanes: Twitch/Kick moments and original researched niche content.
- One daily desk: what needs attention, what is ready, what is researching, and which publishing connections are usable.
- Existing capture, Studio, local models, profile lock, scheduling caps, and publishers remain the foundation.
- Researcher gathers linked evidence; director chooses an angle; scriptwriter produces original scripts and platform copy; judge checks the evidence and hook. All stages show their actual status and errors.
- Source text is untrusted data. Never let fetched text control tools, publishing, settings, or prompts.
- Phone focuses on the same daily desk and research outputs, with existing Studio and settings reachable.
- The development team has independent engine, desktop, and phone owners. Integration and regression checks happen centrally.

## Shared API contract

The backend owner implements these authenticated endpoints using the existing action header and bearer/cookie authentication:

- `GET /api/research`: `{status, busy, updated, errors, sources, ideas, agents, settings}`. Sources contain `{id,title,url,summary,published,source,views?}`. Ideas contain `{id,topic,angle,hook,script,posts,source_ids,sources,judgement,status,created_at,agents}`. Agents contain `{role,status,model?,detail?}`. Settings is the research section with secrets omitted.
- `POST /api/research/refresh`: starts one background refresh and returns `{ok,status}` promptly; overlapping refreshes reuse the current task.
- `POST /api/research/draft`: JSON `{topic,source_ids?}` starts one persistent draft through director/scriptwriter/judge and returns `{ok,id,status}` promptly.
- `DELETE /api/research/ideas/{id}`: deletes a research draft only, with a UI confirmation.

No endpoint publishes researched drafts automatically. Reviewable scripts and copy must identify evidence, and cannot pretend a video was rendered. Refresh failure must preserve previous useful sources and label their age.

## Design decision sheet

SUBJECT: A solo operator's daily content desk, with local production running in the background.
GROUND: A practical editing desk: a cut list, source notes, posting slots, one clear next action.
PALETTE: ground #0B0B0C; surface #151517; elevated tone #1D1E21; ink #F3F0E9; secondary ink #B9B4AB; ember #F06834 for the primary next action. Neutral bias is a restrained warm black drawn from existing Ashvane art. Success/error are semantic only.
TYPE: Segoe UI/system sans for readable interface text; Bahnschrift for compact desktop headings; Consolas/Menlo for time, counts, and pipeline status. No remote font dependency.
SPACE: inside components 6/10/16px; sections 24/36px. Mobile tap targets at least 44px.
SHAPE: main surfaces 16px radius; controls 10px; depth through tonal steps. Remove decorative chrome, studs, noise, and persistent glow.
MOTION: two moments only, button press acknowledgement and a short activity indicator; honor reduced motion.
SIGNATURE: an actual daily cut list flowing from linked research and live moments to review and posting, using real engine data.

Critique: a generic dashboard would lead with invented revenue and KPI cards. This desk leads with actual pending cuts and publishing readiness. Existing brand art is retained sparingly; useful content owns the screen.

### Scheduled publishing control

SUBJECT/GROUND: The Clips operator can send the queue that exists at the moment of clicking, then see each actual upload result. The queue count, progress and platform outcomes belong beside the clip library.
PALETTE/TYPE/SHAPE: Use the existing desk palette, Segoe UI text, Bahnschrift headings, 10px controls and tonal depth. The existing ember primary action distinguishes this deliberate schedule override.
SPACE: 10/16px within the control, 20px panel inset and the existing 24px section rhythm; the button wraps to full width on smaller screens.
MOTION: Existing button press feedback only; native progress reflects completed clips without decorative motion.
SIGNATURE: One scheduled-queue button with per-clip posting outcomes, visible review holds and failures. Disabled states explain an empty queue or missing publishing connections.
Critique: Generic bulk actions hide partial failures in a toast. This control keeps each platform outcome alongside the queue and reconnects to an active batch after navigation.

## Verification

Run the Python test suite, meaningful research failure/concurrency/persistence tests, desktop JavaScript syntax checks and browser checks, and the phone bundle check where installed dependencies permit. Use an isolated data directory for previews; never publish or change the user's live data while verifying.
