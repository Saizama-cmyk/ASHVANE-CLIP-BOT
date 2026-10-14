# Ashvane — workspace guide

Free, local, open-source (AGPL-3.0) business dashboard for Windows and phone. Ashvane is
the parent; **Surge** handles streamer clips, **Hollow** handles original scary stories,
**Resonance** handles music, and **Social Studio** handles client social content.
The switcher beside the Ashvane name changes the whole business
workspace. See `docs/BUSINESSES.md` for boundaries and connection storage.

Surge watches Twitch/Kick, detects moments, cuts/transcribes/judges/edits vertical clips
and schedules posts. Hollow creates original narrated stories through local director,
writer and jury roles, renders configured local illustrations/motion, and publishes
through its own accounts and queue. Hollow also compiles ordered approved finished
stories into self-contained collections with measured chapters and original audio.

## Rules
- Add another business only when the owner explicitly asks. Apply future updates to the
  business the owner names. Do not add unrelated ventures or dashboard features.
- Keep all businesses' destination credentials, queues and navigation separate. Shared
  OAuth application registration is allowed; user/channel tokens must never be inherited.
- $0: no paid APIs/services. Use existing local engines. Video editing uses ffmpeg;
  the owner's explicit music requirement overrides this for Resonance: native REAPER
  performs music edits and exports through the LocalSongLab adapter. Never claim a
  native render or listening result unless it actually completed.
- Python 3.12, deps limited to requirements.txt (+ nvidia cuBLAS/cuDNN wheels for GPU Whisper).
- Async everywhere; `logging.getLogger("clipbot.<module>")`; never swallow exceptions; kill every
  child process on shutdown.
- **Everything configurable**: no tunable literals in code (enforced by tests/test_no_hardcoded.py);
  every setting has a label + help and appears in the generated Settings form.
- All design, art (Blender scripts in art/), sounds and names are original. Never copy another
  product's branding, marks or UI. Brand names live in `clipbot/config.py` (COMPANY, PRODUCT).
- Don't call anything done that wasn't run: `python -m pytest -q` must stay green.

## Map
clipbot/: discovery, capture, chat, detector, assembler, transcribe, vision, clipability (judge),
aiplan (judge profiles), copywriter, safety (slur filter + bleep), editor, studio, scheduler,
publishers/, analytics, clip_import, pets, syslog, updater, ollama_setup, desktop (window/tray/pet),
dashboard/ (FastAPI + static UI, pet.html). installer/: Inno Setup full + web installer, release.
Hollow: stories.py, story_render.py, story_art.py, story_voice.py, story_publishing.py,
story_api.py, story_compilation.py. Core maintenance: supervisor*.py, with public
research, bounded private-safe observations, isolated checks and reversible repairs.
Business navigation: dashboard/static/business.js and business.css.
Resonance: music_api.py, music_producer.py, integrations/localsonglab. Social Studio:
social_api.py. Independent engine controls: business_runtime.py. Research evidence:
docs/MUSIC_PRODUCTION_RESEARCH.md and docs/music-production-ledger.json.
