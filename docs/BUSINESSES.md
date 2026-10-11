# Ashvane business workspaces

Ashvane is the parent dashboard. The business switcher beside its name selects the
entire workspace, rather than opening another section of the clipping system.
Four businesses are defined: **Ashvane Surge** (streamer clips),
**Ashvane Hollow** (scary stories), **Resonance** (music), and **Social Studio**
(client social content, starting with QuirkyCMD). New ventures are added
only when the owner asks; future changes apply to the business the owner names.

Startup reuses an available Ollama server or launches the installed local server
when at least one business is enabled. AI settings expose automatic startup,
executable and readiness timeout controls. Remote AI servers remain externally
managed. Only processes launched by Ashvane belong to its shutdown cleanup.
Resonance starts its existing music backend when enabled; native REAPER workers
open as production jobs require them. ffmpeg and ffprobe run on demand rather
than opening unnecessary application windows.

Surge owns its stream sources, capture controls, clip library, clip studio, research,
publishing schedule, growth views and publishing accounts. Hollow owns original
story creation, its story library, narration/rendering, story publishing, story
accounts and story settings. Selecting Stories does not stop the clip business
running in the background.

The businesses share this PC, the Ashvane profile lock, local model installations
and genuine application tools. They do not share destination sign-ins. Clip OAuth
tokens remain in `tokens.json`; Story OAuth tokens use `tokens-stories.json` in the
same profile, with the same encryption mechanism. Story Meta credentials, page
identifiers and Discord webhooks live in `story_accounts`, separately from `accounts`.
No existing clip channel connection is copied into Stories.

Internal business IDs are `clips`, `stories`, `music`, and `social`. Existing clip
and story URLs and saved settings continue working.

YouTube and TikTok can reuse the configured application registration when the
Stories application credential pair is completely blank. This identifies Ashvane
to the provider; it does not connect a user or choose a channel. Each business still
requires its own explicit sign-in. Partially specified custom application credentials
are not mixed with credentials from the other business.

The black-hole transition happens when switching businesses. Navigation inside a
business uses ordinary section changes, and each business remembers its last section.
Warnings appear only when replacing editor work that could be lost. Switching between
retained business panels does not discard their forms. Navigation warnings have a
persisted **Don't show again** choice; deletion and account-security confirmations
remain separate.

On a phone, **Connect on PC** opens account approval in the PC browser so the local
callback can reach Ashvane. The callback-address paste option remains available if
the browser cannot return automatically. Never paste a callback address into a chat
or public document; send it only to the account form in your own Ashvane profile.

## Independent engines

Desktop and phone expose a Run/Stop control per business. Choosing a workspace
never starts its engine. Saved work remains readable while stopped; expensive new
work is gated. Existing Surge/Hollow states default to running for compatibility;
Resonance and Social Studio start disabled. Settings persist across restarts.

Stopping Surge halts intake and queued work. An already submitted upload or native
inference can take time to drain; the UI reports busy rather than implying an
instant rollback. Hollow cancels owned jobs and keeps uncertain publishing states.
Music cancels owned generation/edit/listening jobs and controls only a verified
launcher-owned YuE2 process. A normal REAPER editor is left open. Social stops its
AI drafting jobs; client/draft/asset/calendar editing remains available.

## Resonance

The music workspace connects through authenticated Ashvane routes to the existing
fixed loopback LocalSongLab bridge. Its library, voices, YuE2 weights and audio
stay in the existing installation. The source-only adapter and installation steps
are in `integrations/localsonglab`; no model weights or private settings are bundled.

Create a take, optionally use a completed artist render's retained dry vocal, then
prepare a REAPER project. Original masters stay as reference tracks. Original beat
and melody patterns have editable steps/notes and MIDI sidecars. The producer
interprets a brief, validates a bounded plan, edits a new native revision, requests
a native export, measures it and optionally obtains a tentative audio observation.
Saved revisions are private auditions; no music publishing or automatic release
approval is implemented. Changing tempo alone is not audio time stretching.

The **Create** desk on Windows and phone now owns reference recordings and lyrics
input. Drop/choose supported audio or video, select a saved reference, audition its
preview and write what to borrow. Bounded authenticated uploads spool temporarily
before the local worker validates and analyzes the recording. Saved observations
and creator notes inform generated lyrics and musical direction; original supplied
lyrics are preserved. Basic analysis estimates tempo; optional **Listen & describe**
uses the installed local listening model. Style hints are appended only on request.
References do not directly condition YuE2 audio, clone a voice or guarantee a match.
Import UTF-8 TXT/LRC lyrics on the same desk; replacement requires confirmation.
LocalSongLab remains an internal engine; opening its separate interface is unnecessary
for this workflow. Seven live adapter/reference-worker checks passed on 11 October
2026, including real upload, analysis, retained listing and byte-range audio preview.

