# Ashvane business workspaces

Ashvane is the parent dashboard. The business switcher beside its name selects the
entire workspace, rather than opening another section of the clipping system.
Only two businesses are defined: **Ashvane Surge** (streamer clips) and
**Ashvane Hollow** (scary stories). New ventures are added
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

Internal business IDs remain `clips` and `stories` so existing URLs and saved settings
continue working. The UI uses Surge and Hollow as the business names.

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
