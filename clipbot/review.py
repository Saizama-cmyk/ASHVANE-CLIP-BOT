"""Inspect the actual final cut before it can enter the automated posting queue."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

from .assembler import quality_check
from .clipability import BadModelOutput, _extract_json
from .config import Settings
from .editor import probe_media, remap_time
from .models import Candidate
from .vision import Vision, extract_frames, sequence_times

logger = logging.getLogger("clipbot.review")
FINAL_CHECKS = ("opening", "payoff", "ending", "crop", "captions", "honest_hook")


def final_timeline(c: Candidate, settings: Settings) -> dict:
    """Use the renderer's saved edit map, including deliberate pause removal."""
    start = c.verdict.get("trim_start", 0)
    duration = max(0, c.verdict.get("trim_end", start) - start)
    saved = c.verdict.get("render_timeline")
    if saved:
        return saved
    # Historical edit settings are unknown: never reconstruct a cut using today's settings.
    keeps = [(0, duration)]
    return {"source_start": start, "keeps": keeps, "intro_s": 0, "outro_s": 0,
            "expected_duration_s": sum(b - a for a, b in keeps)}


def final_evidence(c: Candidate, timeline: dict) -> tuple[str, dict]:
    start, keeps, intro = timeline["source_start"], timeline["keeps"], timeline["intro_s"]
    spoken = []
    for word in c.words:
        if not any(word.end - start > a and word.start - start < b for a, b in keeps):
            continue
        a = intro + remap_time(word.start - start, keeps)
        b = intro + remap_time(word.end - start, keeps)
        if b > a:
            spoken.append(f"[{a:.2f}-{b:.2f}] {word.text}")
    source = c.verdict.get("viewer_review", {})
    observations = [{**item, "at": round(intro + remap_time(item["at"] - start, keeps), 2)}
                    for item in source.get("evidence", [])
                    if any(a <= item["at"] - start <= b for a, b in keeps)]
    return "\n".join(spoken), {**source, "evidence": observations,
                             "timestamp_basis": "final rendered video seconds"}


@contextmanager
def _review_stage(clip_id: str, stage: str):
    started = perf_counter()
    try:
        yield
    finally:
        logger.info("final review %s for %s took %.2fs", stage, clip_id, perf_counter() - started)


def parse_final_review(text: str, duration: float) -> dict:
    data = _extract_json(text)
    if type(data.get("passed")) is not bool:
        raise BadModelOutput("final review passed must be a boolean")
    checks = data.get("checks")
    if not isinstance(checks, dict) or any(type(checks.get(k)) is not bool for k in FINAL_CHECKS):
        raise BadModelOutput("final review must report every quality check")
    issues, evidence = data.get("issues", []), data.get("evidence", [])
    reason = data.get("reason", "")
    if not isinstance(issues, list) or not isinstance(evidence, list) or not isinstance(reason, str) or not reason.strip():
        raise BadModelOutput("final review needs a reason, issues and evidence")
    observations = []
    for item in evidence:
        try:
            if isinstance(item["at"], bool):
                raise ValueError("timestamp must not be a boolean")
            at, detail = float(item["at"]), item["detail"]
        except (TypeError, ValueError, KeyError) as exc:
            raise BadModelOutput("invalid final-cut observation") from exc
        if not isinstance(detail, str) or not detail.strip() or not math.isfinite(at) or not 0 <= at <= duration:
            raise BadModelOutput("final-cut observation outside the video")
        observations.append({"at": at, "detail": detail.strip()})
    passed = data["passed"] and all(checks[k] for k in FINAL_CHECKS) and not issues and bool(observations)
    missing_evidence = data["passed"] and not observations
    if data["passed"] and not passed:
        defects = [f"{key} check failed" for key in FINAL_CHECKS if not checks[key]]
        if issues:
            defects.append("reviewer reported unresolved issues")
        if missing_evidence:
            defects.append("no timestamped evidence was supplied")
        reason = "Held: " + "; ".join(defects) + ". Reviewer note: " + reason.strip()
    return {"passed": passed, "status": "complete", "reason": reason.strip(),
            "checks": {k: checks[k] for k in FINAL_CHECKS},
            "issues": [str(i) for i in issues], "evidence": observations,
            "needs_repair": bool(missing_evidence and all(checks[k] for k in FINAL_CHECKS) and not issues)}


