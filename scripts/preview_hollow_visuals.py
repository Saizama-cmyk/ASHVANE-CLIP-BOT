"""Render an isolated three-shot visual comparison using existing measured narration."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbot.config import Settings, ffmpeg_exe
from clipbot.story_render import StoryRenderer
from clipbot.util import run_cmd


def installed_settings():
    settings = Settings()
    settings.businesses.surge_enabled = False
    settings.businesses.hollow_enabled = True
    settings.stories.auto_publish = False
    settings.stories.auto_render = False
    settings.stories.image_backend = "comfyui"
    settings.stories.comfy_autostart = True
    install = Path(os.environ["LOCALAPPDATA"]) / "Comfy-Desktop" / "ComfyUI-Installs" / "Saizama"
    settings.stories.comfy_root = str(install / "ComfyUI")
    settings.stories.comfy_python = str(install / "standalone-env" / "python.exe")
    settings.stories.comfy_models_root = r"E:\ashvane\models\hollow"
    settings.stories.scene_motion = 0.035
    settings.stories.narrator_backend = "kokoro_local"
    settings.stories.voice = "am_adam"
    return settings


async def main():
    settings = installed_settings()
    source = ROOT / "artifacts" / "hollow-quality" / "user-first-scene-after" / "narration-0.wav"
    timing = json.loads(source.with_suffix(".timings.json").read_text())["segments"]
    target = ROOT / "artifacts" / "hollow-quality" / "cinematic-wall-varied-preview"
    target.mkdir(parents=True, exist_ok=True)
    prompts = [
        "Wide vertical cinematic frame inside one small abandoned apartment at night. Muted petrol-blue walls with aged cream paint, oak floorboards, a single warm tungsten table lamp on the left and a dark door on the right. A woman's ordinary hand rests against the cream plaster in foreground, testing its unnatural warmth. Empty believable domestic room, subtle dread, no monster visible, original atmospheric film illustration.",
        "Extreme close-up insert in the same apartment: long thin strips of old cream paint peel and curl away from a petrol-blue plaster wall, revealing a faint rusty red layer beneath, dry material not gore. Shallow depth of field, warm tungsten lamp grazing the texture from the left. The disturbing detail is the peeling material itself. No faces or people in this shot. Original atmospheric film illustration, coherent materials.",
        "Close over-the-shoulder frame in that same apartment at night. An adult woman with dark shoulder-length hair in a charcoal knit sweater leans close to the peeling cream wall, listening, her ear turned toward a narrow seam in the plaster. Warm tungsten light from the left, petrol-blue shadows, oak floor below. The plaster subtly bows outward near her ear but there is no visible monster or human face in the wall. Quiet suspense, specific believable domestic architecture, original cinematic horror illustration.",
    ]
    groups = [(0, 1), (1, 2), (2, len(timing))]
    scenes, audios = [], []
    for index, (first, end) in enumerate(groups):
        start = timing[first]["start"]
        finish = timing[end]["start"] if end < len(timing) else timing[-1]["end"]
        audio = target / f"narration-{index}.wav"
        result = await run_cmd([ffmpeg_exe(settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", str(start), "-i", str(source), "-t", str(finish-start), str(audio)], settings.stories.render_timeout_s)
        if result.returncode:
            raise RuntimeError(result.err_text)
        segments = [{**row, "start": row["start"]-start, "end": row["end"]-start} for row in timing[first:end]]
        audio.with_suffix(".timings.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
        narration = " ".join(row["text"] for row in timing[first:end])
        scenes.append({"narration": narration, "visual_prompt": prompts[index], "visual": {"setting": "room", "subject": "none", "action": "wait"}})
        audios.append(audio)
    project = {"id": "hollow-visual-preview", "title": "The Walls Are Writing My Name", "format": "animated", "duration_s": 60, "scenes": scenes}
    (target / "plan.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    async with httpx.AsyncClient(trust_env=False) as http:
        renderer = StoryRenderer(settings, http, asyncio.Lock())
        async def existing_narration(*args):
            return audios
        renderer._narrate = existing_narration
        renderer.progress = lambda *args: print("Progress", args, flush=True)
        started = time.monotonic()
        try:
            output = await renderer(project, target, settings)
            output["render_elapsed_s"] = round(time.monotonic()-started, 2)
            (target / "result.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
            print(json.dumps(output), flush=True)
        finally:
            await renderer.stop()


if __name__ == "__main__":
    asyncio.run(main())
