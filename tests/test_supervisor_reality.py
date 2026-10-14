"""Real controller boundaries with deterministic local doubles; no model/Docker/network."""
import asyncio
import json
from unittest.mock import AsyncMock
from types import SimpleNamespace

import httpx
import pytest

from tests.test_supervisor import context, finish, local_model
from clipbot.supervisor import BusinessBusy


@pytest.mark.parametrize("cancel", [False, True])
def test_core_joins_shared_startup_without_cancelling_it(tmp_path, monkeypatch, cancel):
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        gate = asyncio.Event()
        startup = asyncio.create_task(gate.wait())
        ctx.dependencies = SimpleNamespace(task=startup, request=lambda: None)
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        supervisor._agent = AsyncMock(return_value="Verified after startup")
        supervisor.run("Inspect after local AI starts")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert supervisor.snapshot()["blocking_reason"]["code"] == "local_service_starting"
        supervisor.capabilities.assert_not_awaited()
        try:
            if cancel:
                await supervisor.cancel()
                assert not startup.cancelled()
                supervisor._agent.assert_not_awaited()
                assert supervisor.snapshot()["pending_job"] is None
            else:
                gate.set()
                await supervisor._job_task
                supervisor.capabilities.assert_awaited_once()
                supervisor._agent.assert_awaited_once()
                assert supervisor.memory.data["jobs"][-1]["status"] == "completed"
        finally:
            gate.set()
            await startup
            await supervisor.close()
    asyncio.run(run())


def test_shared_startup_timeout_does_not_cancel_service_or_infer(tmp_path, monkeypatch):
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        gate = asyncio.Event()
        startup = asyncio.create_task(gate.wait())
        ctx.dependencies = SimpleNamespace(task=startup, request=lambda: None)
        supervisor.settings.ai.startup_timeout_s = 1
        supervisor.settings.ai.startup_poll_s = .1
        supervisor.capabilities = AsyncMock()
        supervisor._agent = AsyncMock()
        try:
            await supervisor._investigate("Startup must have a deadline")
            assert supervisor.memory.data["jobs"][-1]["status"] == "failed"
            assert not startup.cancelled()
            supervisor.capabilities.assert_not_awaited()
            supervisor._agent.assert_not_awaited()
        finally:
            gate.set()
            await startup
            await supervisor.close()
    asyncio.run(run())


