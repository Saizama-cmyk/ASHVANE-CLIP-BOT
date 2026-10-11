# Ashvane business workspaces

Ashvane is the parent dashboard. The business switcher beside its name selects the
entire workspace, rather than opening another section of the clipping system.
Four businesses are defined: **Ashvane Surge** (streamer clips),
**Ashvane Hollow** (scary stories), **Resonance** (music), and **Social Studio**
(client social content, starting with QuirkyCMD). New ventures are added
only when the owner asks; future changes apply to the business the owner names.

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
Unsaved story edits still require saving or discarding before leaving their editor.

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

The first native integration test on this PC was blocked at REAPER startup/evaluation
initialization. No successful native edit/export or model listening result was
observed. Finish REAPER's first-run setup on the PC, then test a small revision.
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
