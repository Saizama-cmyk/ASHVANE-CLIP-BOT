"""Real supervisor loop and guarded HTTP API with local mocked inference only."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from clipbot.config import Settings, load_settings, save_settings
from clipbot.supervisor import Supervisor, local_endpoint


class OwnedService:
    def __init__(self, settings, workspace):
        self.settings, self.workspace, self._closed = settings, workspace, False
        self.close_calls = 0
        self.install = AsyncMock(return_value={"status": "ready"})
        self.call = AsyncMock(return_value={"content": "public"})

    def inventory(self):
        return []

    async def readiness(self):
        return {"ready": True, "status": "ready"}

    async def close(self):
        self.close_calls += 1
        self._closed = True


def context(tmp_path, monkeypatch, *, enabled=True):
    import clipbot.supervisor as module
    monkeypatch.setattr(module, "Sandbox", OwnedService)
    monkeypatch.setattr(module, "Extensions", OwnedService)
    settings = Settings()
    settings.supervisor.enabled = enabled
    settings.supervisor.max_turns = 3
    source = tmp_path / "source"
    (source / "clipbot").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / "clipbot" / "logic.py").write_bytes(b"def value(): return 1\n")
    (source / "tests" / "test_logic.py").write_bytes(b"def test_existing(): assert True\n")
    (source / "pytest.ini").write_bytes(b"[pytest]\ntestpaths = tests\n")
    settings.supervisor.source_root = str(source)
    ctx = SimpleNamespace(settings=settings, paths=SimpleNamespace(data=tmp_path / "data"),
        pipeline=SimpleNamespace(gpu_lock=asyncio.Lock(), _inflight={}),
        pet_token="synthetic-pet-token", restart_pending=set())
    supervisor = Supervisor(ctx)
    ctx.supervisor = supervisor

    async def commit(new):
        save_settings(new, tmp_path / "saved-settings.json")
        ctx.settings = new
        await supervisor.reconfigure(new)
        return []

    ctx.commit_settings = commit
    return ctx, supervisor


async def local_model(supervisor, actions, handler=None):
    await supervisor.http.aclose()
    requests = []

    async def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": supervisor.cfg.model}, {"name": supervisor.cfg.coder_model}]})
        if handler:
            return await handler(request)
        action = actions.pop(0)
        return httpx.Response(200, json={"message": {"content": json.dumps(action)}})

    supervisor.http = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=False)
    return requests


def finish(summary="Measured investigation complete"):
    return {"action": "finish", "summary": summary, "arguments": {}}


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434", "https://api.openai.com", "http://another-pc:11434",
    "http://192.168.1.1:11434", "http://127.0.0.1:11434?key=secret", "http://user:pass@localhost:11434"])
def test_hosted_remote_or_credentialed_model_endpoint_rejected(url):
    with pytest.raises(ValueError, match="loopback"):
        local_endpoint(url)


def test_master_off_persists_cancels_jobs_and_owned_services_and_reenable_is_fresh(tmp_path, monkeypatch):
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked_model(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        await local_model(supervisor, [], blocked_model)
        first_sandbox, first_extensions = supervisor.sandbox, supervisor.extensions
        try:
            await supervisor.start()
            scheduler = supervisor._scheduler
            await asyncio.wait_for(entered.wait(), 3)
            job = supervisor._job_task
            off = ctx.settings.model_copy(deep=True)
            off.supervisor.enabled = False
            await ctx.commit_settings(off)
            assert load_settings(tmp_path / "saved-settings.json").supervisor.enabled is False
            assert scheduler.cancelled() and job.cancelled() and cancelled.is_set()
            assert supervisor._scheduler is None and supervisor._job_task is None and supervisor._active is None
            assert supervisor.state == "off" and all(row["status"] == "idle" for row in supervisor.agents.values())
            assert first_sandbox._closed and first_extensions._closed
            assert supervisor.memory.data["jobs"][-1]["status"] == "cancelled"
            with pytest.raises(ValueError, match="master switch"):
                supervisor.run()
            on = off.model_copy(deep=True)
            on.supervisor.enabled = True
            await ctx.commit_settings(on)
            assert supervisor.sandbox is not first_sandbox and supervisor.extensions is not first_extensions
            assert not supervisor.sandbox._closed and supervisor._scheduler is not None
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_off_default_has_no_background_scheduler(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch, enabled=False)
        try:
            await supervisor.start()
            assert supervisor._scheduler is None and supervisor.state == "off"
            with pytest.raises(ValueError):
                supervisor.run("Investigate")
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_runtime_evidence_reaches_director_and_stops_with_master(tmp_path, monkeypatch):
    import logging

    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        received = []

        async def agent(role, task):
            received.append((role, task))
            return 'Observed recurring fault; no repair claimed'

        supervisor._agent = agent
        supervisor.capabilities = AsyncMock(return_value={'models': [supervisor.cfg.model, supervisor.cfg.coder_model]})
        supervisor.observations.start()
        try:
            logging.getLogger('clipbot.capture').warning('private-account-token=%s', 'do-not-send')
            await supervisor._investigate('Inspect observed recurring faults')
            observed = received[0][1]['observations']
            assert observed['faults'][0]['source'] == 'capture' and observed['fault_events'] == 1
            assert 'do-not-send' not in json.dumps(received) and 'private-account' not in json.dumps(received)
            off = ctx.settings.model_copy(deep=True)
            off.supervisor.enabled = False
            await supervisor.reconfigure(off)
            assert not supervisor.observations.attached
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_busy_supervisor_collects_faults_without_model_request(tmp_path, monkeypatch):
    import logging

    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        ctx.pipeline._inflight = {'private-candidate': object()}
        requests = await local_model(supervisor, [])
        try:
            await supervisor.start()
            await asyncio.sleep(0)
            logging.getLogger('clipbot.capture').warning('private content')
            value = supervisor.snapshot()
            assert value['state'] == 'waiting_for_business'
            assert value['observations']['fault_events'] == 1
            assert value['observations']['inference_deferred'] is True
            assert requests == []
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_master_stop_drains_an_already_started_atomic_commit(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()

        async def atomic_commit():
            entered.set()
            await release.wait()
            return {"status": "source_applied"}

        commit = asyncio.create_task(atomic_commit())
        supervisor._commit = commit
        await entered.wait()
        stopping = asyncio.create_task(supervisor.cancel())
        try:
            await asyncio.sleep(0)
            assert not stopping.done() and not commit.cancelled()
            release.set()
            await stopping
            assert commit.done() and not commit.cancelled() and supervisor._commit is None
        finally:
            release.set()
            await supervisor.close()
    asyncio.run(run())


def test_remote_endpoint_and_oversized_local_response_fail_without_hosted_fallback(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        requests = await local_model(supervisor, [finish()])
        try:
            supervisor.settings.ai.ollama_url = "http://remote-model.example:11434"
            supervisor.run()
            await supervisor._job_task
            assert not requests and supervisor.memory.data["jobs"][-1]["status"] == "failed"
            supervisor.settings.ai.ollama_url = "http://127.0.0.1:11434"
            supervisor.cfg.response_max_bytes = 4096

            async def oversized(request):
                return httpx.Response(200, content=b"x" * 4097)

            requests = await local_model(supervisor, [], oversized)
            supervisor.run()
            await supervisor._job_task
            assert supervisor.memory.data["jobs"][-1]["status"] == "failed"
            assert "size limit" in supervisor.error
            assert all(request.url.host == "127.0.0.1" for request in requests)
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_delegation_shares_turn_budget_and_finishes_with_bounded_local_requests(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        actions = [{"action": "delegate", "summary": "Investigate public evidence", "arguments": {"role": "researcher", "task": "Check current source capability"}},
                   finish("Research complete"), finish("Director assessed evidence")]
        requests = await local_model(supervisor, actions)
        try:
            supervisor.run("Investigate a useful improvement")
            await supervisor._job_task
            assert supervisor._remaining == 0 and not actions
            assert supervisor.memory.data["jobs"][-1]["status"] == "completed"
            assert supervisor.memory.data["goals"][-1]["agent"] == "researcher"
            assert all(request.url.host in {"127.0.0.1", "localhost"} for request in requests)
            assert len([request for request in requests if request.method == "POST"]) == 3
            for request in requests:
                if request.method == "POST":
                    body = json.loads(request.content)
                    assert body["keep_alive"] == 0 and body["options"]["num_ctx"] == supervisor.cfg.context_tokens
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_turn_exhaustion_cannot_make_an_extra_model_call(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        actions = [{"action": "list_source", "summary": "Inspect source", "arguments": {}} for _ in range(3)]
        requests = await local_model(supervisor, actions)
        try:
            supervisor.run()
            await supervisor._job_task
            assert supervisor._remaining == 0 and len(requests) == 4
            with pytest.raises(ValueError, match="budget"):
                await supervisor._ask("director", [])
            assert len(requests) == 4
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_agent_training_claims_remain_unverified_and_delegation_or_edits_are_restricted(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        try:
            row = await supervisor._tool("curator", "training_example", {"instruction": "Public question", "response": "Agent answer", "verified": True, "rights": "owner_code"})
            assert not row["verified"] and not row["eligible"]
            with pytest.raises(ValueError, match="engineer"):
                await supervisor._tool("researcher", "propose_change", {})
            with pytest.raises(ValueError):
                await supervisor._tool("director", "delegate", {"role": "director", "task": "Loop forever"})
            with pytest.raises(ValueError, match="boolean"):
                await supervisor._tool("director", "browse_files", {"recursive": "yes"})
        finally:
            await supervisor.close()
    asyncio.run(run())


@pytest.mark.parametrize("before,after,review", [
    ({"status": "setup_needed", "error": "No engine"}, {"passed": True}, True),
    ({"status": "failed", "failures": 1, "errors": 1}, {"passed": True}, True),
    ({"status": "passed", "passed": True}, {"passed": True}, True),
    ({"status": "failed", "failures": 1, "errors": 0}, {"passed": False}, True),
    ({"status": "failed", "failures": 1, "errors": 0}, {"passed": True}, False),
    ({"status": "failed", "failures": 1, "errors": 0, "evidence": {"phases": [
        {"name": "baseline", "tests": 1, "failures": 1, "errors": 0, "skipped": 0, "exit_code": 1}]}},
     {"passed": True, "evidence": {"phases": [
        {"name": "baseline", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "exit_code": 0},
        {"name": "additional", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "exit_code": 0}]}}, True)])
def test_failed_repair_infrastructure_or_review_never_promotes(tmp_path, monkeypatch, before, after, review):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        supervisor._active = {"status": "running"}
        supervisor._remaining = 1
        supervisor.sandbox.evaluate = AsyncMock(side_effect=[before, after])
        supervisor.changes.promote = Mock(side_effect=AssertionError("Unsafe promotion"))
        supervisor._ask = AsyncMock(return_value={"passed": review, "reason": "Measured review"})
        source = supervisor.changes.root / "clipbot" / "logic.py"
        from clipbot.supervisor_changes import digest
        args = {"requirement": "Return the corrected value", "regression_test": "def test_requirement(): assert True\n",
                "edits": [{"path": "clipbot/logic.py", "before_sha256": digest(source.read_bytes()), "search": "return 1", "replacement": "return 2"}]}
        try:
            result = await supervisor._change(args)
            assert result["status"] == "held"
            supervisor.changes.promote.assert_not_called()
            assert source.read_bytes() == b"def value(): return 1\n"
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_verified_reproduction_and_independent_review_apply_real_source_change(tmp_path, monkeypatch):
    async def run():
        _, supervisor = context(tmp_path, monkeypatch)
        supervisor._active = {"status": "running"}
        supervisor._remaining = 1
        baseline = {"name": "baseline", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "exit_code": 0}
        reproduced = {"name": "additional", "tests": 1, "failures": 1, "errors": 0, "skipped": 0, "exit_code": 1}
        corrected = {**reproduced, "failures": 0, "exit_code": 0}
        before = {"status": "failed", "passed": False, "tests": 2, "failures": 1, "errors": 0, "error": "",
                  "evidence": {"phases": [baseline, reproduced]}}
        after = {"status": "passed", "passed": True, "tests": 2, "failures": 0, "errors": 0, "error": "",
                 "evidence": {"phases": [baseline, corrected]}}
        supervisor.sandbox.evaluate = AsyncMock(side_effect=[before, after])
        supervisor._ask = AsyncMock(return_value={"passed": True, "reason": "Actual reproduction fails before and passes after"})
        source = supervisor.changes.root / "clipbot" / "logic.py"
        from clipbot.supervisor_changes import digest
        args = {"requirement": "Return the corrected value", "regression_test": "from clipbot.logic import value\ndef test_requirement(): assert value() == 2\n",
                "edits": [{"path": "clipbot/logic.py", "before_sha256": digest(source.read_bytes()), "search": "return 1", "replacement": "return 2"}]}
        try:
            result = await supervisor._change(args)
            assert result["status"] == "source_applied" and result["restart_required"]
            assert source.read_bytes() == b"def value(): return 2\n"
            assert supervisor.memory.data["examples"][-1]["eligible"]
            await supervisor.rollback(result["candidate_id"])
            assert source.read_bytes() == b"def value(): return 1\n"
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_api_inherits_auth_csrf_host_guards_and_master_switch_persists(tmp_path, monkeypatch):
    from clipbot.dashboard.server import create_app
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch, enabled=False)
        app = create_app(ctx)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
                assert (await client.get("/api/supervisor")).status_code == 401
                setup = await client.post("/api/auth/setup", headers={"X-ClipBot": "1"}, json={"name": "Synthetic Owner", "password": "synthetic-password"})
                assert setup.status_code == 200, setup.text
                assert (await client.get("/api/supervisor")).status_code == 200
                assert (await client.post("/api/supervisor/master", json={"enabled": False})).status_code == 403
                assert (await client.get("/api/supervisor", headers={"Host": "evil.example"})).status_code == 403
                stopped = await client.post("/api/supervisor/master", headers={"X-ClipBot": "1"}, json={"enabled": False})
                assert stopped.status_code == 200 and stopped.json()["state"] == "off"
                assert not load_settings(tmp_path / "saved-settings.json").supervisor.enabled
                assert (await client.post("/api/supervisor/run", headers={"X-ClipBot": "1"}, json={})).status_code == 409
                assert (await client.post("/api/supervisor/rollback", headers={"X-ClipBot": "1"}, json={"job_id": "../private"})).status_code == 409
                assert (await client.get("/api/supervisor/dataset/all")).status_code == 400
        finally:
            await supervisor.close()
    asyncio.run(run())


def test_agent_finish_secret_does_not_leak_through_snapshot_or_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from clipbot.supervisor_api import install_supervisor_routes
    async def run():
        ctx, supervisor = context(tmp_path, monkeypatch)
        await local_model(supervisor, [finish("password=synthetic-secret-not-for-dashboard")])
        try:
            supervisor.run("Inspect source only")
            await supervisor._job_task
            app = FastAPI()
            install_supervisor_routes(app, ctx)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-test") as client:
                response = await client.get("/api/supervisor")
                assert response.status_code == 200
                assert "synthetic-secret-not-for-dashboard" not in response.text
            assert "synthetic-secret-not-for-dashboard" not in supervisor.memory.path.read_text()
        finally:
            await supervisor.close()
    asyncio.run(run())
