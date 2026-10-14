"""Lifecycle boundaries: correct local service, owned child cleanup and bounded I/O."""
import asyncio
import json
from functools import wraps
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from clipbot import story_visual_service as module
from clipbot import util


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def settings(tmp_path):
    root = tmp_path / "comfy"
    root.mkdir()
    (root / "main.py").write_text("# existing ComfyUI entry point", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()
    cfg = SimpleNamespace(comfy_url="http://127.0.0.1:8190", comfy_autostart=True,
                          comfy_root=str(root), comfy_python=sys.executable, comfy_models_root=str(models),
                          comfy_motion_models_root="",
                          comfy_startup_timeout_s=0.2, comfy_probe_timeout_s=0.1,
                          comfy_startup_poll_s=0.01, comfy_log_max_bytes=4096, comfy_metadata_max_bytes=4096)
    return SimpleNamespace(stories=cfg, app=SimpleNamespace(shutdown_timeout_s=1))


def stats():
    return {"system": {"comfyui_version": "test-core"},
            "devices": [{"name": "Test GPU", "type": "cuda", "vram_total": 1024}]}


@run_async
async def test_existing_verified_service_is_never_owned_or_stopped(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg.stories.comfy_autostart = False
    cfg.stories.comfy_root = cfg.stories.comfy_python = cfg.stories.comfy_models_root = ""
    async def forbidden(*args, **kwargs):
        pytest.fail("An external verified service must not be launched or terminated")
    monkeypatch.setattr(module, "spawn", forbidden)
    monkeypatch.setattr(module, "terminate", forbidden)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=stats()))) as http:
        service = module.StoryVisualService()
        await service.ensure(cfg, http)
        await service.stop(cfg)
    assert not (tmp_path / "models" / ".hollow-runtime").exists()


@run_async
@pytest.mark.parametrize("body", [{"status": "ready"}, {"system": {"comfyui_version": "x"}, "devices": []},
                                {"system": {"comfyui_version": "x"}, "devices": [{"name": "GPU", "type": "cuda", "vram_total": True}]}])
async def test_wrong_service_on_dedicated_port_does_not_spawn(tmp_path, monkeypatch, body):
    cfg = settings(tmp_path)
    async def forbidden(*args, **kwargs):
        pytest.fail("Do not launch over an unrelated service")
    monkeypatch.setattr(module, "spawn", forbidden)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))) as http:
        with pytest.raises(ValueError, match="verified ComfyUI"):
            await module.StoryVisualService().ensure(cfg, http)


@run_async
@pytest.mark.parametrize("url", ["http://example.com:8190", "http://192.168.0.72:8190", "http://127.0.0.1",
                               "http://user:password@127.0.0.1:8190", "https://127.0.0.1:8190", "http://127.0.0.1:8190/base"])
async def test_only_explicit_literal_loopback_endpoint_is_managed(tmp_path, url):
    cfg = settings(tmp_path)
    cfg.stories.comfy_url = url
    with pytest.raises(ValueError):
        await module.StoryVisualService().ensure(cfg, None)


@run_async
async def test_health_response_bound_and_redirect_rejection(tmp_path):
    cfg = settings(tmp_path)
    service = module.StoryVisualService()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b" " * 8192))) as http:
        with pytest.raises(ValueError, match="metadata limit"):
            await service.ensure(cfg, http)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={"Location": "https://example.com"}))) as http:
        with pytest.raises(ValueError, match="not a ready ComfyUI"):
            await service.ensure(cfg, http)


class FakeChild:
    def __init__(self):
        self.returncode = None
        self.stdout = asyncio.StreamReader()


