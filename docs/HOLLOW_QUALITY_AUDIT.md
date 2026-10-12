# Hollow quality audit — 2026-10-11

The complaint is supported by the renderer and the inspected visual evidence. The current default visual engine draws five kinds of environment and a small set of paper silhouettes. It cannot depict a wall breathing, paint peeling, a hand touching plaster, facial acting, or most specific story events. Moving these layers is not generative character animation.

## Evidence and limits

The active user library at `%LOCALAPPDATA%/Ashvane/stories.json` contains three interrupted projects and no completed video output. The project folders contain real first-scene narration WAVs, but no surviving MP4 export. No custom data-root or scene-asset path was present in these projects. Therefore this audit does not pretend to have watched a completed user episode.

An isolated preview was recreated from the user's saved first scene of **The Walls Are Writing My Name** (project `4f5cffcd59874a89a45f1e6f075d8d9f`) and its actual existing narration WAV. The source project was not edited or published. Evidence: `artifacts/hollow-quality/user-first-scene-before/evidence.json` and `story.mp4`.

The `/watch` local engine sampled the full 16.65-second preview at 0, 4, 8 and 13 seconds. Every selected frame was inspected. The scene shows a generic dark room and a stationary cut-paper figure. It never shows the narrated warm wall, peeling paint or a woman touching plaster. Captions cross sentence boundaries: at about 4 seconds, “— like skin. Paint peels in slow”; at about 13 seconds, “memory. It’s coming / from the plaster, and”. Local frames establish these visual problems; they do not establish voice acting quality. The saved manuscript, not speech recognition, supplies the text evidence here.

A previously rendered generated test episode (`artifacts/story-generated-ending-check/animated/story.mp4`, 38.7 seconds) was also sampled at 0, 5, 10, 15, 19, 24, 29 and 34 seconds. Every selected frame was inspected. The corridor composition repeats, the figure mostly slides, and the later reveal is not visualized. A caption at about 29 seconds shows literal Markdown `*correct*`.

The user's actual narrator configuration is already **Kokoro local**, built-in voice `am_adam`, speed 0.92; both model and voice bank are installed. This is not a Windows fallback problem. The 46-word first scene lasts 16.65 seconds including the scene gap: approximately 166 words/minute, despite the separate writing estimate of 130 words/minute. The writing estimate does not control actual spoken speed. A singing model such as YuE2 is not a drop-in spoken dramatic narrator.

The saved manuscript also contains production directions such as “The camera pulls back” and “The final shot reveals”, plus repeated ending material. These are writing and quality-gate defects, separate from rendering. A text-only jury approval is not evidence that the finished video is engaging.

## Contained repairs

- Local Kokoro now synthesizes sentence-sized readings, records their actual start/end offsets beside each WAV, and inserts configurable sentence breaths. No time-stretching is used.
- Captions follow measured sentence boundaries, respect punctuation, and remove speech-formatting delimiters. Word timing within each sentence remains estimated and is labeled accordingly.
- Narration is loudness-normalized with configurable targets and encoded at the configured output sample rate.
- Existing validated project artwork is now honored by the renderer; previously the render ignored `asset_path`.
- Full supplied/generated illustrations no longer receive a generic, potentially contradictory paper person pasted over them.
- Animated scenes receive a restrained camera push even when the subject waits or is absent. This improves continuity but does not add character acting.
- Obvious sentence-start film directions are rejected for bounded writer repair before narration; this also protects older saved drafts at render time. Legitimate story references to security cameras and gunshots remain allowed.
- Output warnings explicitly state the visual engine's limits. A successful ffmpeg encode is not a cinematic-quality certification.

## Social Studio scope

`clipbot/social_api.py` currently implements client/style profiles, original script/caption drafts, idea generation, registered reference media and partial reference analysis. It does not itself render or publish finished videos. There is no basis to claim that its finished production quality has passed, or that the Hollow animation problem has already occurred there. Evaluate a real finished social video once one is supplied or created through an actual production workflow.

## Validation

Focused story, narration, caption, creator-art containment and configurable-setting checks passed (116 tests at the time of this audit). The isolated improved first-scene preview and measured voice evidence are written under `artifacts/hollow-quality/user-first-scene-after`. Neither preview connects to a social account or changes the saved user project.

The improved preview completed with real installed Kokoro inference and ffmpeg: 18.479 seconds, H.264 video and 48 kHz AAC narration. All six `/watch` frames at 0, 3, 6, 9, 12 and 15 seconds were inspected. Captions now keep punctuation-based phrases such as “— like skin.”, “curling like dried blood.” and “It’s not wind.” separate; the background camera push is visible. Actual sentence offsets are saved in `narration-0.timings.json`. Effective pacing changed from approximately 166 to 149 words/minute. An FFmpeg loudness measurement changed from -22.54 LUFS to -17.41 LUFS; the configured -16 LUFS is a target, not a guarantee in a single pass with peak limiting. This is a concrete repair, not evidence of natural acting or high-end animation. No listening-capable model was used; voice acting and pronunciation remain unverified by this audit.

## Remaining work

Better visuals need an actual installed illustration/animation engine or creator-supplied original scene artwork. Better dramatic delivery needs listening-based voice selection and pronunciation/prosody review. The current repairs do not establish human acting, lip sync, genuinely animated scene action or a prediction of viral performance.
