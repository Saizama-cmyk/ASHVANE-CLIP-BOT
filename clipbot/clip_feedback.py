"""Private, durable owner corrections, separated from publishing and held-out evaluation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time

from fastapi import APIRouter, HTTPException, Request

from .music_api import read_body

HEX_BASE = 16  # SHA-256 hex encoding


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def correction_record(candidate, profile_id, payload, settings):
    cfg = settings.review
    if set(payload) - {"label", "note", "preview_s"} or payload.get("label") not in {"good", "bad"}:
        raise ValueError("Choose worth posting or not worth posting")
    note = payload.get("note", "")
    at = payload.get("preview_s")
    if not isinstance(note, str) or len(note) > cfg.feedback_note_chars:
        raise ValueError("Correction note exceeds its limit")
    if at is not None and (type(at) not in (int, float) or not math.isfinite(at) or at < 0
                           or at > max(0, candidate.end_wall - candidate.start_wall)):
        raise ValueError("Preview time is outside the captured clip")
    if (candidate.source.get("account_profile_id") or "default") != profile_id:
        raise ValueError("This clip belongs to another account profile")
    target = candidate.event.target
    # Adjacent/overlapping cuts from one source recording-hour share a split.
    group = fingerprint({"source": target.key, "hour": math.floor(candidate.event.t_wall / 3600)})
    verdict = candidate.verdict
    evidence = {"source_key": target.key, "event_wall": candidate.event.t_wall,
                "start_wall": candidate.start_wall, "end_wall": candidate.end_wall,
                "transcript_sha256": fingerprint(candidate.transcript), "visual_sha256": fingerprint(candidate.visual),
                "judge_provenance": verdict.get("_judge") or None,
                "settings_model_at_feedback": settings.ai.model,
                "settings_prompt_sha256_at_feedback": fingerprint([settings.ai.system_prompt, cfg.viewer_prompt]),
                "automatic_passed": verdict.get("passed") if type(verdict.get("passed")) is bool
                                    and verdict.get("category") != "model_error" else None,
                "reason": str(verdict.get("reason", ""))[:cfg.feedback_note_chars],
                "stage": str(candidate.stage)}
    now = time.time()
    return {"candidate_id": candidate.id, "profile_id": profile_id, "source_group": group,
            "split": "evaluation" if int(group, HEX_BASE) % 100 < cfg.feedback_eval_percent else "training",
            "label": payload["label"], "note": note.strip(), "preview_s": at,
            "created_at": now, "updated_at": now, "evidence": evidence}


def correction_summary(records):
    evaluation = [row for row in records if row["split"] == "evaluation"]
    return {"total": len(records), "training": sum(row["split"] == "training" for row in records), "evaluation": len(evaluation),
            "quarantine": sum(row["split"] == "quarantine" for row in records),
            "good": sum(row["label"] == "good" for row in records),
            "bad": sum(row["label"] == "bad" for row in records),
            "wrong_rejections": sum(row["label"] == "good" and row["evidence"]["automatic_passed"] is False for row in records),
            "automatic_tuning": False, "selection": "owner-selected corrections, not a random accuracy sample"}


def evaluate_correction_trial(records, predictions, cfg):
    held = [row for row in records if row["split"] == "evaluation"
            and type(row["evidence"].get("automatic_passed")) is bool]
    if any(sum(row["label"] == label for row in held) < cfg.feedback_min_per_label for label in ("good", "bad")):
        return {"qualified": False, "reason": "Need good and bad held-out examples", "automatic_apply": False}
    if set(predictions) != {row["candidate_id"] for row in held} or any(type(value) is not bool for value in predictions.values()):
        return {"qualified": False, "reason": "Trial must cover the exact held-out set", "automatic_apply": False}
    def errors(decide):
        return {"false_accepts": sum(decide(row) and row["label"] == "bad" for row in held),
                "false_rejections": sum(not decide(row) and row["label"] == "good" for row in held)}
    baseline = errors(lambda row: row["evidence"]["automatic_passed"])
    candidate = errors(lambda row: predictions[row["candidate_id"]])
    gain = (sum(baseline.values()) - sum(candidate.values())) / len(held)
    qualified = gain >= cfg.feedback_min_improvement and all(candidate[key] <= baseline[key] for key in baseline)
    return {"qualified": qualified, "accuracy_gain": gain, "baseline": baseline, "candidate": candidate,
            "evaluation_count": len(held), "automatic_apply": False,
            "reason": "Decision trial only; model-run provenance, source regression and independent review remain required"}


def install_clip_feedback_routes(app, ctx):
    router = APIRouter(prefix="/api/clip-feedback")

    @router.get("/{cid}")
    async def get(cid: str, request: Request):
        profiles = ctx.pipeline.account_profiles
        profiles.require_current("clips", request.headers.get("X-Account-Profile", ""))
        async with profiles.upload("clips"):
            owner = profiles.active_id("clips")
            records = await asyncio.to_thread(ctx.pipeline.store.corrections_for, owner)
            return {"record": next((row for row in records if row["candidate_id"] == cid), None),
                    "summary": correction_summary(records), "note_limit": ctx.settings.review.feedback_note_chars}

    @router.put("/{cid}")
    async def save(cid: str, request: Request):
        if not re.fullmatch(r"[a-f0-9]+", cid):
            raise HTTPException(400, "Invalid clip ID")
        profiles = ctx.pipeline.account_profiles
        profiles.require_current("clips", request.headers.get("X-Account-Profile", ""))
        payload = await read_body(request, ctx.settings.account_profiles.request_max_bytes)
        async with profiles.upload("clips"):
            owner = profiles.active_id("clips")
            candidate = await asyncio.to_thread(ctx.pipeline.store.get_candidate, cid)
            if candidate is None:
                raise HTTPException(404, "Clip evidence is no longer available")
            try:
                record = correction_record(candidate, owner, payload, ctx.settings)
                saved = await asyncio.to_thread(ctx.pipeline.store.save_correction, record, ctx.settings.review.feedback_limit)
                return {"ok": True, "record": saved}
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
    app.include_router(router)
