# Notices

**Ashvane**, © Ashvane. Licensed under the GNU Affero General Public
License v3.0 (see `LICENSE`). You may use, study, change and share it; if you run a modified
version as a network service, you must offer its source code to that service's users.

## Trademarks
"Ashvane" is the name of this project. Twitch, Kick, YouTube, TikTok,
Instagram, Facebook, Discord, NVIDIA, Ollama and all other product names are trademarks of their
respective owners. They are mentioned only to describe what this software works with. This
project is **not affiliated with, endorsed by, or sponsored by** any of them.

## Third-party software bundled in the installer
| Component | License |
|---|---|
| Python 3.12 runtime | PSF License |
| FastAPI, Pydantic, faster-whisper, CTranslate2, ONNX Runtime, pythonnet | MIT |
| uvicorn, httpx, websockets, pywebview | BSD-3-Clause |
| Streamlink | BSD-2-Clause |
| Pillow | MIT-CMU (HPND) |
| pystray | LGPL-3.0 (used unmodified; the full source of this app is public, so it can be relinked) |
| PyInstaller bootloader | GPL-2.0 with the bootloader exception |
| kokoro-onnx | MIT |
| Phonemizer and eSpeak NG (through espeakng-loader) | GPL-3.0 |
| SoundFile / libsndfile | BSD-3-Clause / LGPL-2.1-or-later |
| NVIDIA cuBLAS / cuDNN runtime libraries | NVIDIA Software License (redistributable runtime components) |
| Three.js and the bundled observatory addons/shaders | MIT; [preserved license](clipbot/dashboard/static/vendor/three/0.186.1/LICENSE) |
| Space Grotesk and IBM Plex Sans fonts | SIL Open Font License 1.1; bundled locally with original notices |

The current desktop fonts are
[Space Grotesk](clipbot/dashboard/static/fonts/spacegrotesk-OFL.txt) and
[IBM Plex Sans](clipbot/dashboard/static/fonts/ibmplexsans-OFL.txt).
The phone carries the corresponding font files and notices in
[`phone/assets/fonts`](phone/assets/fonts). The company briefing embeds these
fonts together with their original notices. Original copyright years and the
Plex Reserved Font Name are preserved; these fonts are third-party work.

The [observatory asset provenance manifest](clipbot/dashboard/static/vendor/observatory-assets.json)
records upstream URLs and digests, including installed digests for locally adapted
components. Upstream URLs are provenance, not runtime CDN dependencies. The current
dashboard serves its font and observatory assets locally rather than fetching fonts
from Google Fonts. Original Three.js license attribution remains intact.

## Installed or downloaded separately (not bundled)
ffmpeg (LGPL/GPL, installed via winget), Ollama (MIT), the Qwen models pulled through Ollama
(Apache-2.0 for the documented configured checkpoints), and the Whisper speech model
(MIT, downloaded on first use). Other optional checkpoints/engines retain their own
specific licenses; downloading a model does not make its terms part of Ashvane's AGPL.

Resonance's existing LocalSongLab/YuE2 installation and native REAPER are separate
prerequisites. REAPER is separately licensed; Ashvane does not supply a REAPER license.
Hollow's optional ComfyUI illustration/motion installation and weights are separate;
see [the visual setup documentation](docs/HOLLOW_LOCAL_VISUALS.md) for the specific
checkpoint sources and limits.

The optional local Stories narrator downloads Kokoro model and voice assets separately
(Apache-2.0). `scripts/setup_story_voice.py` verifies the pinned release digests and stores
the model card, licenses and source URLs alongside the assets in
`%LOCALAPPDATA%\Ashvane\models\stories`. Built-in Windows speech is also supported.

## Original work
Ashvane-specific application code, interface designs, original 3D art (logo, splash,
backdrop, pets, icons), public SVG illustrations and sound effects were created for
this project. Third-party components listed above retain their authorship and
licenses. Original 3D art is rendered from the Blender scripts in `art/`, and sounds
are synthesized by `art/sounds.py`. The application remains AGPL-3.0 under [LICENSE](LICENSE).
