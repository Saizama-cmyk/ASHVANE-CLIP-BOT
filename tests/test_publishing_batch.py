"""Batch publishing snapshots the queue and shares every normal upload gate and lock."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx

from clipbot.auth import ProfileStore
from clipbot.config import merge_incoming, resolve_paths
from clipbot.dashboard.server import create_app
from clipbot.models import Stage
from clipbot.pipeline import Pipeline
from clipbot.scheduler import Scheduler
from tests.test_scheduler import FakePub, cand, enabled, pubs


def pipeline_at(tmp_path):
    settings = merge_incoming(enabled(daily_cap=0), {
        "app": {"data_dir": str(tmp_path / "data")},
        "review": {"final_review": False},
        "posting": {"hours_start": 3, "hours_end": 4},
    })
    pipeline = Pipeline(settings, resolve_paths(settings))
    publisher = FakePub(settings)
    pipeline.scheduler = Scheduler(settings, pipeline.store, pubs(settings, publisher))
    pipeline.scheduler.media_locks = pipeline._media_locks
    return pipeline, publisher


def test_batch_snapshot_duplicate_click_and_progress_then_excludes_new_arrivals(tmp_path):
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        first, second = cand(tmp_path, created=1), cand(tmp_path, created=2)
        for clip in (first, second):
            pipeline.store.upsert_candidate(clip)
        started, release = asyncio.Event(), asyncio.Event()
        original = publisher._publish
        async def slow_publish(video, post):
            started.set()
            await release.wait()
            return await original(video, post)
        publisher._publish = slow_publish
        try:
            a, b = await asyncio.gather(pipeline.start_publishing_batch(), pipeline.start_publishing_batch())
            assert a["ok"] and a["job_id"] == b["job_id"] and a["total"] == b["total"] == 2
            await started.wait()
            progress = pipeline.publishing_batch_snapshot()
            assert progress["status"] == "running" and progress["current_id"] == first.id
            assert progress["completed"] == 0 and progress["platforms"] == ["discord"]
            late = cand(tmp_path, created=3)
            pipeline.store.upsert_candidate(late)
            progress["platforms"].append("youtube")
            assert pipeline.publishing_batch_snapshot()["platforms"] == ["discord"]
            release.set()
            await pipeline._publish_batch_task
            final = pipeline.publishing_batch_snapshot()
            assert final["status"] == "complete" and final["completed"] == final["posted"] == 2
            assert final["held"] == final["failed"] == 0 and final["current_id"] is None
            assert [row["clip_id"] for row in final["results"]] == [first.id, second.id]
            assert len(publisher.calls) == 2
            assert pipeline.store.get_candidate(late.id).stage == Stage.SCHEDULED
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_batch_continues_after_missing_media_quality_hold_and_exception(tmp_path):
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        missing, held, broken, good = [cand(tmp_path, created=n) for n in range(4)]
        excluded = cand(tmp_path, stage=Stage.REJECTED)
        for clip in (missing, held, broken, good, excluded):
            pipeline.store.upsert_candidate(clip)
        Path(missing.final_path).unlink()
        pipeline.settings.review.final_review = True
        async def review(clip):
            if clip.id == held.id:
                clip.error = "Final cut has no payoff"
                return False
            return True
        pipeline._review_final = review
        original = pipeline.publish_now
        async def publish(cid, platforms, **kwargs):
            if cid == broken.id:
                raise OSError("test media unavailable")
            return await original(cid, platforms, **kwargs)
        pipeline.publish_now = publish
        try:
            await pipeline.start_publishing_batch()
            await pipeline._publish_batch_task
            final = pipeline.publishing_batch_snapshot()
            assert final["status"] == "complete" and final["total"] == final["completed"] == 4
            assert (final["posted"], final["held"], final["failed"]) == (1, 1, 2)
            errors = {row["clip_id"]: row["error"] for row in final["results"]}
            assert "missing" in errors[missing.id] and "Restore" in errors[missing.id] and "no payoff" in errors[held.id]
            assert "unavailable" in errors[broken.id] and errors[good.id] == ""
            assert len(publisher.calls) == 1 and excluded.id not in errors
            assert pipeline.store.get_candidate(excluded.id).stage == Stage.REJECTED
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_batch_manual_and_automatic_race_uploads_the_same_platform_once(tmp_path):
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        clip = cand(tmp_path)
        pipeline.store.upsert_candidate(clip)
        entered, release = asyncio.Event(), asyncio.Event()
        original = publisher._publish
        async def slow_publish(video, post):
            entered.set()
            await release.wait()
            return await original(video, post)
        publisher._publish = slow_publish
        try:
            automatic = asyncio.create_task(pipeline.scheduler._post("discord", clip.id))
            await entered.wait()
            await pipeline.start_publishing_batch()
            manual = asyncio.create_task(pipeline.publish_now(clip.id, ["discord"]))
            release.set()
            automatic_result, manual_result, _ = await asyncio.gather(automatic, manual, pipeline._publish_batch_task)
            assert automatic_result.ok and manual_result["ok"]
            assert manual_result["results"]["discord"]["already_posted"] is True
            assert len(publisher.calls) == 1 and len(pipeline.store.posts_for_candidate(clip.id)) == 1
            assert pipeline.publishing_batch_snapshot()["posted"] == 1
            assert not pipeline._media_locks[clip.id].locked()
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_automatic_missing_media_check_waits_for_batch_restoring_the_render(tmp_path, monkeypatch):
    import clipbot.pipeline as module
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        clip = cand(tmp_path)
        Path(clip.final_path).unlink()
        source = tmp_path / "source.mp4"
        source.write_bytes(b"mock source")
        clip.raw_path = str(source)
        pipeline.store.upsert_candidate(clip)
        entered, release = asyncio.Event(), asyncio.Event()
        async def probe(*_args):
            return SimpleNamespace(duration=1)
        async def render(_source, output, *_args, **_kwargs):
            entered.set()
            await release.wait()
            output.write_bytes(b"restored render")
        monkeypatch.setattr(module, "probe_media", probe)
        monkeypatch.setattr(module, "render", render)
        try:
            await pipeline.start_publishing_batch()
            await entered.wait()
            pending = asyncio.create_task(pipeline.scheduler._pending_for("discord"))
            await asyncio.sleep(0)
            assert not pending.done()
            assert pipeline.store.get_candidate(clip.id).stage == Stage.SCHEDULED
            release.set()
            await pipeline._publish_batch_task
            assert await pending == []
            restored = pipeline.store.get_candidate(clip.id)
            assert restored.stage == Stage.POSTED and Path(restored.final_path).exists()
            assert len(publisher.calls) == 1 and pipeline.publishing_batch_snapshot()["posted"] == 1
        finally:
            release.set()
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_batch_rechecks_stage_under_media_lock_without_promoting_rejected_clip(tmp_path):
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        clip = cand(tmp_path)
        pipeline.store.upsert_candidate(clip)
        lock = pipeline._media_locks.setdefault(clip.id, asyncio.Lock())
        try:
            await lock.acquire()
            await pipeline.start_publishing_batch()
            clip.stage = Stage.REJECTED
            pipeline.store.upsert_candidate(clip)
            lock.release()
            await pipeline._publish_batch_task
            assert pipeline.publishing_batch_snapshot()["held"] == 1
            assert not publisher.calls and pipeline.store.get_candidate(clip.id).stage == Stage.REJECTED
        finally:
            if lock.locked():
                lock.release()
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_shutdown_interrupts_batch_without_reporting_completion_or_losing_lock(tmp_path):
    async def run():
        pipeline, publisher = pipeline_at(tmp_path)
        clip = cand(tmp_path)
        pipeline.store.upsert_candidate(clip)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def slow_publish(_video, _post):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        publisher._publish = slow_publish
        try:
            await pipeline.start_publishing_batch()
            await entered.wait()
            await pipeline.stop()
            final = pipeline.publishing_batch_snapshot()
            assert final["status"] == "idle" and final["interrupted"] and "interrupted" in final["error"]
            assert final["completed"] == final["posted"] == 0 and final["total"] == 1
            assert cancelled.is_set() and not pipeline._media_locks[clip.id].locked()
            assert not pipeline.store.posts_for_candidate(clip.id)
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_batch_rejects_no_ready_platforms_and_completes_empty_queue(tmp_path):
    async def run():
        pipeline, _publisher = pipeline_at(tmp_path)
        try:
            pipeline.settings.posting.discord.enabled = False
            assert not (await pipeline.start_publishing_batch())["ok"]
            assert pipeline.publishing_batch_snapshot()["status"] == "idle"
            pipeline.settings.posting.discord.enabled = True
            assert (await pipeline.start_publishing_batch())["total"] == 0
            await pipeline._publish_batch_task
            assert pipeline.publishing_batch_snapshot()["status"] == "complete"
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())


def test_batch_api_requires_session_and_action_header(tmp_path):
    async def run():
        pipeline, _publisher = pipeline_at(tmp_path)
        ctx = SimpleNamespace(settings=pipeline.settings, paths=pipeline.paths, pipeline=pipeline)
        app = create_app(ctx)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url=f"http://127.0.0.1:{pipeline.settings.dashboard.port}") as client:
                assert (await client.get("/api/publishing/batch")).status_code == 401
                assert (await client.post("/api/publishing/batch", headers={"X-ClipBot": "1"})).status_code == 401
                auth = ProfileStore()
                setup = await client.post("/api/auth/setup", headers={"X-ClipBot": "1"},
                                          json={"name": "Batch tester", "password": "safe-password-123"})
                assert setup.status_code == 200
                profile = setup.json()["profile"]
                token = auth.create_session(profile["id"], pipeline.settings.app.session_hours)
                client.headers["Authorization"] = f"Bearer {token}"
                snapshot = (await client.get("/api/publishing/batch")).json()
                assert snapshot["status"] == "idle"
                assert snapshot["scheduled_count"] == 0
                assert (await client.post("/api/publishing/batch")).status_code == 403
                response = await client.post("/api/publishing/batch", headers={"X-ClipBot": "1"})
                assert response.status_code == 200 and response.json()["ok"]
                await pipeline._publish_batch_task
                assert (await client.get("/api/publishing/batch")).json()["status"] == "complete"
        finally:
            await pipeline._stop_publish_batch()
            pipeline.store.close()
    asyncio.run(run())
