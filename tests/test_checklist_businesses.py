"""Readiness must distinguish installed tools, active work and stopped businesses."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from clipbot.config import Settings
from clipbot.checklist import run_checklist


def setup(settings, *, reaper_health="verified", gpu_busy=False):
    lock = asyncio.Lock()
    async def native(method, route):
        assert method == "GET"
        return ({"ready": True, "message": "Local engine inspected"} if route == "/api/status" else
                {"ready": reaper_health != "blocked", "installed": True,
                 "native_health": {"status": reaper_health, "message": "Native " + reaper_health}})
    story = SimpleNamespace(_gpu_lock=lock, _model=lambda s:s.ai.vision_model,
                            _capabilities=lambda:{"narrator_available":True,"narrator_label":"Installed local voice",
                                                  "visual_provider":{"available":True,"label":"Local theatre"}})
    pipeline = SimpleNamespace(stories=story, gpu=None, blocked="", business_state=lambda business:
                               {"running":True,"busy":False,"message":"Running"})
    ctx = SimpleNamespace(pipeline=pipeline,music_bridge=SimpleNamespace(call=AsyncMock(side_effect=native),producer=None))
    return ctx,lock


def run(settings, monkeypatch, *, status=200, reaper_health="verified", gpu_busy=False):
    monkeypatch.setattr("clipbot.checklist._runs", AsyncMock(return_value=(True,"Available")))
    async def check():
        ctx,lock=setup(settings,reaper_health=reaper_health)
        if gpu_busy:
            await lock.acquire()
        response=httpx.Response(status,json={"models":[{"name":settings.ai.vision_model}]},request=httpx.Request("GET","http://localhost/api/tags"))
        result=await run_checklist(settings,SimpleNamespace(get=AsyncMock(return_value=response)),ctx)
        assert all(call.args[0]=="GET" for call in ctx.music_bridge.call.await_args_list)
        return result
    return asyncio.run(check())


def stopped_settings():
    settings=Settings()
    settings.businesses.surge_enabled=False
    settings.businesses.hollow_enabled=False
    return settings


def test_stopped_businesses_are_not_missing_requirements(monkeypatch):
    result=run(stopped_settings(),monkeypatch,status=503,reaper_health="blocked")
    assert result["ok"]
    assert len(result["businesses"])==4
    assert all(group["status"]=="stopped" for group in result["businesses"])
    assert not any(item["required"] for item in result["items"])
    assert {"ffmpeg","ffprobe","ollama","twitch","kick","posting"} <= {item["id"] for item in result["items"]}


def test_checks_active_surge_model_not_unused_configured_judge(monkeypatch):
    settings=stopped_settings();settings.businesses.surge_enabled=True
    settings.twitch.client_id="fixture";settings.twitch.client_secret="fixture"
    settings.ai.model="unused-not-installed";settings.ai.judge_profile="balanced"
    result=run(settings,monkeypatch)
    assert result["ok"]
    assert next(group for group in result["businesses"] if group["id"]=="clips")["ready"]


def test_reaper_executable_never_overrides_blocked_native_audio(monkeypatch):
    settings=stopped_settings();settings.businesses.resonance_enabled=True
    result=run(settings,monkeypatch,reaper_health="blocked")
    group=next(group for group in result["businesses"] if group["id"]=="music")
    checks={item["id"]:item for item in group["items"]}
    assert checks["music_reaper_installed"]["ok"]
    assert not checks["music_reaper_native"]["ok"]
    assert group["status"]=="blocked" and not result["ok"]


def test_unverified_native_audio_stays_unverified(monkeypatch):
    settings=stopped_settings();settings.businesses.resonance_enabled=True
    result=run(settings,monkeypatch,reaper_health="unverified")
    assert not next(item for item in result["items"] if item["id"]=="music_reaper_native")["ok"]


def test_shared_gpu_in_use_does_not_claim_all_businesses_ready(monkeypatch):
    settings=stopped_settings();settings.businesses.hollow_enabled=True
    result=run(settings,monkeypatch,gpu_busy=True)
    group=next(group for group in result["businesses"] if group["id"]=="stories")
    assert result["shared"]["gpu_busy"] and group["status"]=="busy" and not group["ready"]
    assert result["ok"]  # Busy is not an installation failure.


def test_ollama_error_response_is_not_healthy(monkeypatch):
    settings=stopped_settings();settings.businesses.hollow_enabled=True
    result=run(settings,monkeypatch,status=503)
    assert not next(item for item in result["items"] if item["id"]=="ollama")["ok"]
    assert not result["ok"]


def test_native_edit_without_measured_audio_does_not_verify_export(monkeypatch):
    settings=stopped_settings();settings.businesses.resonance_enabled=True
    result=run(settings,monkeypatch,reaper_health="verified")
    checks={item["id"]:item for item in result["items"]}
    assert checks["music_reaper_native"]["ok"]
    assert not checks["music_reaper_audio"]["ok"]
    assert not result["ok"]
