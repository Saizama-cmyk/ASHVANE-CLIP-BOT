"""Offline narration and original illustrated story production, with measured outputs."""
from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from .config import Settings, ffmpeg_exe, ffprobe_exe, is_frozen, resolve_paths
from .story_art import scene_layers
from .util import ERR_SNIPPET, run_cmd

logger = logging.getLogger("clipbot.story_render")

_VOICES_PS = """$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech;
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;
try { @($s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object {
  @{id=$_.VoiceInfo.Name;label=$_.VoiceInfo.Name}
}) | ConvertTo-Json -Compress } finally { $s.Dispose() }"""
_SPEAK_PS = """param([string]$Plan)
$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech
$p=Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $s.Rate=[int]$p.rate
  if ($p.voice) { $s.SelectVoice([string]$p.voice) }
  foreach ($scene in $p.scenes) {
    $s.SetOutputToWaveFile([string]$scene.path)
    $s.Speak([string]$scene.text)
    $s.SetOutputToNull()
  }
} finally { $s.Dispose() }
"""


def local_service_url(value: str) -> str:
    """Only operator-configured literal local addresses; redirects are never followed."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a local HTTP service address without credentials or query parameters")
    hostname = parsed.hostname or ""
    if hostname != "localhost":
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise ValueError("Use localhost or a literal private IP for local AI services") from exc
        if not (ip.is_loopback or ip.is_private) or ip.is_unspecified or ip.is_multicast:
            raise ValueError("Story AI services must run on your local/private network")
    return value.strip().rstrip("/")


def _stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600 * 1000)
    minutes, ms = divmod(ms, 60 * 1000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def write_captions(text: str, duration: float, target: Path, words_per_caption: int,
                   width: int, height: int, font: str, font_size: float) -> None:
    words = text.split()
    groups = [words[i:i + words_per_caption] for i in range(0, len(words), words_per_caption)]
    font = font.replace(",", " ").replace("\n", " ").replace("\r", " ")
    lines = [f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
             "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
             f"Style: Default,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,2,0,2,{round(font_size)},{round(font_size)},{round(font_size * 2)},1\n\n"
             "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"]
    offset = 0
    for index, group in enumerate(groups):
        start = duration * offset / max(1, len(words))
        offset += len(group)
        end = duration * offset / max(1, len(words))
        # SRT markup is not allowed to become subtitle styling or an injection.
        public_text = " ".join(group).replace("<", "‹").replace(">", "›").replace("{", "(").replace("}", ")").replace("\\", "＼")
        def ass_time(value):
            return _stamp(value).replace(",", ".")[:-1]
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{public_text}")
    target.write_text("\n".join(lines), encoding="utf-8")


class StoryRenderer:
    def __init__(self, settings: Settings, http, gpu_lock: asyncio.Lock, models_dir: Path | None = None):
        self.settings, self.http, self.gpu_lock = settings, http, gpu_lock
        self.voices: list[dict] = []
        self.neural_voices: list[dict] = []
        paths = resolve_paths(settings)
        self.models_dir = Path(models_dir) if models_dir else (paths.models or paths.data / "models")
        self.voice_error = ""
        self._refresh_task: asyncio.Task | None = None
        self.progress = None
        self.powershell = shutil.which("powershell.exe") if os.name == "nt" else None

    def apply(self, settings: Settings) -> None:
        old = self.settings.stories
        self.settings = settings
        new = settings.stories
        if not settings.businesses.hollow_enabled:
            return
        if (old.narrator_backend, old.kokoro_model_path, old.kokoro_voices_path, old.kokoro_lang) != (new.narrator_backend, new.kokoro_model_path, new.kokoro_voices_path, new.kokoro_lang):
            if self._refresh_task and not self._refresh_task.done():
                self._refresh_task.cancel()
            self._refresh_task = asyncio.create_task(self.initialize(), name="story-voices-refresh")

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
            self._refresh_task = None

    def _kokoro_paths(self, cfg):
        return (Path(cfg.kokoro_model_path) if cfg.kokoro_model_path else self.models_dir / "stories" / "kokoro.onnx",
                Path(cfg.kokoro_voices_path) if cfg.kokoro_voices_path else self.models_dir / "stories" / "voices.bin")

    async def initialize(self) -> None:
        if self.settings.stories.narrator_backend == "kokoro_local":
            model, voices = self._kokoro_paths(self.settings.stories)
            try:
                if not model.is_file() or not voices.is_file():
                    raise ValueError("Install the local Kokoro model and voice bank with scripts/setup_story_voice.py")
                from .story_voice import voice_metadata
                self.neural_voices = await asyncio.to_thread(voice_metadata, voices, self.settings.stories.kokoro_lang)
                self.voice_error = ""
            except (ValueError, OSError, ImportError) as exc:
                self.neural_voices = []
                self.voice_error = f"Local neural narrator unavailable: {exc}"
                logger.warning(self.voice_error)
            return
        if not self.powershell:
            self.voice_error = "Windows offline narration requires Windows, or configure a local speech server in Settings → Stories"
            return
        try:
            result = await run_cmd([self.powershell, "-NoProfile", "-NonInteractive", "-Command", _VOICES_PS],
                                   self.settings.stories.timeout_s, grace_s=self.settings.app.shutdown_timeout_s)
            if result.returncode:
                raise ValueError(result.err_text[-ERR_SNIPPET:])
            rows = json.loads(result.out_text.lstrip("\ufeff"))
            self.voices = rows if isinstance(rows, list) else [rows]
            self.voices = [row for row in self.voices if isinstance(row, dict) and row.get("id")]
        except (ValueError, OSError, RuntimeError) as exc:
            self.voice_error = f"Offline voice discovery failed: {exc}"
            logger.warning(self.voice_error)

    @property
    def capabilities(self) -> dict:
        cfg = self.settings.stories
        reasons = []
        narrator = bool(self.voices) if cfg.narrator_backend == "windows" else (bool(self.neural_voices) if cfg.narrator_backend == "kokoro_local" else bool(cfg.speech_url))
        if not narrator:
            reasons.append(self.voice_error or "Choose an installed narrator in Settings → Stories")
        video = bool(ffmpeg_exe(self.settings) and ffprobe_exe(self.settings))
        if not video:
            reasons.append("ffmpeg and ffprobe are required to produce story videos")
        voices = self.voices if cfg.narrator_backend == "windows" else (self.neural_voices if cfg.narrator_backend == "kokoro_local" else [{"id": cfg.voice, "label": cfg.voice or "Local speech server default"}])
        return {"narrator_available": narrator, "still_available": video, "animated_available": video,
                "render_available": narrator and video, "voices": voices, "reasons": reasons,
                "narrator_label": "Windows offline narration" if cfg.narrator_backend == "windows" else ("Kokoro local neural narration" if cfg.narrator_backend == "kokoro_local" else "Local speech server (connection checked on render)"),
                "visual_provider": {"id": "local_image" if cfg.image_provider_url else "shadow_theatre",
                                    "label": "Local AI illustrations + animated shadow layers" if cfg.image_provider_url else "Original illustrated shadow theatre",
                                    "available": video}}

    async def _command(self, args: list[str], settings: Settings, cwd: Path | None = None):
        result = await run_cmd(args, settings.stories.render_timeout_s, str(cwd) if cwd else None,
                               grace_s=settings.app.shutdown_timeout_s)
        if result.returncode:
            raise ValueError(f"Story production failed: {result.err_text[-ERR_SNIPPET:]}")
        return result

    async def _duration(self, path: Path, settings: Settings) -> tuple[float, dict]:
        result = await self._command([ffprobe_exe(settings), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], settings)
        data = json.loads(result.out_text)
        duration = float(data["format"]["duration"])
        if duration <= 0:
            raise ValueError("Narration or rendered video has no playable duration")
        return duration, data

    async def _narrate(self, project: dict, folder: Path, settings: Settings) -> list[Path]:
        cfg = settings.stories
        paths = [folder / f"narration-{index}.wav" for index in range(len(project["scenes"]))]
        voice = project.get("voice") or cfg.voice
        if cfg.narrator_backend == "windows":
            if not self.powershell or not self.voices:
                raise ValueError("No Windows offline voice is available; configure a local speech server")
            if voice and voice not in {row["id"] for row in self.voices}:
                raise ValueError("The selected Windows voice is no longer installed")
            script = folder / "speak.ps1"
            script.write_text(_SPEAK_PS, encoding="utf-8-sig")
            plan = folder / "narration-plan.json"
            plan.write_text(json.dumps({"rate": cfg.speech_rate, "voice": voice,
                                      "scenes": [{"path": str(path), "text": scene["narration"]} for path, scene in zip(paths, project["scenes"])]}), encoding="utf-8")
            await self._command([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(script), "-Plan", str(plan)], settings)
        elif cfg.narrator_backend == "kokoro_local":
            model, voices = self._kokoro_paths(cfg)
            if not self.neural_voices:
                raise ValueError("The local neural narrator has no installed voices")
            voice = voice or self.neural_voices[0]["id"]
            plan = folder / "narration-plan.json"
            plan.write_text(json.dumps({"model_path": str(model.resolve()), "voices_path": str(voices.resolve()),
                                      "root": str(folder.resolve()), "voice": voice, "speed": cfg.kokoro_speed, "lang": cfg.kokoro_lang, "threads": cfg.kokoro_threads,
                                      "scenes": [{"path": str(path.resolve()), "text": scene["narration"]} for path, scene in zip(paths, project["scenes"])]}), encoding="utf-8")
            args = [sys.executable] + ([] if is_frozen() else ["-m", "clipbot"]) + ["--story-voice", str(plan)]
            await self._command(args, settings)
        else:
            endpoint = local_service_url(cfg.speech_url) + "/v1/audio/speech"
            for scene, path in zip(project["scenes"], paths):
                audio = await self._local_request(endpoint, {"model": cfg.speech_model, "voice": voice,
                                                  "input": scene["narration"], "response_format": "wav"}, settings)
                path.write_bytes(audio)
        return paths

    async def _local_request(self, endpoint: str, payload: dict, settings: Settings) -> bytes:
        output = bytearray()
        async with self.http.stream("POST", endpoint, json=payload, timeout=settings.stories.timeout_s,
                                    follow_redirects=False) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                output.extend(chunk)
                if len(output) > settings.stories.generated_media_max_mb * 1024 * 1024:
                    raise ValueError("Local generated media exceeds the configured response limit")
        return bytes(output)

    async def _illustrate(self, scene: dict, folder: Path, width: int, height: int, settings: Settings) -> dict:
        layers = await asyncio.to_thread(scene_layers, scene, folder, width, height)
        cfg = settings.stories
        if cfg.image_provider_url:
            async with self.gpu_lock:
                raw_response = await self._local_request(local_service_url(cfg.image_provider_url) + "/sdapi/v1/txt2img",
                    {"prompt": scene["visual_prompt"], "width": width, "height": height,
                     "steps": cfg.image_steps, "batch_size": 1}, settings)
            images = json.loads(raw_response).get("images", [])
            if not images or not isinstance(images[0], str):
                raise ValueError("Local illustration server returned no image")
            def save_image():
                raw = base64.b64decode(images[0].split(",")[-1], validate=True)
                with Image.open(io.BytesIO(raw)) as image:
                    image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS).save(layers["background"])
            await asyncio.to_thread(save_image)
        return layers

    async def __call__(self, project: dict, folder: Path, settings: Settings) -> dict:
        cfg = settings.stories
        ffmpeg = ffmpeg_exe(settings)
        if not ffmpeg or not ffprobe_exe(settings):
            raise ValueError("Install ffmpeg and ffprobe before rendering stories")
        landscape = project["duration_s"] > cfg.episode_threshold_s
        width, height = (cfg.image_height, cfg.image_width) if landscape else (cfg.image_width, cfg.image_height)
        folder.mkdir(parents=True, exist_ok=True)
        if self.progress:
            self.progress(project["id"], "narrating", 0)
        audio_paths = await self._narrate(project, folder, settings)
        parts = []
        for index, (scene, audio) in enumerate(zip(project["scenes"], audio_paths)):
            if self.progress:
                self.progress(project["id"], "rendering", index / len(audio_paths))
            spoken_duration, _ = await self._duration(audio, settings)
            duration = spoken_duration + cfg.narration_gap_s
            layers = await self._illustrate(scene, folder / f"scene-{index}", width, height, settings)
            scene_folder = layers["background"].parent
            font_size = cfg.caption_font_size / (2 if landscape else 1)
            write_captions(scene["narration"], spoken_duration, scene_folder / "narration.ass", cfg.caption_words,
                           width, height, cfg.caption_font, font_size)
            animated = project["format"] == "animated"
            action = (scene.get("visual") or {}).get("action", "approach")
            # Character and fog move independently of the camera. Stills remain still.
            center = "(W-w)/2"
            motion = f"{width * cfg.scene_motion:.3f}"
            x = f"{center}+{motion}*(1-t/{duration:.6f})" if animated else center
            if action == "wait":
                x = center
            y = "H-h-H/10"
            if animated and action == "follow":
                x = f"{center}+{motion}*sin(t*2)"
            character = "[1:v]format=rgba[character];"
            if animated and action in ("reveal", "vanish"):
                direction = "in" if action == "reveal" else "out"
                start = duration / 2 if action == "vanish" else 0
                character = f"[1:v]format=rgba,fade=t={direction}:st={start:.6f}:d={duration / 2:.6f}:alpha=1[character];"
            fog_x = f"-{motion}*t/{duration:.6f}" if animated else "0"
            filters = character + f"[0:v][character]overlay=x='{x}':y='{y}':eval=frame[stage];[stage][2:v]overlay=x='{fog_x}':y=0:eval=frame"
            if cfg.captions:
                filters += ",ass=narration.ass"
            filters += "[video]"
            out = scene_folder / "scene.mp4"
            args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            for name in ("background", "figure", "fog"):
                args += ["-loop", "1", "-framerate", str(cfg.fps), "-i", str(layers[name])]
            args += ["-i", str(audio), "-filter_complex", filters, "-map", "[video]", "-map", "3:a:0",
                     "-af", f"apad=pad_dur={cfg.narration_gap_s}", "-t", str(duration),
                     "-c:v", "libx264", "-preset", settings.edit.preset, "-crf", str(cfg.crf),
                     "-pix_fmt", "yuv420p", "-r", str(cfg.fps), "-c:a", "aac", "-b:a", cfg.audio_bitrate,
                     "-movflags", "+faststart", str(out)]
            await self._command(args, settings, scene_folder)
            parts.append(out)
        concat = folder / "scenes.txt"
        # Filenames are generated locally; no user paths are interpolated into concat syntax.
        concat.write_text("\n".join(f"file 'scene-{index}/scene.mp4'" for index in range(len(parts))), encoding="utf-8")
        video = folder / "story.mp4"
        await self._command([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "concat", "-safe", "1", "-i", str(concat),
                             "-c", "copy", "-movflags", "+faststart", str(video)], settings)
        narration = folder / "narration.m4a"
        await self._command([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(video), "-vn", "-c:a", "copy", str(narration)], settings)
        duration, probe = await self._duration(video, settings)
        streams = probe.get("streams", [])
        if not any(s.get("codec_type") == "audio" for s in streams) or not any(s.get("codec_type") == "video" for s in streams):
            raise ValueError("Finished story must contain both video and narration")
        return {"video_path": str(video), "audio_path": str(narration), "duration_s": duration,
                "width": width, "height": height, "fps": cfg.fps,
                "visual_mode": "Animated shadow theatre" if project["format"] == "animated" else "Illustrated stills",
                "narrator": project.get("voice") or cfg.voice or (self.neural_voices[0]["id"] if cfg.narrator_backend == "kokoro_local" and self.neural_voices else cfg.narrator_backend),
                "warnings": ["Subtitle timing is estimated within each measured scene reading."] if cfg.captions else []}
