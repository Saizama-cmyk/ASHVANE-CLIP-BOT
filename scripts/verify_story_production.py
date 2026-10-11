"""Real offline narrator/ffmpeg smoke check; never connects or publishes to accounts."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import numpy as np
from PIL import Image, ImageChops, ImageStat, ImageFilter

from clipbot.config import Settings, ffmpeg_exe
from clipbot.story_render import StoryRenderer
from clipbot.util import run_cmd

SCRIPT = ("The station clock stopped at two seventeen. I checked my watch. It was still moving. "
          "Behind the sealed door, someone knocked exactly three times. Then my own voice came through "
          "the speaker, begging me to stay inside. I stepped away. The handle turned from my side.")


def motion_metrics(frames: list[Image.Image]) -> dict:
    """Spatially coherent change, rejecting codec grain and uniform quantization shifts.

    Resize before blur to discard high frequency compression noise. Exclude the
    lower fifth containing changing subtitles; compensate only a uniform RGB
    shift, which cannot produce actual translation or reveal an object.
    """
    raw = sum(ImageStat.Stat(ImageChops.difference(*frames)).mean)
    prepared = [image.resize((180, round(180 * image.height / image.width)), Image.Resampling.LANCZOS)
                .filter(ImageFilter.GaussianBlur(2)) for image in frames]
    arrays = [np.asarray(image, dtype=np.float32) for image in prepared]
    delta = arrays[1] - arrays[0]
    corrected = delta - np.median(delta, axis=(0, 1))
    magnitude = np.abs(corrected)
    # Both measures are reported, rather than claiming every changed pixel is motion.
    return {"raw_rgb_delta": raw, "perceptual_delta": float(magnitude.mean(axis=(0, 1)).sum()),
            "coherent_changed_fraction": float((magnitude.max(axis=2) > 3).mean()),
            "normalization": "180px width, Gaussian sigma2, uniform RGB offset removed, subtitles excluded"}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "story-production-check")
    parser.add_argument("--generate", action="store_true", help="Also ask the real local director/writer/jury for a new original draft")
    parser.add_argument("--neural", action="store_true", help="Verify the installed local neural narrator")
    parser.add_argument("--full-size", action="store_true", help="Use real production dimensions and frame rate")
    parser.add_argument("--reuse-narration", type=Path, help="Reuse a real previously measured narration WAV after validating its adjacent plan")
    parser.add_argument("--atmosphere", action="store_true", help="Also check paired no-subject/wait atmosphere scenes")
    args = parser.parse_args()
    settings = Settings()
    settings.stories.auto_publish = False
    settings.stories.auto_render = False
    if not args.full_size:
        settings.stories.image_width = 360
        settings.stories.image_height = 640
        settings.stories.fps = 12
        settings.stories.caption_font_size = 24
    if args.neural:
        settings.stories.narrator_backend = "kokoro_local"
        settings.stories.voice = "am_adam"
    settings.edit.preset = "ultrafast"
    settings.ai.num_ctx = 16384
    async with httpx.AsyncClient(timeout=settings.stories.timeout_s) as http:
        renderer = StoryRenderer(settings, http, asyncio.Lock())
        await renderer.initialize()
        project = {"id": "0" * 32, "title": "The Clock That Stopped", "topic": "An impossible station clock",
                   "genre": "sci_fi", "format": "animated", "duration_s": 30, "voice": "",
                   "script": SCRIPT, "public_copy": {"youtube": {"title": "The Clock That Stopped", "description": "Original fiction.", "tags": []}},
                   "scenes": [{"id": "1" * 32, "narration": SCRIPT,
                               "visual_prompt": "An empty space station corridor. A sealed door at the end opens to a waiting silhouette.",
                               "visual": {"setting": "station", "subject": "figure", "action": "approach"}}]}
        if args.generate:
            from clipbot.config import AppPaths
            from clipbot.stories import StoryStudio
            models = (await http.get(settings.ai.ollama_url.rstrip("/") + "/api/tags")).json()["models"]
            model = next((m["name"] for m in models if "gemma3:12b" in m["name"]), models[0]["name"])
            settings.stories.model = model
            folder = args.output / "isolated-library"
            paths = AppPaths(folder, folder / "buffer", folder / "work", folder / "clips", folder / "logs", folder / "state.db", folder / "tokens.json", folder / "models")
            studio = StoryStudio(settings, http, paths)
            studio.start()
            created = studio.create("A station clock stops whenever the person outside the sealed door speaks in the narrator's voice. A complete original science-fiction horror story with an earned ending.", "sci_fi", "animated", 30)
            await studio._task
            project = studio.get(created["id"])
            (args.output / "generated-project.json").parent.mkdir(parents=True, exist_ok=True)
            (args.output / "generated-project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
            if not project.get("script") or project["status"] not in ("draft", "needs_review"):
                raise RuntimeError(project.get("error") or "No original story generated")
        if args.reuse_narration:
            source = args.reuse_narration.resolve(strict=True)
            plan = json.loads((source.parent / "narration-plan.json").read_text(encoding="utf-8"))
            if len(project["scenes"]) != 1 or [scene["text"] for scene in plan["scenes"]] != [project["scenes"][0]["narration"]]:
                raise RuntimeError("Cached narration does not match this exact spoken manuscript")
            if args.neural and plan.get("voice") != settings.stories.voice:
                raise RuntimeError("Cached narration uses a different built-in voice")
            async def cached_narration(public, folder, snapshot):
                target = folder / "narration-0.wav"
                if source != target.resolve():
                    shutil.copyfile(source, target)
                (folder / "narration-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
                return [target]
            renderer._narrate = cached_narration
        report = {"capabilities": renderer.capabilities, "generated": args.generate, "outputs": {}}
        report["reused_narration"] = str(args.reuse_narration) if args.reuse_narration else ""
        modes = [("still", "still"), ("animated", "animated")]
        if args.atmosphere:
            modes += [("atmosphere-still", "still"), ("atmosphere-animated", "animated")]
        for output_name, format_name in modes:
            project["format"] = format_name
            project["scenes"][0]["visual"].update(subject="none" if output_name.startswith("atmosphere") else "figure",
                                                  action="wait" if output_name.startswith("atmosphere") else "approach")
            output = args.output / output_name
            result = await renderer(project, output.resolve(), settings)
            duration = result["duration_s"]
            sample_video = output / "scene-0" / "scene.mp4"
            sample_duration, _ = await renderer._duration(sample_video, settings)
            frames = []
            for index, at in enumerate((sample_duration * .18, sample_duration * .82)):
                target = output / f"sample-{index}.png"
                cmd = await run_cmd([ffmpeg_exe(settings), "-v", "error", "-y", "-ss", str(at), "-i", str(sample_video.resolve()), "-frames:v", "1", str(target.resolve())], settings.stories.render_timeout_s)
                if cmd.returncode:
                    raise RuntimeError(cmd.err_text)
                with Image.open(target) as img:
                    frames.append(img.convert("RGB").crop((0, 0, img.width, int(img.height * .8))))
            metrics = motion_metrics(frames)
            volume = await run_cmd([ffmpeg_exe(settings), "-v", "info", "-i", result["video_path"], "-af", "volumedetect", "-vn", "-f", "null", "-"], settings.stories.render_timeout_s)
            if "mean_volume: -inf" in volume.err_text or volume.returncode:
                raise RuntimeError("Narration is silent or undecodable")
            result["motion_check"] = metrics
            report["outputs"][output_name] = result
            print(output_name, duration, "seconds; motion", metrics, flush=True)
            # Save measured proof even if the later paired comparison rejects animation.
            (args.output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        comparisons = []
        for baseline, animated in [("still", "animated")] + ([("atmosphere-still", "atmosphere-animated")] if args.atmosphere else []):
            still_delta = report["outputs"][baseline]["motion_check"]["perceptual_delta"]
            animated_delta = report["outputs"][animated]["motion_check"]["perceptual_delta"]
            passed = animated_delta > max(still_delta * 1.5, still_delta + .1)
            comparisons.append({"baseline": baseline, "animated": animated, "baseline_delta": still_delta,
                                "animated_delta": animated_delta, "passed": passed})
        report["paired_motion_checks"] = comparisons
        (args.output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not all(item["passed"] for item in comparisons):
            raise RuntimeError("Animated scene change does not exceed its paired codec-noise baseline; inspect saved frames")
        print("Verified offline narration, still and actual scene animation; no accounts or publishing used.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
