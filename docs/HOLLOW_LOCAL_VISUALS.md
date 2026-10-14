# Hollow local illustration upgrade

Hollow can render original scene images with **FLUX.2 Klein 4B FP8** through a
dedicated local ComfyUI process. Supplied scene artwork remains supported. The prior
procedural renderer and an existing AUTOMATIC1111 endpoint remain explicit choices.
An unavailable AI engine fails the job rather than replacing it with generic drawings.

## Direction

The [six-video visual study](HOLLOW-VISUAL-BENCHMARK-20261011.md) supports concrete
locations, recurring appearances/props, purposeful viewpoints, and a legible reveal
order. The AI writer now describes a single visible instant per scene. Compatibility
stage tags no longer restrict an AI-illustrated story to five drawn environments.
Same-location shots can optionally reference the previous generated image. This is
off by default: the real GPU test repeated the wide framing when asked for an insert.
Shared textual art direction is used by default so new shots can change composition.

Still mode holds original illustrations. Animated mode can use **Wan 2.2 TI2V 5B**
to generate actual scene movement from each illustration, or explicit camera-only
motion. Labels and output metadata distinguish these. Neither promises lip sync or
actor-level performance. Narration and publishing are separate from this visual
upgrade; comparisons reuse existing measured voice takes.

## Local installation

`scripts/setup_story_visuals.py --models E:\ashvane\models\hollow` downloads the
three weights from their primary repositories, checks their byte sizes and SHA-256
digests, and records a manifest outside the app. Models are not bundled into the exe.
The setup script supports verified HTTP byte ranges and interrupted downloads.
Use `--mode motion` for the separately verified Wan diffusion model, UMT5 encoder,
and video VAE. The native core-node workflow follows the
[ComfyUI Wan guide](https://docs.comfy.org/tutorials/video/wan/wan2_2), with model
architecture/license documented by [Wan](https://github.com/Wan-Video/Wan2.2).
The guide's 8 GB offloading claim is a single vendor-origin statement, not a local
speed or quality measurement.

Configure Stories → image engine as ComfyUI, enable managed startup, and supply the
existing ComfyUI folder, its Python executable, and the model folder. All paths,
sampling parameters, deadlines, polling, image limits and shared art direction are
settings. The current PC uses its existing Saizama ComfyUI installation and port 8190.

The owned child binds loopback, disables browser launch, custom nodes and cloud API
nodes, and stores runtime files on E:. An explicit database URL prevents ComfyUI from
migrating its existing Desktop database. A first test exposed that automatic migration;
the original database was restored from the backup it created.

The installed ComfyUI environment was incomplete: torch/torchgen and torchsde were
missing, and comfy-aimdo/comfy-kitchen did not match the checked-out ComfyUI requirements.
Torch files were restored from its existing cached standalone installer, then its
own requirements were synchronized with its existing Python environment. Ashvane's
Python environment and dependency list were not expanded for diffusion inference.

## Resource and failure handling

Hollow writing roles release their Ollama model before illustration when enabled in
settings. Rendering shares the existing GPU lock. The owned image service stops at
the end of a render, including failures/cancellation, and when Hollow stops. Another
operator-managed ComfyUI process is never killed or globally unloaded.

Requests, deadlines, metadata, images and decoded pixels are bounded. Reference uploads
use generated names, and output references must belong to the submitted UUID. Cancellation
deletes/interrupts that UUID only. Full-frame artwork is aspect-cropped and rendered
without the procedural person/fog overlays.

Animation illustrates all scenes first, then releases the owned image process before
loading the video model. Generated segments use Wan's spatial/temporal strides, have
configurable frame/resolution/work limits, and are checked with ffprobe and decoded by
ffmpeg before delivery. Longer narration uses new motion segments conditioned on the
last frame, not loops, a stretched short take, or a frozen final frame. Native motion
is delivered with the measured narration and captions, without the additional still
camera effect. Both successful and failed renders stop the owned local engine.

## Primary model evidence and limits

- [BFL model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8)
  identifies the 4B checkpoint as Apache-2.0 and documents reference editing. These are
  single-origin developer statements; the choice is specifically 4B, not the differently
  licensed 9B checkpoint.
- [ComfyUI guide](https://docs.comfy.org/tutorials/flux/flux-2-klein) supplies the
  core-node workflow and model components. Its hardware/speed figures are vendor
  measurements on other hardware, not a promise for this PC.
- The local weights manifest records the actual installed files and digests. The
  comparison script and result live under `artifacts/hollow-quality/cinematic-wall-varied-preview`.

The benchmark uses sampled frames and available captions, not continuous listening.
No controlled retention test, revenue prediction or guarantee of views was established.
Image quality, identity consistency and exact scene agreement still need review in
the finished story. The actual three-shot illustration test produced a wide frame,
paint insert and listening subject (19.30 seconds, 720x1280, 24 fps). Cold render elapsed
206 seconds in the first test and 539 seconds during concurrent packaging/downloads;
warm image prompts took about 4–6 seconds. These are observations, not a throughput
guarantee. The isolated animation check is `scripts/preview_hollow_animation.py` and
its result is recorded separately under `artifacts/hollow-quality/wan-paint-preview`.

The actual native animation check completed on 12 October: 4.194 seconds delivered at
720x1280/24 fps, with narration and measured sentence captions. The first attempt lost
focus near its end. A second check with explicit fixed-focus/locked-camera direction
kept the peeling-wall composition sharper across four inspected cue frames. Movement
is subtle; this is not evidence of convincing character acting. That preset is installed
in the owner's Stories settings. The second GPU render took 212.33 seconds including
engine startup; its video is `artifacts/hollow-quality/wan-paint-focused-preview/story.mp4`.
The Wan weights are verified on the internal SSD at
`%LOCALAPPDATA%/Ashvane/models/hollow-motion`; image weights remain on E:.

The rebuilt Windows executable passed the isolated authenticated dashboard/API smoke
test including its frozen Kokoro narration worker. Source regression suite: 733 passed,
1 skipped. The native prompt uses canonical UUIDs required by this ComfyUI version;
workflow validation failures now surface their bounded local diagnostics.
