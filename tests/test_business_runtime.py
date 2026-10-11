"""Business controls stop real scoped tasks while keeping unrelated work and saved jobs."""
import asyncio
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clipbot.business_runtime import _BusinessWorkGuard, _work_business
from clipbot.config import Settings, resolve_paths
from clipbot.models import Candidate, Platform, SpikeEvent, Stage, StreamTarget
from clipbot.pipeline import Pipeline
from clipbot.stories import StoryBusy, StoryStudio
from clipbot.transcribe import Transcriber
from clipbot.util import child_count, run_cmd


def test_business_defaults_are_independent():
    settings = Settings()
    assert settings.businesses.surge_enabled
    assert settings.businesses.hollow_enabled
    assert not settings.businesses.resonance_enabled
    assert not settings.businesses.social_enabled


def test_disabled_businesses_never_start_background_work(tmp_path):
    async def run():
        settings = Settings()
        settings.app.data_dir = str(tmp_path)
        settings.businesses.surge_enabled = False
        settings.businesses.hollow_enabled = False
        pipeline = Pipeline(settings, resolve_paths(settings))
        pipeline._gpu_loop = lambda: asyncio.Event().wait()
        pipeline._recover = AsyncMock()
        await pipeline.start()
        try:
            pipeline._recover.assert_not_awaited()
            assert not pipeline._business_tasks["clips"]
            assert not pipeline._business_tasks["stories"]
            assert pipeline.scheduler._task is None
            assert pipeline.importer._task is None
            assert pipeline.research._timer is None
            assert pipeline.story_publishing._task is None
            assert pipeline.stories._closed
        finally:
            await pipeline.stop()
    asyncio.run(run())


def test_surge_stop_cancels_its_child_and_keeps_queue_and_hollow(tmp_path):
    async def run():
        settings = Settings()
        settings.app.data_dir = str(tmp_path)
        pipeline = Pipeline(settings, resolve_paths(settings))
        pipeline._running = True
        pipeline._business_running = {"clips": True, "stories": True}
        for name in ("importer", "analytics", "trends", "research", "chat"):
            setattr(pipeline, name, SimpleNamespace(stop=AsyncMock()))
        pipeline.captures = SimpleNamespace(stop_all=AsyncMock(), captures={"kick:test": object()})
        pipeline.scheduler = SimpleNamespace(_task=None, _busy={})
        target = StreamTarget(Platform.KICK, "test", "Test", "IRL", 1)
        event = SpikeEvent(target=target, t_wall=1, kind="chat", score=1, chat_rate=1, baseline=1)
        raw = tmp_path / "saved-source.mp4"
        raw.write_bytes(b"saved source")
        candidate = Candidate(id=event.id, event=event, raw_path=str(raw), stage=Stage.QC,
                              start_wall=0, end_wall=1)
        pipeline.store.upsert_candidate(candidate)
        pipeline._business_tasks["clips"].append(asyncio.create_task(
            run_cmd([sys.executable, "-c", "import time; time.sleep(60)"], 60)))
        hollow = asyncio.create_task(asyncio.Event().wait())
        pipeline._business_tasks["stories"].append(hollow)
        try:
            while not child_count():
                await asyncio.sleep(0)
            settings.businesses.surge_enabled = False
            await pipeline.reconcile_businesses()
            assert child_count() == 0
            assert not hollow.done()
            assert pipeline.business_state("clips")["running"] is False
            assert pipeline.business_state("stories")["running"] is True
            assert pipeline.store.get_candidate(candidate.id).stage is Stage.QC
            assert raw.read_bytes() == b"saved source"
            pipeline.captures.stop_all.assert_awaited_once()
            assert not pipeline.captures.captures
            pipeline.research.stop.assert_awaited_once()
        finally:
            hollow.cancel()
            await asyncio.gather(hollow, return_exceptions=True)
            pipeline.store.close()
    asyncio.run(run())