After the owner completed REAPER startup setup on 11 October 2026, a native test
successfully changed a test track to -10 dB and pan 0.2, then exported a one-second
48 kHz stereo PCM24 WAV. Read-back confirmed the edits; decoded audio was non-silent
with no clipped samples. Native health now reports verified. This checks editing
and export operation, not musical quality or model listening.
Read `docs/MUSIC_PRODUCTION_RESEARCH.md` for production principles and limits.

## Social Studio

Each client owns its brand guide, public profile links, content drafts, registered
assets and manual publishing calendar. The recovered QuirkyCMD handoff supplies its
actual formats and accounts. Old media is reference material; new productions need
fresh footage. The local AI drafts against the selected client's guide and bounded
context. It cannot execute project code or silently switch the target client.

Public profile links are not sign-ins. Social Studio currently prepares drafts and
a manual calendar; it has no connected publishing credentials or automatic posting.
Nothing is copied from Surge/Hollow accounts. Individual drafts can be deleted;
there is no destructive client-wide cascade. Phone playback caches authenticated
music media locally and clears that cache when the paired identity changes.

## Ideas and creative memory

Hollow offers **Generate** and **Use mine** for its premise. Generate can create an
original premise from the selected genre, treatment and duration with no mandatory
creator text. Suggested ideas remain editable. A given or explicitly selected
premise is preserved. Resonance offers generated lyrics, supplied lyrics and
instrumental takes. Blank generated lyrics and musical direction can be suggested
locally; supplied lyrics are never replaced by that suggestion.

Social Studio proposes ideas against the selected client's documented facts and
saved video-style profile. Each client can save custom styles, upload bounded
references and retry reference analysis later. Video analysis samples actual frames;
it does not establish that every frame or the soundtrack was examined. Audio and PDF
references currently use creator notes rather than claiming full listening/reading.

Feedback, editable production guidance and reference-derived style rules are stored
locally in `creative-memory.json`, scoped to each business account profile or Social
client/style. Feedback on generated ideas and lyrics stays with the profile that
produced them, even if the selected account changes later.
Future prompts retrieve this guidance; model weights are not trained. Pending or
failed analysis is labeled explicitly. Current-trend research and better performance
are not inferred from a saved reference or a positive rating. Private feedback and
evaluation notes are production context and must remain outside public content.

## Account profiles

Surge and Hollow have named account profiles with their own destination credentials
and encrypted token files. Existing connections remain in each business's main
profile and retain the legacy token paths. A new profile may reuse developer app
registration, but it never inherits a signed-in channel, Meta token or webhook.
Profile links are descriptive and do not establish publishing authorization.
Resonance saves artist profiles and public links; music distribution is not connected.
Social Studio continues to use its existing client and video-style profiles.

Clips and stories remain bound to the profile that created them. Legacy queued items
belong to the main profile. Selecting another profile holds the original queue; it
does not send those videos to the new channel. An upload, generation job, or pending
sign-in must finish or be stopped before profiles can change. Pending sign-in can be
canceled without revoking an already connected channel.

The profile account panel uses explicit profile IDs for edits and OAuth actions.
After multiple profiles exist, older account forms require a matching profile
precondition and otherwise direct the user to that panel. Unreadable profile data
is preserved and publication is held rather than resetting destination ownership.

## Business readiness and clip latency

System and Setup report Surge, Hollow, Resonance and Social Studio separately.
An intentionally stopped business does not fail overall readiness. Installed models,
shared GPU activity, native REAPER health and measured export evidence are reported
separately; these checks do not start models or claim production quality.

Surge bounds concurrent audio probes, timestamps detected audio against the segment
that supplied it, and reuses a persisted transcript when recovering work beyond that
stage. Waiting for transcription and performing transcription have separate timing
fields. Stream capture exposes segment-write freshness; this is not a measurement of
delay behind the actual Twitch/Kick broadcast. Live edge, segment streaming and
platform low-latency modes remain configurable. A live comparison is needed before
claiming a measured end-to-end latency reduction.
