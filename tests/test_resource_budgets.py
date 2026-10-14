"""Measured worker queues and bounded creative admission, without real inference."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import httpx
import pytest

from clipbot.business_runtime import resource_budget_snapshot
from clipbot.config import Settings, resolve_paths
from clipbot.creative_tools import CreativeTools
from clipbot.pipeline import Limiter, Pipeline
from clipbot.social_api import SocialStudio


def creative_context():
    settings = Settings()
    settings.businesses.social_enabled = True
    settings.businesses.hollow_enabled = True
    settings.creative.max_pending_per_business = 2
    lock = asyncio.Lock()
    ctx = SimpleNamespace(settings=settings, pipeline=SimpleNamespace(stories=SimpleNamespace(_gpu_lock=lock)))
    ctx.creative_tools = CreativeTools(ctx)
    return ctx


def test_limiter_waiting_cancellation_and_runtime_downsize_are_exact():
    async def run():
        limiter = Limiter(2)
        await limiter.__aenter__()
        await limiter.__aenter__()
        first = asyncio.create_task(limiter.__aenter__())
        second = asyncio.create_task(limiter.__aenter__())
        await asyncio.sleep(0)
        assert limiter.snapshot() == {"active": 2, "waiting": 2, "limit": 2, "available": 0}
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        assert limiter.waiting == 1
        await limiter.set_limit(1)
        await limiter.__aexit__()
        assert limiter.active == 1 and limiter.waiting == 1 and not second.done()
        await limiter.__aexit__()
        await second
        assert limiter.active == 1 and limiter.waiting == 0
        await limiter.__aexit__()
        assert limiter.snapshot() == {"active": 0, "waiting": 0, "limit": 1, "available": 1}
    asyncio.run(run())


def test_limiter_cancelled_release_still_returns_capacity():
    async def run():
        limiter = Limiter(1)
        await limiter.__aenter__()
        await limiter._cond.acquire()
        leaving = asyncio.create_task(limiter.__aexit__())
        await asyncio.sleep(0)
        leaving.cancel()
        await asyncio.sleep(0)
        assert not leaving.done() and limiter.active == 1
        limiter._cond.release()
        await asyncio.gather(leaving, return_exceptions=True)
        assert leaving.cancelled() and limiter.active == limiter.waiting == 0
    asyncio.run(run())


def test_pipeline_resource_snapshot_uses_actual_queues_without_private_work(tmp_path):
    async def run():
        settings = Settings()
        settings.app.data_dir = str(tmp_path)
        pipeline = Pipeline(settings, resolve_paths(settings))
        pipeline.gpu_lock = asyncio.Lock()
        await pipeline.gpu_lock.acquire()
        gpu_waiter = asyncio.create_task(pipeline.gpu_lock.acquire())
        await pipeline._ai_limit.__aenter__()
        ai_waiter = asyncio.create_task(pipeline._ai_limit.__aenter__())
        now = time.time()
        pipeline._latency = {"private-candidate": {"id": "private-candidate", "created_at": now - 2,
                              "phase": "ai_wait", "phase_started_at": now - 1, "stages_s": {}},
                             "finished-private": {"created_at": now - 2, "finished_at": now, "phase": "edit_wait", "stages_s": {}}}
        try:
            await asyncio.sleep(0)
            budget = pipeline.resource_budget_snapshot()
            assert budget["ai"]["active"] == 1 and budget["ai"]["waiting"] == 1
            assert budget["shared_gpu"] == {"locked": True, "waiting": 1, "waiting_reason": "shared_gpu_busy"}
            assert budget["phases"] == {"ai_wait": 1}
            assert "private" not in json.dumps(budget)
            latency = pipeline.latency_snapshot()
            assert latency["active_jobs"][0]["waiting_reason"] == "waiting_for_ai_slot"
            assert latency["recent_jobs"][0]["waiting_reason"] is None
            assert latency["worker_queues"]["ai"]["waiting"] == 1
        finally:
            gpu_waiter.cancel()
            ai_waiter.cancel()
            await asyncio.gather(gpu_waiter, ai_waiter, return_exceptions=True)
            pipeline.gpu_lock.release()
            await pipeline._ai_limit.__aexit__()
            pipeline.store.close()
    asyncio.run(run())


def test_creative_queue_is_bounded_before_http_and_reports_real_gpu_wait(monkeypatch):
    async def run():
        ctx = creative_context()
        service = ctx.creative_tools
        entered, release = asyncio.Event(), asyncio.Event()
        constructor = httpx.AsyncClient
        requests = []
        async def respond(request):
            requests.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"message": {"content": '{"answer":"original"}'}})
        monkeypatch.setattr("clipbot.creative_tools.httpx.AsyncClient", lambda **kwargs: constructor(transport=httpx.MockTransport(respond), **kwargs))
        first = asyncio.create_task(service.chat("social", "contract", {"private": "do not expose"}))
        await entered.wait()
        second = asyncio.create_task(service.chat("social", "contract", {}))
        await asyncio.sleep(0)
        try:
            budget = service.snapshot("social")
            assert budget["pending"] == 2 and budget["active"] == 1 and budget["waiting"] == 1
            assert budget["waiting_reason"] == "shared_gpu_busy" and budget["admission_full"]
            with pytest.raises(HTTPException) as full:
                await service.chat("social", "contract", {})
            assert full.value.status_code == 429
            assert len(requests) == 1 and len(service.tasks["social"]) == 2
            assert "private" not in json.dumps(service.snapshot())
            release.set()
            assert await first == await second == {"answer": "original"}
            assert service.snapshot("social")["pending"] == 0
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await service.close()
    asyncio.run(run())


def test_social_drafts_share_chat_admission_and_business_cancel_keeps_other_business():
    async def run():
        ctx = creative_context()
        ctx.settings.creative.max_pending_per_business = 1
        service = ctx.creative_tools
        studio = SocialStudio.__new__(SocialStudio)
        studio.ctx = ctx
        entered = asyncio.Event()
        async def draft(*args):
            entered.set()
            await asyncio.Event().wait()
        studio._draft = draft
        social = asyncio.create_task(studio.draft("private-client", {}))
        await entered.wait()
        other_entered = asyncio.Event()
        async def other():
            async with service.admission("stories"):
                other_entered.set()
                await asyncio.Event().wait()
        story = asyncio.create_task(other())
        await other_entered.wait()
        try:
            with pytest.raises(HTTPException) as full:
                await service.chat("social", "contract", {})
            assert full.value.status_code == 429
            assert service.snapshot("social")["pending"] == 1
            await service.cancel_business("social")
            assert social.cancelled() and service.snapshot("social")["pending"] == 0
            assert not story.done() and service.snapshot("stories")["pending"] == 1
        finally:
            await service.close()
            await asyncio.gather(social, story, return_exceptions=True)
    asyncio.run(run())


def test_creative_preparation_failure_and_nested_admission_release_exactly_once():
    async def run():
        ctx = creative_context()
        service = ctx.creative_tools
        try:
            async with service.admission("social"):
                async with service.admission("social"):
                    assert service.snapshot("social")["pending"] == 1
                    raise ValueError("Preparation failed")
        except ValueError:
            pass
        assert service.snapshot("social")["pending"] == 0
        service._chat = AsyncMock(side_effect=ValueError("Invalid payload before model request"))
        with pytest.raises(ValueError):
            await service.chat("social", "contract", {})
        assert not service.tasks["social"] and not service.phases["social"]
    asyncio.run(run())


def test_existing_single_producer_limits_are_reported_without_creating_services():
    ctx = creative_context()
    ctx.pipeline.stories.busy = True
    ctx.music_bridge = SimpleNamespace(producer=SimpleNamespace(busy=False))
    budgets = resource_budget_snapshot(ctx)
    assert budgets["story_production"] == {"limit": 1, "active": 1, "queue_policy": "reject_while_active"}
    assert budgets["music_production"] == {"limit": 1, "active": 0, "queue_policy": "reject_while_active"}
    assert len(budgets["creative"]) == 4