async def review_final(c: Candidate, settings: Settings, vision: Vision) -> dict:
    """Technical QC and a separate visual review. An unavailable reviewer never silently passes."""
    async def inspect() -> dict:
        path = Path(c.final_path)
        with _review_stage(c.id, "media probe"):
            info = await probe_media(path, settings)
        timeline = final_timeline(c, settings)
        expected = timeline["expected_duration_s"]
        if not c.verdict.get("render_timeline") and abs(info.duration - expected) > 1 / settings.edit.fps:
            return {"passed": False, "status": "unavailable",
                    "reason": "This older export has no saved edit timeline. Re-render it in Studio before final review.",
                    "checks": {}, "issues": ["The original and edited durations cannot be aligned safely."], "evidence": []}
        with _review_stage(c.id, "technical checks"):
            qc = await quality_check(path, expected, settings)
        if not qc.ok:
            return {"passed": False, "status": "complete", "reason": qc.reason,
                    "checks": {"technical": False}, "issues": [qc.reason], "evidence": []}
        if (info.width, info.height) != (settings.edit.width, settings.edit.height):
            return {"passed": False, "status": "complete", "reason": "unexpected output dimensions",
                    "checks": {"technical": False}, "issues": ["Re-render in the configured vertical size."],
                    "evidence": []}
        times = sequence_times(info.duration, settings.review.final_frames,
                               tail_margin_s=settings.review.frame_end_margin_s)
        with _review_stage(c.id, "frame extraction"):
            frames = await extract_frames(path, times, settings)
        images = [base64.b64encode(frame).decode("ascii") for frame in frames]
        spoken, source_review = final_evidence(c, timeline)
        context = {"duration": info.duration, "frame_times": times,
                   "hook": c.post_copy.get("hook", ""),
                   "source_review": source_review, "edit_timeline": timeline,
                   "speech_in_cut": spoken[:settings.ai.transcript_max_chars],
                   "technical": {"audio": "present, above silence threshold",
                                 "black_fraction": qc.black_frac}}
        # Vision.look takes the same GPU lock as raw-clip judgement and original scripts.
        base_prompt = settings.review.final_prompt + "\n\nCUT DATA:\n" + json.dumps(context)
        prompt = base_prompt
        repair_note = ("\nReturn complete JSON matching the instructions above. Preserve your actual "
                       "quality assessment. Evidence must describe supplied frames or speech; "
                       "if no observation supports a pass, reject and explain the gap.")
        for attempt in range(settings.ai.retries + 1):
            try:
                with _review_stage(c.id, f"model attempt {attempt + 1}"):
                    raw = await vision.look(prompt, images)
                    out = parse_final_review(raw, info.duration)
            except BadModelOutput as exc:
                if attempt >= settings.ai.retries:
                    raise
                prompt = base_prompt + "\nValidation failed: " + str(exc) + repair_note
                continue
            if out["needs_repair"] and attempt < settings.ai.retries:
                prompt = base_prompt + "\nValidation failed: no timestamped evidence was supplied." + repair_note
                continue
            break
        if out["needs_repair"]:
            out["status"] = "unavailable"
        out["checks"]["technical"] = True
        out["model"] = settings.ai.vision_model
        return out

    try:
        return await asyncio.wait_for(inspect(), settings.review.final_timeout_s)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        reason = f"Review exceeded its {settings.review.final_timeout_s:g}s deadline. Retry after reducing Final-cut frames or selecting a faster vision model."
        logger.warning("final review deadline exceeded for %s", c.id)
        return {"passed": False, "status": "unavailable", "reason": reason,
                "checks": {}, "issues": ["Review did not finish; upload is held."], "evidence": []}
    except Exception as exc:
        logger.warning("final review unavailable for %s: %s", c.id, exc)
        return {"passed": False, "status": "unavailable", "reason": str(exc) or type(exc).__name__,
                "checks": {}, "issues": ["Review could not finish; retry after fixing the reported issue."],
                "evidence": []}
