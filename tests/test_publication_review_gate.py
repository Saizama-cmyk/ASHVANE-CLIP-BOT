"""The final review gate must protect actual uploads, including old queued clips."""
import asyncio

from clipbot.config import Settings, resolve_paths
from clipbot.db import Store
from clipbot.pipeline import Pipeline
from clipbot.scheduler import Scheduler
from tests.test_scheduler import FakePub, cand, enabled, pubs


def test_old_scheduled_clip_cannot_bypass_upload_review(tmp_path):
    settings = enabled()
    store = Store(tmp_path / "test.db")
    clip = cand(tmp_path)
    store.upsert_candidate(clip)
    pub = FakePub(settings)
    scheduler = Scheduler(settings, store, pubs(settings, pub))
    seen = []
    async def reject(candidate):
        seen.append(candidate.id)
        candidate.error = "Final cut has no payoff"
        return False
    scheduler.quality_guard = reject
    try:
        result = asyncio.run(scheduler.publish_now(clip.id, ["discord"]))
        assert seen == [clip.id] and not result["discord"]["ok"]
        assert pub.calls == [] and not store.posts_for_candidate(clip.id)
        assert "no payoff" in result["discord"]["error"]
    finally:
        store.close()


def test_upload_holds_the_same_media_lock_as_studio(tmp_path):
    settings = enabled()
    store = Store(tmp_path / "test.db")
    clip = cand(tmp_path)
    store.upsert_candidate(clip)
    pub = FakePub(settings)
    scheduler = Scheduler(settings, store, pubs(settings, pub))
    async def run():
        reviewed = asyncio.Event()
        release = asyncio.Event()
        lock = asyncio.Lock()
        scheduler.media_locks[clip.id] = lock
        async def guard(_candidate):
            assert lock.locked(), "Review and upload must hold the media mutation lock"
            reviewed.set()
            await release.wait()
            return True
        scheduler.quality_guard = guard
        posting = asyncio.create_task(scheduler._post("discord", clip.id))
        await reviewed.wait()
        assert lock.locked() and not pub.calls
        release.set()
        result = await posting
        assert result.ok and not lock.locked()
    try:
        asyncio.run(run())
    finally:
        store.close()


def test_final_review_cache_reuses_only_unchanged_video_and_policy(tmp_path, monkeypatch):
    import clipbot.pipeline as module
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    pipeline = Pipeline(settings, resolve_paths(settings))
    clip = cand(tmp_path)
    pipeline.store.upsert_candidate(clip)
    pipeline.vision = object()
    calls = []
    async def review(candidate, _settings, _vision):
        calls.append(candidate.id)
        return {"passed": True, "status": "complete", "reason": "Reviewed"}
    monkeypatch.setattr(module, "review_final", review)
    async def run():
        assert await pipeline._review_final(clip)
        assert await pipeline._review_final(clip)
        assert len(calls) == 1
        settings.review.min_confidence = 0.8
        assert await pipeline._review_final(clip)
        assert len(calls) == 2
        from pathlib import Path
        Path(clip.final_path).write_bytes(b"new video bytes")
        assert await pipeline._review_final(clip)
        assert len(calls) == 3
    try:
        asyncio.run(run())
    finally:
        pipeline.store.close()


def test_deleted_render_becomes_visible_failure_and_cannot_upload(tmp_path):
    from pathlib import Path
    from clipbot.models import Stage
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    pipeline = Pipeline(settings, resolve_paths(settings))
    clip = cand(tmp_path)
    pipeline.store.upsert_candidate(clip)
    Path(clip.final_path).unlink()
    try:
        assert not asyncio.run(pipeline._review_final(clip))
        assert clip.stage == Stage.FAILED
        assert clip.verdict["final_review"]["status"] == "unavailable"
        assert not clip.verdict["final_review"]["passed"]
    finally:
        pipeline.store.close()


def test_missing_review_frame_cannot_shift_image_timestamps(tmp_path):
    from clipbot.media import frames_dir
    from types import SimpleNamespace
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    pipeline = Pipeline(settings, resolve_paths(settings))
    pipeline.clipability = SimpleNamespace(one_model=lambda: True)
    clip = cand(tmp_path)
    clip.frame_times = [0, 1, 2]
    folder = frames_dir(pipeline.paths, clip.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "0.jpg").write_bytes(b"opening")
    (folder / "2.jpg").write_bytes(b"ending")
    try:
        import pytest
        with pytest.raises(OSError):
            asyncio.run(pipeline._judge_images(clip))
    finally:
        pipeline.store.close()


def test_direct_viewer_judge_does_not_need_an_extra_vision_model_call(tmp_path, monkeypatch):
    import base64
    import json
    from types import SimpleNamespace
    import clipbot.vision as vision_module
    from clipbot.clipability import parse_verdict
    from clipbot.vision import Vision
    from tests.test_clipability import GOOD, cand as raw_candidate
    from tests.test_viewer_review import viewer
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    pipeline = Pipeline(settings, resolve_paths(settings))
    clip = raw_candidate()
    calls = []
    async def frames(_path, times, _settings):
        return [f"image-{at}".encode() for at in times]
    async def never_describe(*_args, **_kwargs):
        raise AssertionError("A multimodal judge already sees the actual frames")
    async def judge(candidate, duration, _min_score, *, images, require_review):
        calls.append("judge")
        assert require_review and len(images) == len(candidate.frame_times)
        assert [base64.b64decode(image).decode() for image in images] == [f"image-{at}" for at in candidate.frame_times]
        return parse_verdict(json.dumps({**GOOD, "viewer_review": viewer()}), duration, settings)
    async def write(*_args):
        calls.append("writer")
        return {'_source': 'video', 'youtube': {'title': 'An unexpected second chance', 'description': ''}}
    pipeline.vision = Vision(settings, None)
    pipeline.clipability = SimpleNamespace(one_model=lambda: True, judge=judge)
    pipeline.copywriter = SimpleNamespace(write=write)
    pipeline.analytics = SimpleNamespace(notes=lambda: "")
    pipeline.trends = SimpleNamespace(brief=lambda *_args: "")
    monkeypatch.setattr(vision_module, "extract_frames", frames)
    monkeypatch.setattr(pipeline.vision, "describe", never_describe)
    try:
        asyncio.run(pipeline._think(clip, 37))
        assert calls == ["judge", "writer"]
        assert clip.verdict["passed"] and "Miss followed" in clip.visual
    finally:
        pipeline.store.close()
