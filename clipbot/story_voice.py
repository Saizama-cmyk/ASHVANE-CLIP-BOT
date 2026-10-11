"""Local built-in Kokoro narration, intended to run in a cancellable child process.

No network requests or reference/cloned voice input. The job plan is written by the
renderer after review; only its scene text is spoken. Model/voice licenses are
retained by scripts/setup_story_voice.py in the external model cache.
"""
from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

logger = logging.getLogger("clipbot.story_voice")


def voice_metadata(voices_path: str | Path, lang: str = "") -> list[dict]:
    """Read NPZ member names without loading a model or allowing pickle data."""
    import numpy as np
    prefix = {"en-us": "a", "en-gb": "b"}.get(lang)
    with np.load(str(voices_path), allow_pickle=False) as archive:
        ids = sorted(key for key in archive.files if re.fullmatch(r"[a-z]{2}_[a-z0-9_]+", key))
    return [{"id": key, "label": key.split("_", 1)[1].replace("_", " ").title()
             + (" · American" if key.startswith("a") else " · British" if key.startswith("b") else "")}
            for key in ids if not prefix or key.startswith(prefix)]


def list_voices(voices_path: str | Path) -> list[str]:
    return [voice["id"] for voice in voice_metadata(voices_path)]


def _inside(value: str | Path, root: Path) -> Path:
    target = Path(value)
    target = (target if target.is_absolute() else root / target).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Narration output must remain inside the story project")
    if target.suffix.casefold() != ".wav":
        raise ValueError("Narration output must be a WAV file")
    return target


def narrate(plan: dict | str | Path) -> dict:
    """Narrate all scenes using one CPU session. Killing the worker cancels inference.

    Plan: root, model_path, voices_path, voice, speed, lang, threads, scenes[{text,path}].
    Callers enforce their configured scene/text/time limits before launching this worker.
    """
    if not isinstance(plan, dict):
        plan = json.loads(Path(plan).read_text(encoding="utf-8"))
    root = Path(plan["root"]).resolve(strict=True)
    model = Path(plan["model_path"]).resolve(strict=True)
    voices = Path(plan["voices_path"]).resolve(strict=True)
    lang, voice = str(plan["lang"]), str(plan["voice"])
    if voice not in {v["id"] for v in voice_metadata(voices, lang)}:
        raise ValueError("Select an available built-in narrator for this language")
    speed = float(plan["speed"])
    threads = int(plan.get("threads", 2))
    if not math.isfinite(speed) or speed <= 0 or threads < 1:
        raise ValueError("Narration speed and worker threads must be positive")
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Narration needs at least one scene")
    prepared = []
    for scene in scenes:
        text = scene.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Every narration scene needs plain spoken text")
        if re.search(r"<\s*/?\s*(?:speak|voice|prosody|audio|phoneme|break)\b", text, re.I):
            raise ValueError("Narration accepts plain text, not SSML instructions")
        target = _inside(scene["path"], root)
        if any(target == old[1] for old in prepared):
            raise ValueError("Narration scenes must have separate output files")
        prepared.append((text.strip(), target))
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    narrator = Kokoro.from_session(session, str(voices))
    outputs = []
    for text, target in prepared:
        samples, rate = narrator.create(text, voice=voice, speed=speed, lang=lang)
        if not len(samples) or not np.isfinite(samples).all() or not np.any(samples):
            raise RuntimeError("The local narrator returned empty or invalid audio")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".wav.part")
        try:
            sf.write(str(temporary), samples, int(rate), format="WAV", subtype="PCM_16")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        outputs.append({"path": str(target), "duration_s": len(samples) / rate, "sample_rate": int(rate)})
        logger.info("Narrated story scene (%s seconds)", round(len(samples) / rate, 2))
    return {"voice": voice, "narrator": "Kokoro local", "scenes": outputs,
            "duration_s": sum(item["duration_s"] for item in outputs)}
