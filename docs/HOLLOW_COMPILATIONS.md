# Hollow story compilations

Compilations join an ordered selection of existing finished Hollow stories. They
reuse each selected video's own visual treatment and recorded voice. The compiler
does not write new stories, call a narrator or image model, or claim a new content
jury review. The caller must validate source ownership, account profile and current
approval before launching the compilation in Hollow's existing single job slot.

`StoryCompiler(settings).compile(inputs, edition, title=..., opening_s=None,
between_s=None, landscape=True)` is the reusable rendering interface. Inputs are
ordered `{project_id, title, path}` records; paths must already have been resolved
through the owning studio's inside-project validation. The compiler also requires
absolute regular local files and rejects links, junctions, hardlink aliases, empty
inputs and an edition that overlaps its sources. The edition must be fresh and
empty, so retries cannot overwrite an existing successful delivery.

Every source is copied into the edition's `sources/` folder before the first video
encode. Copies are exclusive, streamed in configured chunks and hashed while
copying. A changed source signature/size causes a hold. Cancellation signals the
owned copy worker and drains it before cleanup. Original source files are opened
read-only; deleting or editing an original after a successful snapshot cannot
change the compilation's copies or finished movie. A retry can use the prior
edition's saved copies as inputs to a new edition.

The compiler normalizes output dimensions, frame rate, aspect ratio, audio sample
rate and channel layout. Mixed portrait/landscape footage is fitted with
letterboxing; it is not cropped or regenerated. It uses Hollow's configured image
dimensions, frame rate, H.264 quality and audio bitrate, the existing edit preset
and audio sample rate, and existing subprocess timeout/cleanup helpers. Landscape
swaps Hollow's configured portrait width and height. This preserves the original
visual style and spoken performance, while the normalization necessarily
reencodes video and audio; it is not a bit-exact copy of the original media.

Normalized MOV segments keep H.264 video with a common frame cadence and lossless
stereo PCM audio. MOV avoids the millisecond timestamp quantization observed with
Matroska during the mixed-FPS regression test. Concatenation copies the normalized
video and encodes AAC only once, avoiding separate AAC priming at each story/card.
Shorter streams are padded to a whole output frame, preserving the longer
original audio/video tail. No loudness replacement, voice replacement or new TTS
is introduced. Optional opening and between-story cards contain only the supplied
public titles, using Hollow's configured subtitle face/size on a plain black
background with silent audio.

Chapter boundaries come from probed normalized segment durations. With an opening
card, its chapter begins at zero and the first story begins after it. Without an
opening, the first story begins at zero. A subsequent story's chapter begins at
its title card when enabled; `video_start_s` identifies the actual start of that
story's footage. Chapters are embedded in the MP4, then independently probed back
to verify their count, titles and timestamps. No chapter timestamps are invented
from requested story target lengths. This does not claim eligibility for any
platform's chapter feature or minimum chapter count/duration rules.

Admission is bounded by configured story count, total source bytes and measured
duration including frame-rounded cards. It also checks current destination free
space off the event loop. The admission reserve includes source copies, estimates
for normalized/assembled/remuxed video and calculated stereo PCM storage. This is
an explicit storage estimate, not a fixed CRF bitrate guarantee. Before assembly
and final delivery, further free-space checks use actual intermediate file sizes.
Insufficient space produces an actionable error; the compiler does not silently
move production to another drive. Cancellation or failure removes this fresh
edition's owned snapshots/intermediates/deliveries and preserves originals.

Success requires independently probed final video and audio, configured dimensions,
H.264/AAC codecs, sample rate, frame cadence/frame-count duration agreement, audio
and video duration agreement and the measured chapter metadata. Only then are the
finished `story.mp4`, `narration.m4a` and `compilation.json` retained alongside source
copies. Temporary render segments are removed.

The result follows the existing renderer contract: `video_path`, `audio_path`,
measured `duration_s`, `width`, `height`, `fps`, `visual_mode`, `narrator` and
`warnings`. It additionally returns `chapters`, `source_snapshots` and
`av_metadata`. Snapshot records include original project ID/title, an absolute
edition-owned `file`, byte count, SHA-256 and probed source duration. Chapter
records include `title`, measured `start_s`/`end_s`, `kind`, and story project ID
plus `video_start_s` when applicable. The parent studio owns saved project state,
download URLs, public description formatting, publication approval and the UI.

Focused tests render tiny red/blue stories with different aspect ratios, frame
rates and audio sample rates. They inspect final frame colors and tone frequencies
to establish order and retained audio; verify silent title cards, real chapters,
original hashes and playback after original deletion; cancel an actual ffmpeg
child; drain a copying worker; and exercise count, duration, bytes, disk, path,
title/card and missing-audio negative controls. No production story or media file
was read or changed, and no model or paid service was used by these tests.
