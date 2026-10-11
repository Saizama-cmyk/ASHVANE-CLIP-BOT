# Ashvane — workspace guide

Free, local, open-source (AGPL-3.0) business dashboard for Windows and phone. Ashvane is
the parent; **Surge** is its streamer-clipping business and **Hollow** is its original
scary-story business. The switcher beside the Ashvane name changes the whole business
workspace. See `docs/BUSINESSES.md` for boundaries and connection storage.

Surge watches Twitch/Kick, detects moments, cuts/transcribes/judges/edits vertical clips
and schedules posts. Hollow creates original narrated stories through local director,
writer and jury roles, renders still illustrations or animated shadow theatre, and
publishes through its own accounts and queue.

## Rules
- Add another business only when the owner explicitly asks. Apply future updates to the
  business the owner names. Do not add unrelated ventures or dashboard features.
- Keep Surge and Hollow destination credentials, queues and navigation separate. Shared
  OAuth application registration is allowed; user/channel tokens must never be inherited.
- $0: no paid APIs/services. Only local AI (Ollama, Whisper). ffmpeg does all editing.
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
story_api.py. Business navigation: dashboard/static/business.js and business.css.
