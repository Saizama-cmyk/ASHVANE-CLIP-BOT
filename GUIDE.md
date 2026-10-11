# Ashvane v1.0.0: complete guide

A free, local, open-source (AGPL-3.0) Windows app. It watches Twitch and Kick streams, catches hype moments, cuts vertical clips, captions them, uses local AI to judge the clips and write the titles, and posts them automatically. No paid APIs; everything runs on your PC.

## Install
- **Full installer:** `dist\Ashvane-Setup-1.0.0.exe` (about 1 GB, includes everything). Run it, accept the terms, and it offers to install Ollama.
- **Web installer:** a small file that downloads the latest full installer from GitHub Releases. Built by `installer\publish_release.bat` once the GitHub repo exists.
- **Updates:** set Settings → Updates → repo (`owner/name`) and the app checks on start. "Update now" installs silently, keeps your data and restarts.
- **Your data** lives in `%LOCALAPPDATA%\Ashvane`; older ClipBot data migrates automatically.

## First run
1. **Profile.** Unique name (case-insensitive) and a password. Passwords are stored only as salted PBKDF2 hashes (600k rounds), never in plain text. Each profile has its own data folder.
2. **Setup tab.** Shows what is missing (ffmpeg, Ollama, models). Models download themselves based on your GPU.
3. **Sources.** Twitch Client ID + secret (dev.twitch.tv), Kick keys (kick.com → Settings → Developer).
4. **Accounts.** Connect buttons for YouTube and TikTok; Meta tokens for Instagram/Facebook; a webhook URL for Discord. Keys are encrypted on this PC.
5. **Posting.** Turn each platform on, set daily caps, posting hours and templates.
6. **Let it run.** Settings → "Start here" and each section's "How this works" explain every option.

## Pipeline (how a clip is made)
1. **Discovery** picks up to 15 streams per platform: forced streamers, then top categories, then "Fill empty slots" with the biggest remaining ones.
2. **Capture** records each stream into a rolling on-disk buffer (Streamlink), so a moment can be cut after it happens.
3. **Detector** fires on unusual chat speed (z-score), keywords, and jumps in audio loudness — plus a **combined rule**: when two signals are each ~60% of the way to their threshold, that fires too. This is what catches moments no single threshold would.
4. **Cut + transcribe.** ffmpeg cuts at high quality (CRF 14); faster-whisper (large-v3-turbo, CUDA) transcribes. Segments already pruned from the buffer are skipped instead of failing the cut.
5. **Safety.** Slurs and derogatory terms are blocked (hard-R N-word blocked, casual "nigga" allowed): bleeped in audio, masked in titles/captions/tags, and the clip is skipped. Level, bleep sound, extra words and exceptions are in Settings → Safety.
6. **Judge.** A local Ollama model scores 0–10 against an explicit rubric: payoff, emotion, hook, self-contained, clarity. A funny or shocking **line** counts even when the picture is static, so talking-head moments stop being thrown away as "chat only". The judge also picks the cut points and the exact beat (`peak_at`) the edit punches in on.
   - **Second look:** a clip that lands within 1.5 points of the pass mark is judged again with more frames before it is discarded.
   - **Profiles** by VRAM: light (small model, stricter rules), balanced (one `qwen3-vl:8b-instruct` sees, judges and writes — right for 10–24 GB cards like your RTX 5080), strong (big separate judge, 24 GB+).
7. **Copywriter** watches frames (one at the exact spike) plus chat's reaction, then writes title, description, tags, hashtags, first comment and the on-screen hook per platform.
8. **Editor** renders 1080×1920:
   - **Dead-air cut:** long pauses inside the clip are removed and the pieces joined, with captions re-timed to match. Pace is the whole game in short-form.
   - **Stage layout:** the stream fills a tall box (64% of frame height by default, sides cropped) instead of floating as a small letterboxed strip. Facecam layout stacks the webcam over the gameplay.
   - Word-level captions with a pop on the spoken word, hook box, **slow push-in** across the clip and an **eased punch-in** at the judge's peak, loudness normalisation, progress bar, watermark.
9. **Scheduler** posts within caps, windows and gaps. **Analytics** measures views and steers future picks.
10. **Backlog failsafe:** capture pauses when too many clips wait for the AI. Only one AI stage runs at a time.

## App tour
- **Live desk:** stream slots with chat sparklines. Click one to watch it full screen ~6 s behind live.
- **Business switcher:** beside the Ashvane name, choose Surge (streamer clips) or
  Hollow (scary stories). Each has
  its own navigation, publishing connections and settings. Only switching businesses
  triggers the black-hole transition.
