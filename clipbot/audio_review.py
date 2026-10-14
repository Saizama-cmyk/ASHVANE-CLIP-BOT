"""Conservative, bounded detection of opening broadband noise added during editing."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import numpy as np

from .config import Settings, ffmpeg_exe
from .util import run_cmd

logger = logging.getLogger("clipbot.audio_review")
AMPLITUDE_TO_DB = 20  # decibel definition for an amplitude ratio


def noise_summary(pcm: bytes, settings: Settings) -> dict:
    cfg = settings.review
    samples = np.frombuffer(pcm, dtype="<f4")
    size = cfg.opening_audio_fft
    if len(samples) < size or not np.isfinite(samples).all():
        raise ValueError("Opening audio has too few valid samples")
    windows = np.lib.stride_tricks.sliding_window_view(samples, size)[::max(1, size // 2)]
    rms = np.sqrt(np.mean(windows.astype(np.float64) ** 2, axis=1))
    level = np.log10(np.maximum(rms, np.finfo(float).tiny)) * AMPLITUDE_TO_DB
    power = np.abs(np.fft.rfft(windows * np.hanning(size), axis=1)) ** 2
    # Ignore DC; epsilon is numerical precision, not a detection threshold.
    power = np.maximum(power[:, 1:], np.finfo(float).tiny)
    flatness = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
    noisy = (flatness >= cfg.opening_audio_flatness) & (level >= cfg.opening_audio_min_db)
    return {"noise_share": float(np.mean(noisy)), "windows": len(windows),
            "mean_dbfs": float(np.mean(level)), "mean_flatness": float(np.mean(flatness))}


async def _decode(path: Path, start: float, duration: float, settings: Settings) -> bytes:
    ffmpeg = await asyncio.to_thread(ffmpeg_exe, settings)
    if not ffmpeg:
        raise ValueError("ffmpeg unavailable for opening audio")
    cfg = settings.review
    result = await run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(start), "-i", str(path), "-t", str(duration), "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", str(cfg.opening_audio_rate), "-f", "f32le", "pipe:1"],
        cfg.opening_audio_timeout_s, grace_s=settings.app.shutdown_timeout_s)
    if result.returncode or not result.stdout:
        raise ValueError("Opening audio could not be decoded")
    return result.stdout


async def check_opening_audio(candidate, timeline: dict, settings: Settings) -> dict:
    """No listening claim: only hold an observed increase over aligned source noise."""
    if not settings.review.opening_audio_check:
        return {"status": "disabled", "passed": None, "reason": "Opening audio comparison disabled"}
    source = Path(candidate.raw_path) if candidate.raw_path else None
    keeps = timeline.get("keeps", [])
    if timeline.get("intro_s", 0) or not keeps or source is None or not await asyncio.to_thread(source.is_file):
        return {"status": "unavailable", "passed": None,
                "reason": "Aligned original opening unavailable, or export starts with an intro"}
    start, end = keeps[0]
    duration = min(settings.review.opening_audio_seconds, end - start)
    try:
        original = await _decode(source, timeline["source_start"] + start, duration, settings)
        rendered = await _decode(Path(candidate.final_path), 0, duration, settings)
        before = await asyncio.to_thread(noise_summary, original, settings)
        after = await asyncio.to_thread(noise_summary, rendered, settings)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("opening audio comparison unavailable: %s", type(exc).__name__)
        return {"status": "unavailable", "passed": None, "reason": type(exc).__name__ + ": opening audio comparison did not finish"}
    added = after["noise_share"] - before["noise_share"]
    hold = (after["noise_share"] >= settings.review.opening_audio_noise_share
            and added >= settings.review.opening_audio_added_share)
    return {"status": "complete", "passed": not hold, "source": before, "export": after,
            "compared_seconds": duration, "reason": "Export opening has sustained added broadband noise; re-render and inspect the audio" if hold
            else "No sustained added broadband noise detected in the compared opening"}