def test_live_pending_goal_can_be_cancelled_and_history_is_not_pending(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        supervisor._agent = AsyncMock(side_effect=BusinessBusy("Business work arrived"))
        try:
            await supervisor._investigate("Keep this goal until cancelled")
            pending = supervisor.snapshot()["pending_job"]
            assert pending["goal"] == "Keep this goal until cancelled"
            assert pending["status"] == "deferred" and pending["remaining_turns"] == supervisor.cfg.max_turns
            await supervisor.cancel()
            assert supervisor.snapshot()["pending_job"] is None
            supervisor.memory.data["jobs"].append({"id": "historical", "status": "deferred"})
            assert supervisor.snapshot()["pending_job"] is None
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_model_outage_keeps_other_capabilities_and_explicit_blocker(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        await supervisor.http.aclose()
        async def unavailable(request):
            raise httpx.ConnectError("password=private-server-note", request=request)
        supervisor.http = httpx.AsyncClient(transport=httpx.MockTransport(unavailable))
        try:
            cap = await supervisor.capabilities()
            assert cap["source"]["available"] and cap["isolation"]["ready"]
            assert not cap["inference_ready"] and not cap["repair_ready"]
            assert cap["model_inventory"]["error_type"] == "ConnectError"
            snapshot = supervisor.snapshot()
            assert snapshot["blocking_reason"]["code"] == "model_service_unavailable"
            assert "private-server-note" not in json.dumps(snapshot)
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_missing_coder_allows_research_but_cannot_execute_engineer(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        requests = await local_model(supervisor, [finish("Inspection complete; no repair claimed")])
        original = supervisor.http
        async def decision_only(request):
            if request.method == "GET":
                return httpx.Response(200, json={"models": [{"name": supervisor.cfg.model}]})
            return await original.send(request)
        supervisor.http = httpx.AsyncClient(transport=httpx.MockTransport(decision_only))
        try:
            await supervisor._investigate("Inspect capabilities")
            assert supervisor.memory.data["jobs"][-1]["status"] == "completed"
            assert supervisor.snapshot()["capabilities"]["inference_ready"]
            assert not supervisor.snapshot()["capabilities"]["repair_ready"]
            supervisor._remaining = 1
            with pytest.raises(ValueError, match="specialist model"):
                await supervisor._ask("engineer", [])
            assert supervisor._remaining == 1
            assert len(requests) == 1
        finally:
            await supervisor.close()
            await original.aclose()
    asyncio.run(run())


def test_busy_causes_are_fixed_identifiers_and_capture_watchers_do_not_block(tmp_path, monkeypatch):
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        try:
            ctx.pipeline.captures = {"private-channel": object()}
            assert not supervisor._busy()
            ctx.pipeline._inflight = {"private-candidate": object()}
            first = supervisor.snapshot()
            assert first["blocking_reason"]["details"] == ["clip_generation_active"]
            assert first["blocking_since"] is not None
            assert supervisor.snapshot()["blocking_since"] == first["blocking_since"]
            assert "private-candidate" not in json.dumps(first)
            ctx.pipeline._inflight.clear()
            assert supervisor.snapshot()["blocking_reason"] is None
            assert supervisor.snapshot()["blocking_since"] is None
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_results_have_linked_receipts_and_budget_exhaustion_is_not_completed(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        actions = [
            {"action": "list_source", "summary": "This is only a request", "arguments": {}},
            {"action": "read_source", "summary": "Attempt missing source", "arguments": {"path": "clipbot/missing.py"}},
            {"action": "training_example", "summary": "Untested generated answer", "arguments": {"instruction": "question", "response": "answer"}},
        ]
        await local_model(supervisor, actions)
        try:
            await supervisor._investigate("Inspect")
            snap = supervisor.snapshot()
            assert snap["jobs"][-1]["status"] == "budget_exhausted"
            receipts = snap["work_receipts"]
            assert len(receipts) == 3
            assert [row["outcome"] for row in receipts] == ["completed", "failed", "completed"]
            assert receipts[-1]["eligible"] is False and receipts[-1]["verified"] is False
            requests = {row["id"]: row for row in snap["events"] if row.get("phase") == "requested"}
            assert all(row["request_id"] in requests for row in receipts)
            assert all(row["job_id"] == snap["jobs"][-1]["id"] for row in receipts)
            assert not snap["examples"]["eligible"]
            assert "answer" not in json.dumps(receipts)
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_invalid_delegation_cannot_create_phantom_goal(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        try:
            with pytest.raises(ValueError):
                await supervisor._tool("director", "delegate", {"role": "absent", "task": "Inspect"})
            assert not supervisor.memory.data["goals"]
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_gpu_lock_race_rechecks_business_and_master_before_model_submission(tmp_path, monkeypatch):
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        class BusinessArrives:
            def locked(self):
                return False
            async def __aenter__(self):
                ctx.pipeline._inflight = {"private-item": object()}
            async def __aexit__(self, *args):
                pass
        ctx.pipeline.gpu_lock = BusinessArrives()
        requests = await local_model(supervisor, [])
        supervisor._remaining = 2
        try:
            with pytest.raises(BusinessBusy):
                await supervisor._ask("director", [])
            assert supervisor._remaining == 2 and not requests
            ctx.pipeline._inflight.clear()
            class MasterTurnsOff(BusinessArrives):
                async def __aenter__(self):
                    supervisor.cfg.enabled = False
            ctx.pipeline.gpu_lock = MasterTurnsOff()
            with pytest.raises(asyncio.CancelledError):
                await supervisor._ask("director", [])
            assert supervisor._remaining == 2 and not requests
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_busy_preparation_collects_real_public_receipts_without_inference(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        supervisor.cfg.research_sources = ["https://example.org/one", "https://example.org/two"]
        supervisor._public = AsyncMock(side_effect=[{"provenance": {"sha256": "verified-hash"}}, httpx.ConnectError("failed")])
        supervisor._ask = AsyncMock(side_effect=AssertionError("Inference forbidden"))
        try:
            await supervisor._prepare_public_evidence()
            receipt = supervisor.snapshot()["work_receipts"][-1]
            assert receipt["outcome"] == "partial" and receipt["sources_fetched"] == 1
            assert receipt["initiated_by"] == "scheduler"
            supervisor._ask.assert_not_awaited()
            supervisor.cfg.enabled = False
            supervisor._public.reset_mock()
            await supervisor._prepare_public_evidence()
            supervisor._public.assert_not_awaited()
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_core_inference_is_not_reported_as_business_gpu_ownership(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        async def thinking(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"message": {"content": json.dumps(finish())}})
        await local_model(supervisor, [], thinking)
        supervisor._remaining = 1
        task = asyncio.create_task(supervisor._ask("director", []))
        try:
            await entered.wait()
            assert supervisor.ctx.pipeline.gpu_lock.locked()
            assert supervisor.snapshot()["observations"]["business_generation_active"] is False
            assert supervisor.snapshot()["blocking_reason"] is None
            release.set()
            await task
            assert supervisor._inference_owns_gpu is False
            assert supervisor._receipt("call_extension", {"status": "failed", "result": {"isError": True}})["outcome"] == "failed"
        finally:
            release.set()
            await task
            await supervisor.close()
    asyncio.run(run())


def test_scheduler_busy_rechecks_promptly_but_completed_cycles_keep_interval(tmp_path, monkeypatch):
    async def run():
        import clipbot.supervisor as module
        ctx, supervisor = context(tmp_path, monkeypatch)
        clock = {"now": 1000.0}
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["now"]))
        real_sleep = asyncio.sleep
        supervisor.cfg.idle_recheck_s = 15
        supervisor.cfg.interval_min = 1
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        supervisor._prepare_public_evidence = AsyncMock()
        starts, sleeping = [], []
        async def agent(role, task):
            starts.append(clock["now"])
            return "Actual deterministic test completion"
        supervisor._agent = agent
        ctx.pipeline._inflight = {"private": object()}
        async def sleep(seconds):
            sleeping.append((seconds, supervisor._next_cycle_at))
            if len(sleeping) == 1:
                assert supervisor.state == "waiting_for_business" and supervisor._next_cycle_at is None
                ctx.pipeline._inflight.clear()
            await real_sleep(0)
            if len(starts) >= 2:
                supervisor.cfg.enabled = False
            clock["now"] += seconds
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        try:
            await supervisor._schedule()
            assert starts[0] == 1015
            assert starts[1] - starts[0] >= 60
            assert len(starts) == 2
            supervisor._prepare_public_evidence.assert_awaited_once()
            assert any(next_at is not None for _, next_at in sleeping)
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_busy_polling_does_not_refetch_public_feeds_every_tick(tmp_path, monkeypatch):
    async def run():
        import clipbot.supervisor as module
        ctx, supervisor = context(tmp_path, monkeypatch)
        clock = {"now": 1000.0, "sleeps": 0}
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["now"]))
        real_sleep = asyncio.sleep
        supervisor.cfg.idle_recheck_s = 15
        supervisor.cfg.interval_min = 1
        ctx.pipeline._inflight = {"private": object()}
        supervisor._prepare_public_evidence = AsyncMock()
        supervisor._agent = AsyncMock(side_effect=AssertionError("No inference while busy"))
        async def sleep(seconds):
            assert supervisor._next_cycle_at is None
            clock["sleeps"] += 1
            clock["now"] += seconds
            if clock["sleeps"] == 5:
                supervisor.cfg.enabled = False
            await real_sleep(0)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        try:
            await supervisor._schedule()
            assert supervisor._prepare_public_evidence.await_count == 2
            supervisor._agent.assert_not_awaited()
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_deferred_owner_goal_resumes_same_job_without_resetting_turn_budget(tmp_path, monkeypatch):
    async def run():
        import clipbot.supervisor as module
        ctx, supervisor = context(tmp_path, monkeypatch)
        clock = {"now": 1000.0}
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["now"]))
        real_sleep = asyncio.sleep
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        calls = []
        async def agent(role, task):
            calls.append((task, supervisor._remaining))
            if len(calls) == 1:
                supervisor._remaining -= 1
                ctx.pipeline._inflight = {"private": object()}
                raise BusinessBusy("Business arrived")
            assert task["owner_goal"] == "Investigate the owner's actual request"
            assert task["observations"]["resumed_investigation"]["remaining_turns"] == 2
            supervisor._remaining -= 1
            return "Resumed and completed in test"
        supervisor._agent = agent
        await supervisor._investigate("Investigate the owner's actual request")
        original_id = supervisor.memory.data["jobs"][-1]["id"]
        assert supervisor._deferred["remaining"] == 2
        ctx.pipeline._inflight.clear()
        async def sleep(seconds):
            clock["now"] += seconds
            await real_sleep(0)
            if len(calls) == 2:
                supervisor.cfg.enabled = False
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        try:
            await supervisor._schedule()
            assert len(supervisor.memory.data["jobs"]) == 1
            job = supervisor.memory.data["jobs"][0]
            assert job["id"] == original_id and job["status"] == "completed"
            assert [remaining for _, remaining in calls] == [3, 2]
            assert supervisor._remaining == 1 and supervisor._deferred is None
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_cancelled_deferred_goal_is_not_queued_again(tmp_path, monkeypatch):
    async def run():
        import clipbot.supervisor as module
        ctx, supervisor = context(tmp_path, monkeypatch)
        clock = {"now": 1000.0}
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["now"]))
        real_sleep = asyncio.sleep
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        async def busy(role, task):
            raise BusinessBusy("Business arrived")
        supervisor._agent = busy
        await supervisor._investigate("Owner goal that must not resume after cancellation")
        await supervisor.cancel()
        assert supervisor._deferred is None
        assert supervisor.memory.data["jobs"][0]["status"] == "cancelled"
        supervisor._agent = AsyncMock(side_effect=AssertionError("Cancelled work must not resume"))
        async def sleep(seconds):
            assert supervisor._next_cycle_at > clock["now"]
            clock["now"] += seconds
            supervisor.cfg.enabled = False
            await real_sleep(0)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        try:
            await supervisor._schedule()
            supervisor._agent.assert_not_awaited()
            assert len(supervisor.memory.data["jobs"]) == 1
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_cancelled_active_goal_cannot_become_a_deferred_resume(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        entered = asyncio.Event()
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        async def active(role, task):
            entered.set()
            await asyncio.Event().wait()
        supervisor._agent = active
        supervisor.run("Owner goal cancelled during work")
        await entered.wait()
        await supervisor.cancel()
        try:
            assert supervisor._deferred is None and supervisor._job_task is None
            assert supervisor.memory.data["jobs"][0]["status"] == "cancelled"
            assert supervisor.snapshot()["next_cycle_at"] is not None
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_slow_public_preparation_cannot_block_idle_pickup_and_is_drained(tmp_path, monkeypatch):
    async def run():
        import clipbot.supervisor as module
        ctx, supervisor = context(tmp_path, monkeypatch)
        clock = {"now": 1000.0}
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["now"]))
        real_sleep = asyncio.sleep
        started, drained = asyncio.Event(), asyncio.Event()
        async def prepare():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        supervisor._prepare_public_evidence = prepare
        supervisor.capabilities = AsyncMock(return_value={"models": [supervisor.cfg.model]})
        calls = []
        async def agent(role, task):
            assert started.is_set() and not drained.is_set()
            calls.append(clock["now"])
            return "Completed while the public fetch still waited"
        supervisor._agent = agent
        ctx.pipeline._inflight = {"private": object()}
        async def sleep(seconds):
            await real_sleep(0)
            if started.is_set():
                ctx.pipeline._inflight.clear()
            clock["now"] += seconds
            if calls:
                supervisor.cfg.enabled = False
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        try:
            await supervisor._schedule()
            assert calls == [1015]
            assert not drained.is_set()
            await supervisor.cancel()
            assert drained.is_set() and supervisor._preparation_task is None
        finally:
            await supervisor.close()
    asyncio.run(run())
