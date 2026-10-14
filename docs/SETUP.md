# Set up Ashvane

Start with one business and verify its actual prerequisites. Add more engines and
destinations only when the workstation and account connections are ready.

## Windows installation

Use a published `Ashvane-Setup-<version>.exe` from the
[project releases](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases).
Check its release notes and checksums. The installer is built for Windows and can
offer ffmpeg/Ollama prerequisites; model weights are separate downloads. Existing
data locations are configurable. Preserve a backup before moving profile/media
storage or testing a different build.

Open Setup and System after first launch. Confirm ffmpeg/ffprobe, the configured
Ollama service and installed model inventory, writable data/media folders and
available resources. Windows 10/11 is the desktop target. NVIDIA acceleration helps
Whisper and local inference; no single GPU/RAM recommendation guarantees all four
businesses will run together at useful speed. CPU fallback is slower.

## Run from source

Install Python 3.12, ffmpeg/ffprobe and Ollama. A desktop window also needs WebView2.
From a clone of this repository:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m clipbot --window
```

Console mode uses `python -m clipbot`; `--headless` omits the desktop window. Use
the virtual environment's Python when several versions are installed. The local
dashboard defaults to `http://127.0.0.1:8787`; profile authentication still applies.

```powershell
.venv\Scripts\python -m pytest -q
```

`build.bat` creates the PyInstaller application. `installer\build_installer.bat`
uses Inno Setup for the Windows installer. Source tests, frozen startup checks and
installed-runtime verification are separate release steps.

## Select engines and models

| Feature | Additional prerequisite |
|---|---|
| Surge | Configured Twitch/Kick discovery as used, accessible live sources, Streamlink, Whisper and local vision/judge model |
| Hollow narration | Available Windows voice or separately installed local Kokoro model/voices; compatible speech endpoint when explicitly configured |
| Hollow AI artwork/motion | Existing local ComfyUI plus the specific verified illustration/motion checkpoints; see [visual setup](HOLLOW_LOCAL_VISUALS.md) |
| Resonance | Existing LocalSongLab/YuE2 bridge and compatible native REAPER installation/license; see [integration](../integrations/localsonglab) |
| Social Studio | A selected client, saved brand facts/styles and available local drafting model |
| Core investigations | Configured installed decision model, source/capability health and available resource admission |
| Core source repairs | Engineering model, configured source checkout, trusted Docker evaluation environment and enabled review/promotion policy |

The installed engineering configuration uses Qwen3-Coder 30B A3B; decision/visual
review uses the configured Qwen3-VL model. These roles do not imply identical memory
requirements. Confirm the exact installed names in Settings and inventory. A
missing engineering model may block repairs while decision-only work remains ready.
Check checkpoint-specific terms before use; Ashvane does not redistribute all weights.

## Connect the right destination

Create/select the intended **business account profile before connecting accounts**.
Surge and Hollow have separate tokens and queue ownership. A new profile does not
inherit a signed-in channel, Meta token or Discord webhook. Public profile links
are not sign-ins. Reusing a provider app registration is different from reusing
user authorization.

| Destination | What to configure / inspect |
|---|---|
| Twitch/Kick discovery | Developer application credentials in the matching source settings; verify actual source/chat/capture state |
| YouTube | Google project/Data API and matching OAuth application; explicitly connect the intended channel |
| YouTube watch outcomes | Analytics API enabled and the additional grant available; inspect Growth permission/data status |
| TikTok | Developer application, exact registered redirect and approved permissions; public posting depends on TikTok review/allowed privacy |
| Instagram | Required professional-account permissions and authorized Instagram connection |
| Facebook | The intended Page ID, Page authorization and publishing permissions |
| Discord | A webhook for the intended channel; keep the full URL private |

Provider portals and review rules change. Use the app's current help/status and the
provider's current official documentation. Failed permission/API/connection states
must be resolved; a saved value alone is not evidence of a working publisher.
Resonance has no distribution connection. Social Studio has no automatic posting
connection. Start with a private/manual preview and inspect the finished output.

## Phone connection and release addresses

The PC must remain running. Enable Phone remote, use your own trusted network or
configured Tailscale connection, and sign in using your Ashvane profile. Do not
expose the local dashboard directly to the public internet or share callback URLs.
Read [phone setup](../phone/README.md) for native builds and sideloading.

Existing stable addresses are preserved:

- [iPhone release](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.ipa)
- [Android release](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.apk)
- [Sideload feed](https://raw.githubusercontent.com/Saizama-cmyk/ASHVANE-CLIP-BOT/main/docs/sideload.json)

Check release notes for the packaged source commit. At this snapshot, the new
Interstellar phone source has export/fixture evidence; a new IPA awaits native CI.
An Expo export is not an installable IPA. Physical-device checks remain pending.

## Before leaving work unattended

Check each business's switch and prerequisites, available disk capacity, queue
reasons, source/account/profile identity and finished media. Enable only the
destinations intended for that profile. Review thresholds are configurable; disabling
a gate changes the protection it provides. Consult [current limits](STATUS.md) and
[the technical briefing](ASHVANE_DEEP_DIVE.md) before treating an experiment as a
production capability.

The application is AGPL-3.0. External software, models and source media retain
their own licenses and rights requirements; REAPER is separately licensed.