@run_async
@pytest.mark.parametrize("separate_motion", [False, True])
async def test_spawn_uses_isolated_paths_and_only_stops_owned_child(tmp_path, monkeypatch, separate_motion):
    cfg = settings(tmp_path)
    if separate_motion:
        motion_root = tmp_path / "motion-models"
        motion_root.mkdir()
        cfg.stories.comfy_motion_models_root = str(motion_root)
    child = FakeChild()
    calls = []
    ready = False
    async def launch(*args, **kwargs):
        nonlocal ready
        calls.append((args, kwargs))
        ready = True
        return child
    async def terminate(proc, grace):
        assert proc is child
        proc.returncode = 0
        proc.stdout.feed_eof()
    def health(req):
        if not ready:
            raise httpx.ConnectError("not running", request=req)
        return httpx.Response(200, json=stats())
    monkeypatch.setattr(module, "spawn", launch)
    monkeypatch.setattr(module, "terminate", terminate)
    async with httpx.AsyncClient(transport=httpx.MockTransport(health)) as http:
        service = module.StoryVisualService()
        await service.ensure(cfg, http)
        await service.ensure(cfg, http)
        assert len(calls) == 1
        args, kwargs = calls[0]
        runtime = Path(cfg.stories.comfy_models_root) / ".hollow-runtime"
        assert "--disable-all-custom-nodes" in args and "--disable-api-nodes" in args
        assert args[args.index("--listen") + 1] == "127.0.0.1"
        assert args[args.index("--port") + 1] == "8190"
        database = args[args.index("--database-url") + 1]
        assert database.startswith("sqlite:///")
        assert Path(database.removeprefix("sqlite:///")).is_relative_to(runtime)
        for flag in ("--base-directory", "--input-directory", "--output-directory", "--temp-directory", "--user-directory"):
            assert Path(args[args.index(flag) + 1]).is_relative_to(runtime)
        assert kwargs["cwd"] == str(runtime)
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        yaml = (runtime / "extra_model_paths.yaml").read_text()
        assert "base_path: " + json.dumps(cfg.stories.comfy_models_root) in yaml
        assert "diffusion_models: diffusion_models" in yaml and "text_encoders: text_encoders" in yaml
        if separate_motion:
            assert "hollow_motion:" in yaml and "base_path: " + json.dumps(str(motion_root)) in yaml
        await service.stop(cfg)
        assert child.returncode == 0 and service._proc is None and service._log_task is None


@run_async
async def test_cancelled_startup_cleans_child_and_log_reader(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    child, started = FakeChild(), asyncio.Event()
    async def launch(*args, **kwargs):
        started.set()
        return child
    async def terminate(proc, grace):
        proc.returncode = -1
        proc.stdout.feed_eof()
    async def unavailable(*args):
        return False
    monkeypatch.setattr(module, "spawn", launch)
    monkeypatch.setattr(module, "terminate", terminate)
    service = module.StoryVisualService()
    monkeypatch.setattr(service, "_healthy", unavailable)
    task = asyncio.create_task(service.ensure(cfg, None))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.returncode == -1 and service._proc is None and service._log_task is None


@run_async
async def test_startup_deadline_terminates_real_owned_child(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg.stories.comfy_startup_timeout_s = 0.1
    children = []
    async def launch(*args, **kwargs):
        child = await util.spawn(sys.executable, "-u", "-c", "import time; print('owned test child', flush=True); time.sleep(60)",
                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        children.append(child)
        return child
    async def unavailable(*args):
        return False
    monkeypatch.setattr(module, "spawn", launch)
    service = module.StoryVisualService()
    monkeypatch.setattr(service, "_healthy", unavailable)
    try:
        with pytest.raises(ValueError, match="deadline"):
            await service.ensure(cfg, None)
        assert len(children) == 1 and children[0].returncode is not None
        assert service._proc is None and service._log_task is None
    finally:
        for child in children:
            await util.terminate(child, 1)


@run_async
async def test_log_stays_bounded(tmp_path):
    child = FakeChild()
    log = tmp_path / "comfyui.log"
    child.stdout.feed_data(b"a" * 10000)
    child.stdout.feed_eof()
    await module.StoryVisualService()._drain_log(child, log, 4096)
    assert 0 < log.stat().st_size <= 4096


@run_async
async def test_relative_installation_rejected_before_spawn(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg.stories.comfy_root = "relative/comfy"
    service = module.StoryVisualService()
    async def unavailable(*args):
        return False
    monkeypatch.setattr(service, "_healthy", unavailable)
    with pytest.raises(ValueError, match="absolute"):
        await service.ensure(cfg, None)
    assert service._proc is None
