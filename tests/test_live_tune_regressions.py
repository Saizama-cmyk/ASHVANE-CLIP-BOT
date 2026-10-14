"""Isolated live-buffer, browser lifecycle and hardware-tuning regressions."""
import asyncio
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from clipbot.capture import Capture, Segment
from clipbot.config import Settings
from clipbot.dashboard.server import create_app
from clipbot.hardware import Hardware, recommend
from clipbot.models import Platform, StreamTarget
from tests.test_account_profiles import context

H = {"X-ClipBot": "1"}


def test_watch_reads_cached_complete_segments_without_storage_and_stays_private(tmp_path, monkeypatch):
    import clipbot.capture as capture_module

    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, _ = context(tmp_path, engine)
            target = StreamTarget(Platform.TWITCH, "fixture", "Fixture", "Art", 1)
            cap = Capture(target, ctx.settings, tmp_path, None)
            complete = Segment(cap.folder / "seg_20261013120000.ts", 100, 106)
            monkeypatch.setattr(capture_module, "_scan_segments", lambda _: ([complete], 106))
            cap.segments()
            monkeypatch.setattr(cap, "read_segments", lambda: pytest.fail("viewer scanned storage"))
            ctx.pipeline.captures = {target.key: cap}
            ctx.pipeline.targets = {target.key: target}
            ctx.pipeline.detector = SimpleNamespace(stats=lambda _: {}, recent_chat=lambda *_: [])
            ctx.pipeline.store = SimpleNamespace(recent_candidates=lambda _: [])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(ctx)), base_url="http://127.0.0.1:8787") as client:
                assert (await client.get(f"/api/watch/{target.key}")).status_code == 401
                assert (await client.get(f"/media/live/{target.key}/{complete.path.stem}.mp4")).status_code == 401
                await client.post("/api/auth/setup", headers=H, json={"name": "Owner", "password": "fixture-password"})
                response = await client.get(f"/api/watch/{target.key}")
                assert response.status_code == 200
                body = response.json()
                assert body["segments"] == [{"name": complete.path.stem, "start": 100, "end": 106}]
                assert body["buffer"]["available"] is True
                cap._reset_observation()
                body = (await client.get(f"/api/watch/{target.key}")).json()
                assert body["segments"] == [] and body["buffer"]["available"] is False
                assert (await client.get(f"/api/watch/{target.key}", headers={"Host": "foreign.example"})).status_code == 403
                assert (await client.get("/api/watch/twitch:missing")).status_code == 404
    asyncio.run(run())


def test_clear_or_newer_scan_cannot_be_replaced_by_old_segments(tmp_path, monkeypatch):
    import clipbot.capture as module
    cap = Capture(StreamTarget(Platform.TWITCH, "fixture", "Fixture", "Art", 1), Settings(), tmp_path, None)
    entered, release = threading.Event(), threading.Event()
    old = Segment(tmp_path / "old.ts", 0, 6)
    fresh = Segment(tmp_path / "fresh.ts", 6, 12)

    def scan(_):
        if not entered.is_set():
            entered.set()
            assert release.wait(2)
            return [old], 6
        return [fresh], 12

    monkeypatch.setattr(module, "_scan_segments", scan)
    async def run():
        pending = asyncio.create_task(asyncio.to_thread(cap.segments))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            cap._reset_observation()
            assert cap.cached_segments == () and cap.snapshot()["metadata_available"] is False
            cap.segments()
        finally:
            release.set()
            await pending
        assert cap.cached_segments == (fresh,)
        assert isinstance(cap.cached_segments, tuple)
    asyncio.run(run())


def test_scan_recommendations_survive_unrelated_setup_and_apply_validates(tmp_path, monkeypatch):
    import clipbot.dashboard.server as module
    hardware = Hardware(16, 32, "Fixture GPU", 12, True, 200, 100, "cuda")
    async def detect(*_):
        return hardware
    async def unrelated_setup(*_):
        pytest.fail("hardware scan waited on unrelated business readiness")
    monkeypatch.setattr(module, "detect", detect)
    monkeypatch.setattr(module, "run_checklist", unrelated_setup)

    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, _ = context(tmp_path, engine)
            ctx.pipeline.http = engine
            ctx.pipeline.transcriber = SimpleNamespace(status="cuda")
            original_commit = ctx.commit_settings
            async def commit(new):
                await original_commit(new)
                return []
            ctx.commit_settings = commit
            async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(ctx)), base_url="http://127.0.0.1:8787") as client:
                assert (await client.post("/api/system/scan", headers=H)).status_code == 401
                await client.post("/api/auth/setup", headers=H, json={"name": "Owner", "password": "fixture-password"})
                assert (await client.post("/api/system/scan")).status_code == 403
                scanned = await client.post("/api/system/scan", headers=H, json={"network": False})
                assert scanned.status_code == 200
                recs = scanned.json()["recommendations"]
                assert recs == recommend(hardware, ctx.settings)
                chosen = next(row for row in recs if row["field"] == "edit.encoder")
                applied = await client.post("/api/system/apply", headers=H, json={"apply": [chosen]})
                assert applied.status_code == 200 and applied.json()["ok"] is True
                assert ctx.settings.edit.encoder == "h264_nvenc"
                for bad in ({"apply": {}}, {"apply": [None]}, {"apply": [{"field": "bad", "value": 1}]}, {"apply": [{"field": "accounts.discord_webhook", "value": "secret"}]}):
                    assert (await client.post("/api/system/apply", headers=H, json=bad)).status_code == 422
    asyncio.run(run())


def test_concurrent_remux_requests_do_not_share_partial_output(tmp_path, monkeypatch):
    import clipbot.media as module
    outputs = []
    async def command(args, _timeout):
        out = Path(args[-1])
        outputs.append(out)
        while len(outputs) < 2:
            await asyncio.sleep(0)
        out.write_bytes(b"fixture-mp4")
        return SimpleNamespace(returncode=0, err_text="")
    monkeypatch.setattr(module, "ffmpeg_exe", lambda _: "fixture-ffmpeg")
    monkeypatch.setattr(module, "run_cmd", command)
    async def run():
        source = tmp_path / "seg_20261013120000.ts"
        results = await asyncio.gather(*(module.remux_segment(source, tmp_path / "cache", Settings()) for _ in range(2)))
        assert outputs[0] != outputs[1]
        assert results[0] == results[1] and results[0].read_bytes() == b"fixture-mp4"
        assert not list((tmp_path / "cache").glob("*.tmp.mp4"))
    asyncio.run(run())


def test_real_remux_has_decodable_av_and_fragmented_mp4(tmp_path, ffmpeg, lavfi_clip):
    from clipbot.media import remux_segment
    source = tmp_path / "seg_20261013120000.ts"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(lavfi_clip), "-c", "copy", "-f", "mpegts", str(source)], check=True, timeout=30)
    settings = Settings()
    settings.paths.ffmpeg = ffmpeg
    out = asyncio.run(remux_segment(source, tmp_path / "cache", settings))
    assert out and b"moof" in out.read_bytes()
    result = subprocess.run([ffmpeg, "-v", "error", "-i", str(out), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_browser_controller_reopening_old_requests_and_official_player():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable for browser controller regression")
    script = Path(__file__).resolve().parent.parent / "scripts" / "verify_live_tune_controllers.cjs"
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