- **Stories:** a separate business workspace for original narrated horror. Choose a premise, genre,
  still illustrations or animated shadow theatre, and a target length. A local director,
  writer and independent jury create and review the manuscript; a failed story stays held
  for revision. Accepted stories can render and publish automatically to the destinations
  selected inside Stories. Clip posting switches and templates do not control this queue.
- **Clips:** everything it cut. Clips still working show what stage they are in.
- **Studio:** quick settings plus an Advanced drop-down; six themes (Sterling, Ember, Loud, Clean, Night Shift, Cinema). "Use for all new clips" saves the look.
- **Status card** (click it): system log with events, issues and analytics.
- **Desktop pet:**
  - Runs as a click-through overlay across your whole desktop, so it moves at 60 fps without dragging a window around — that was the old stutter.
  - Because a see-through window gets no mouse messages from Windows, Ashvane tracks the cursor itself: hover opens the card, drag moves the pet, double-click opens the app, and the card's buttons work.
  - Hover card floats above the pet with stats, the hottest stream and graphs.
- **Tray:** closing the window keeps it running. Start with Windows is optional and starts it quietly.
- **Look:** an original dark observatory interface, amber instruments and a central black-hole transition between Stories and the live desk. Reduced-motion preferences use a brief fade. The phone has the same sections and visual language.

## Stories production and publishing

Open Stories, enter an original premise and choose a format. Short projects render vertically;
targets above three minutes render as landscape episodes. Length is a narration estimate:
the finished duration is measured from the actual voice recording. Animated shadow theatre
moves illustrated characters and atmosphere; it does not generate cinematic character footage.
An optional local image server can supply backgrounds.

The default narrator uses installed Windows voices. For natural local narration, run
`.venv\Scripts\python scripts\setup_story_voice.py`, then select **kokoro_local** as the narrator
and a voice in Stories settings. The model download is about 142 MB and subsequent narration
runs on this PC without a paid API. Subtitle timings are estimated within each scene reading.

The manuscript, scene visuals and public title/description can be edited before rendering.
Edits invalidate the previous review and video. Review explanations and internal agent notes
never become narration, captions or published metadata. Stories are labelled original fiction;
YouTube's synthetic-media disclosure is enabled by default.

Stories shows its own connected destination account. Connect or renew accounts under
  Hollow → Accounts before publishing; clip accounts are not reused. Automatic publishing requires a current passing review,
a completed video and a verified account, and observes its own daily cap and gap. Long landscape
episodes use YouTube or Discord. An interrupted or ambiguous upload is held for account checking
instead of being retried automatically and risking a duplicate post.

Research methods, the sampled horror videos and policy sources are documented in
[`docs/HORROR-STORY-RESEARCH.md`](docs/HORROR-STORY-RESEARCH.md). The study is a bounded sample,
not a claim of global trend coverage or guaranteed revenue.

## Settings worth knowing
| Setting | Why |
|---|---|
| Detector → Catch combined signals | The main dial for "am I missing clips?" Lower the strength to catch more. |
| AI → Second look at near-misses | Stops good clips dying on a thin first description. |
| AI → Judge profile | Auto picks by VRAM; force one if you want speed or strictness. |
| Edit → Cut the dead air | Turn off if you want the raw timing. |
| Edit → Stage height / position | How much of the frame the stream fills. |
| Posting → YouTube → 18+ | The upload API cannot apply an age restriction; this setting holds affected clips instead of claiming to restrict them. |
| Pets → Animation speed / walk speed / mouse polling | Feel of the desktop pet. |

## Legal
- LICENSE (AGPL-3.0), NOTICE.md, TERMS.md, PRIVACY.md. Terms are accepted in the installer and again when a profile is created.
- You are responsible for the rights to what you repost; "Blocked streamers" handles takedown requests.
- **Name:** "Ashvane" is a coined word. Web searches on 2026-09-23 found no app, software company or clipping tool using it. That is not a trademark clearance; search USPTO (tmsearch.uspto.gov) before registering or selling merch under it. Not legal advice.

## Build and release (developer)
- **Tests:** `.venv\Scripts\python -m pytest -q`.
- **Dev run:** `run.bat`.
- **Build:** `installer\build_installer.bat` → `dist\Ashvane-Setup-1.0.0.exe`.
- **Publish:** `winget install GitHub.cli`, `gh auth login`, create a public repo, `set CLIPBOT_REPO=owner/name`, `installer\publish_release.bat`.
- **Prompt upgrades:** prompts live in settings.json, so `config.upgrade_prompts` replaces a stored prompt that still matches an older shipped default. Add the old prompt's sha256 to `PROMPT_FIELDS` whenever you change a default, or existing installs keep the old one.

## Still open
- Push to GitHub.
- Instagram/Facebook test posts once Meta tokens are saved.
- First comment auto-posting (needs extra OAuth scopes).
- Brand-kit job to customise your channels (images and copy are in `brandkit\`).