def test_stopping_one_business_does_not_wait_for_other_upload(tmp_path):
    async def run():
        settings = Settings()
        settings.app.data_dir = str(tmp_path)
        pipeline = Pipeline(settings, resolve_paths(settings))
        pipeline._running = True
        pipeline._business_running = {"clips": True, "stories": True}
        release = asyncio.Event()
        clips_stopping = asyncio.Event()
        hollow_stopped = asyncio.Event()

        async def stop(business):
            if business == "clips":
                clips_stopping.set()
                await release.wait()
            else:
                hollow_stopped.set()
            pipeline._business_running[business] = False
        pipeline._stop_business = stop
        settings.businesses.surge_enabled = False
        first = asyncio.create_task(pipeline.reconcile_businesses())
        await clips_stopping.wait()
        settings.businesses.hollow_enabled = False
        second = asyncio.create_task(pipeline.reconcile_businesses())
        try:
            await asyncio.wait_for(hollow_stopped.wait(), 1)
            assert not first.done()
        finally:
            release.set()
            await asyncio.gather(first, second)
            pipeline.store.close()
    asyncio.run(run())


def test_clip_cancelled_before_first_turn_keeps_durable_queue_row(tmp_path):
    async def run():
        settings = Settings()
        settings.app.data_dir = str(tmp_path)
        pipeline = Pipeline(settings, resolve_paths(settings))
        pipeline._sync_capture_pause = AsyncMock()
        target = StreamTarget(Platform.KICK, "test", "Test", "IRL", 1)
        event = SpikeEvent(target=target, t_wall=1, kind="chat", score=1, chat_rate=1, baseline=1)
        candidate = Candidate(id=event.id, event=event, raw_path="", start_wall=0, end_wall=1)
        pipeline._launch(candidate)
        task = pipeline._inflight[candidate.id]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pipeline._persist_pending_candidates()
        assert pipeline.store.get_candidate(candidate.id).stage is Stage.QUEUED
        pipeline.store.close()
    asyncio.run(run())


def test_story_stop_before_first_task_turn_persists_draft(tmp_path):
    async def run():
        settings = Settings()
        studio = StoryStudio(settings, None, SimpleNamespace(data=tmp_path))
        project = studio.create("The bell below the lake", "paranormal", "still", 60)
        await studio.stop()
        saved = studio.get(project["id"])
        assert saved["status"] == "interrupted"
        assert saved["topic"] == project["topic"]
        reloaded = StoryStudio(settings, None, SimpleNamespace(data=tmp_path))
        assert reloaded.get(project["id"])["status"] == "interrupted"
        settings.businesses.hollow_enabled = False
        studio.start()
        with pytest.raises(StoryBusy, match="Hollow is stopped"):
            studio.create("Another bell", "paranormal", "still", 60)
    asyncio.run(run())


def test_transcribe_cancel_drains_native_thread_before_freeing_slot(tmp_path):
    async def run():
        transcriber = Transcriber(Settings())
        entered, release = threading.Event(), threading.Event()

        def inference(_path):
            entered.set()
            release.wait()
            return "finished"
        transcriber._transcribe_sync = inference
        task = asyncio.create_task(transcriber.transcribe(tmp_path / "source.mp4"))
        await asyncio.to_thread(entered.wait)
        task.cancel()
        await asyncio.sleep(0)
        assert transcriber.jobs == 1
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transcriber.jobs == 0
    asyncio.run(run())


@pytest.mark.parametrize("path,business", [
    ("/api/clip_import/run", "clips"), ("/api/research/draft", "clips"),
    ("/api/publishing/batch", "clips"), ("/api/clips/a/publish", "clips"),
    ("/api/stories", "stories"), ("/api/stories/a/render", "stories"),
    ("/api/stories/accounts/youtube/disconnect", None), ("/api/control/quit", None),
])
def test_guard_scopes_only_work_commands(path, business):
    assert _work_business(path, "POST") == business
    assert _work_business(path, "GET") is None


def test_stopped_guard_blocks_work_but_allows_reads():
    async def run():
        downstream = AsyncMock()
        pipeline = SimpleNamespace(business_enabled=lambda business: False,
                                   _business_transition=set())
        guard = _BusinessWorkGuard(downstream, SimpleNamespace(pipeline=pipeline))
        send = AsyncMock()
        await guard({"type": "http", "path": "/api/clip_import/run", "method": "POST"},
                    AsyncMock(), send)
        assert send.call_args_list[0].args[0]["status"] == 409
        downstream.assert_not_called()
        await guard({"type": "http", "path": "/api/stories", "method": "GET"}, AsyncMock(), send)
        downstream.assert_awaited_once()
    asyncio.run(run())
