"""Review one existing final cut with local AI; never publish or change its database row."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from clipbot.config import Settings
from clipbot.models import Candidate, Platform, SpikeEvent, StreamTarget
from clipbot.editor import probe_media
from clipbot.review import review_final
from clipbot.clipability import Clipability
from clipbot.transcribe import Transcriber
from clipbot.vision import Vision


async def main(args):
    if args.video:
        info = await probe_media(Path(args.video), Settings())
        target = StreamTarget(Platform.TWITCH, "review", "Existing clip", "", 0)
        event = SpikeEvent(target, 0, "manual", 0, 0, 0)
        candidate = Candidate(event.id, event, "", 0, info.duration, final_path=args.video,
                              verdict={"trim_start": 0, "trim_end": info.duration}, words=[])
    else:
        with sqlite3.connect(f"file:{Path(args.database).as_posix()}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT json FROM candidates ORDER BY created_at DESC").fetchall()
        candidate = next((Candidate.from_dict(json.loads(row[0])) for row in rows
                          if json.loads(row[0]).get("final_path")
                          and Path(json.loads(row[0])["final_path"]).is_file()), None)
    if candidate is None:
        raise RuntimeError("No existing rendered clip is available")
    settings = Settings()
    settings.review.final_timeout_s = args.timeout
    if args.transcribe:
        if not args.speech_model or not (Path(args.speech_model) / "model.bin").is_file():
            raise ValueError("Supply a cached local speech model folder; validation never downloads weights")
        settings.whisper.model = args.speech_model
        settings.whisper.device = "cpu"
        speech = Transcriber(settings)
        transcript = await speech.transcribe(Path(candidate.final_path))
        candidate.transcript, candidate.words = transcript.text, transcript.words
        speech.unload()
    started = time.monotonic()
    async with httpx.AsyncClient() as http:
        vision = Vision(settings, http)
        raw_verdict = None
        if args.raw:
            folder = Path(args.output).with_suffix("").parent / (Path(args.output).stem + "-frames")
            info = await probe_media(Path(candidate.final_path), settings)
            candidate.raw_path = candidate.final_path
            frames = await vision.prepare(Path(candidate.final_path), info.duration, None, folder)
            candidate.frame_times = frames.times
            images = [base64.b64encode((folder / f"{i}.jpg").read_bytes()).decode("ascii")
                      for i in range(frames.frames)]
            raw_verdict = await Clipability(settings, http).judge(candidate, info.duration,
                                                                 images=images, require_review=True)
            candidate.verdict["viewer_review"] = raw_verdict.get("viewer_review", {})
        verdict = await review_final(candidate, settings, vision)
    output = {"clip_id": candidate.id, "file": candidate.final_path, "final_review": verdict}
    if args.raw:
        output["source_review"] = raw_verdict
    output["speech_words"] = len(candidate.words)
    output["review_elapsed_s"] = round(time.monotonic() - started, 2)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"clip_id": candidate.id, "passed": verdict["passed"],
                      "status": verdict["status"], "reason": verdict["reason"], "report": args.output}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?")
    parser.add_argument("--video")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--raw", action="store_true", help="Also validate the direct-frame source judge")
    parser.add_argument("--transcribe", action="store_true", help="Read speech from the existing file using cached weights")
    parser.add_argument("--speech-model", help="Local cached model folder, required with --transcribe")
    asyncio.run(main(parser.parse_args()))
