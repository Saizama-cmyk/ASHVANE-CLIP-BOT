# LocalSongLab integration for Ashvane Resonance

This source-only adapter extends an **existing LocalSongLab installation**. It
does not install YuE2, model weights, Applio, FFmpeg or REAPER. Existing music,
voices, datasets, references and owner-specific remote access remain in that
installation. Ashvane connects to its fixed loopback bridge on port 8099.

## Install

Stop the LocalSongLab bridge when idle. From PowerShell, run:

```powershell
./install.ps1 -SongLabRoot "$env:USERPROFILE/Music/LocalSongLab"
```

The installer checks all patches before changing any source, backs up the affected
source files, and requires Git's `apply` command. It accepts the original baseline
or an already-applied patch; conflicting local edits stop installation. Configure
`app/reaper_config.json` for a different REAPER installation or resource directory.
An empty resource-directory setting uses `%APPDATA%/REAPER`. Existing config is
preserved. Start the existing launcher or use Resonance's Start control afterward.

Run local checks from `LocalSongLab/app` with `python -m unittest discover -q`.
On 11 October 2026 the expanded suite ran **55 tests: 54 passed, 1 skipped**. The
skip is an existing Windows file-symlink privilege check. Source and UI checks
do not establish native render operation or musical quality.

## What the adapter does

- Creates independent REAPER sessions with copied retained masters, optional real
  separated dry vocals/backing, original synthesized instrument tracks and MIDI
  sidecars. Source audio and voices are never overwritten.
- Preserves a converted dry vocal when replacing backing; replacement requires a
  completed artist render with the retained vocal/backing files. A full stereo mix
  cannot supply an isolated dry vocal. Separation can retain audible bleed.
- Validates producer plans, generates trusted Lua from allowlisted operations,
  edits a revision snapshot in a separate native REAPER process, and exports with
  REAPER itself. Normal editor instances are never killed by job cancellation.
- Supports levels, pan, mute, tempo, item position/length/fades, stock FX, EQ and
  generated-instrument pattern replacement. Custom notes provide timing, pitch,
  velocity and duration. Unsupported instructions fail explicitly.
- Measures the actual decoded output channels for duration, peak, RMS and clipped
  samples. These measurements do not approve musical quality.
- Optionally asks the installed managed local MOSS-Music listener about an actual
  completed native revision. Its observation stays tentative and `approved=false`.
- Keeps saved takes/media readable when the music business is stopped. Runtime
  control gates new work, cancels owned jobs and starts/stops only a YuE2 process
  recorded by the launcher, after checking PID, creation time and executable.

Producer/model orchestration lives in Ashvane. A project's `producer_brief` is
retained as notes; presets alone do not interpret that brief. No paid provider is
introduced. Native engine models, stock plugins and legal license setup are the
owner's existing installations.

## Bridge contracts

Every POST uses existing LocalSongLab Host/Origin checks, JSON content type and
`X-Local-Song-Lab: 1`. There are no arbitrary command/path/Lua inputs.

The reference-upload exception uses raw binary content and `X-File-Name` with an
encoded filename. Ashvane bounds, authenticates and spools uploads before forwarding
to this fixed loopback route; the existing reference worker checks containers,
storage limits and preview output. Desktop and phone use Ashvane's `/api/music`
reference list/upload/analyze/cancel/describe/media routes, not the separate studio
interface. TXT/LRC lyrics are imported locally into editable text. Saved reference
observations and creator notes inform local lyric writing and take direction.

- `GET /api/runtime`, `POST /api/runtime {enabled: boolean}`.
- `GET /api/reaper/status`: native health, defaults/options/limits, projects and
  `dry_vocals_available`/`dry_vocal_renders`.
- `GET /api/reaper/projects`, `GET /api/reaper/projects/{project_id}`.
- `POST /api/reaper/projects`: optional `song_id`, `render_id`, `title`, `bpm`,
  `bars`, `beat_style`, `key`, `seed`, `producer_brief`, `replace_backing`, `tracks`.
  Defaults: 90 BPM, 8 bars, boom-bap, C, seed 0, replacement false. Limits:
  40–240 BPM, 1–64 bars, 600 seconds; styles trap/boom-bap/four-on-floor.
- `POST .../{project_id}/validate`: `{summary,actions}`; returns a validated plan.
- `POST .../{project_id}/edit`: `{plan,render:true}`; returns a queued revision.
- `POST .../{project_id}/export {}`, `/open {}`, `/cancel {}`.
- `POST .../{project_id}/revisions/{revision_id}/listen {}`; poll
  `GET /api/reaper/listening/{job_id}`; cancel with `POST .../{job_id}/cancel {}`.
- Completed exports: `/reaper/media/{project_id}/{revision_id}` and corresponding
  `/reaper/download/...`, including byte-range playback.

Plans use `type` and existing exact `track` names. Supported actions:

Native operations use the published [REAPER ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).

```text
set_track: track, volume_db? (-60..12), pan? (-1..1), mute?
set_tempo: bpm (40..240)
arrange_item: track, item_index? (0), start_seconds, length_seconds,
              fade_in_seconds?, fade_out_seconds?
add_stock_fx: track, fx (ReaEQ/ReaComp/ReaVerbate/ReaLimit),
              parameters? [{name: exact native parameter name, value: 0..1}]
eq_band: track, band_type (high_pass/low_shelf/band/notch/high_shelf/low_pass),
         band_index? (0), frequency_hz (20..20000), gain_db? (-24..24), q? (.1..20)
replace_pattern: track (managed matching generated-instrument track),
                 instrument (kick/snare/hat/bass/keys), steps [0..15],
                 velocity? (1..127), note? (24..96)
```

For custom melodies replace `steps` with `notes`: up to 256 events per repeated
bar, each `{step:0..15.999,note:24..96,velocity?:1..127,length_steps?:.125..16}`.
Replacement creates revision-owned audio and MIDI and changes the native item's
source, preserving earlier media. It does not transcribe or isolate YuE2 drums.

Revisions have `id,status,message,plan`, and on a rendered completion
`qc,audio_url,download_url`. States include queued/editing/rendering/completed/
failed/cancelled. Successful native revisions refresh the saved track/FX inventory
and BPM for subsequent planning. Save manual editor changes before exporting.

## Native verification

After the owner finished startup setup on 11 October 2026, REAPER 7.82 completed
a native level/pan edit and export of the one-second verification session.
Read-back confirmed -10 dB and pan 0.2. The resulting stereo PCM24 WAV has a
48 kHz sample rate, non-silent decoded audio and zero clipped samples. The media
route served the verified WAV, and native health reports verified. Earlier failed
startup logs remain retained. No license was purchased, modified or bypassed.

A real completed artist render was copied into a 59.998667-second replacement
session with separate dry vocals/backing and custom generated notes. SHA-256 checks
confirmed its four original audio assets were unchanged. That verifies source
preservation and session preparation. The later short-session test verifies native
editing/export; the full retained-vocal session and model listening remain unverified.
