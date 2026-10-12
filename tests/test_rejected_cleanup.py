"""Rejected cleanup removes owned media, preserves decisions and cannot race production."""
import asyncio
import os
import threading
from pathlib import Path

import httpx
import pytest

from clipbot import sweeper
from clipbot.config import Settings
from clipbot.dashboard.server import create_app
from clipbot.db import Store
from clipbot.models import Stage
from clipbot.pipeline import Pipeline
from clipbot.scheduler import Scheduler
from tests.test_account_profiles import context
from tests.test_scheduler import cand
from tests.test_sweeper import paths_at


def rejected(paths, *, created=0):
    clip = cand(paths.clips, stage=Stage.REJECTED, created=created)
    Path(clip.final_path).unlink()
    clip.final_path = str(paths.clips / f"xqc_{clip.id}.mp4")
    clip.raw_path = str(paths.work / f"{clip.id}_raw.mp4")
    Path(clip.raw_path).write_bytes(b"raw")
    Path(clip.final_path).write_bytes(b"final")
    clip.transcript = "Keep this evidence"
    clip.verdict["reason"] = "A saved decision"
    return clip


def test_owned_rejected_media_is_deleted_but_decisions_other_stages_and_shared_files_survive(tmp_path):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        clip = rejected(paths)
        frames = paths.work / "frames" / clip.id
        frames.mkdir(parents=True)
        (frames / "0.jpg").write_bytes(b"frame")
        (frames / "personal.txt").write_text("preserve")
        rejected_shared = rejected(paths)
        accepted = cand(paths.clips)
        accepted.raw_path = rejected_shared.raw_path
        failed = rejected(paths)
        failed.stage = Stage.FAILED
        buffer = paths.buffer / "twitch_xqc" / "seg_20260101000000.ts"
        buffer.parent.mkdir()
        buffer.write_bytes(b"shared buffer")
        for item in (clip, rejected_shared, accepted, failed):
            store.upsert_candidate(item)
        scheduler = Scheduler(Settings(), store, {}, paths)
        result = await scheduler.delete_rejected_media(manual=True)
        assert result["files_deleted"] == 4 and result["bytes_freed"] == 18
        assert result["files_skipped"] == 1
        saved = store.get_candidate(clip.id)
        assert saved.raw_path == saved.final_path == ""
        assert saved.stage == Stage.REJECTED
        assert saved.transcript == clip.transcript and saved.verdict == clip.verdict
        assert saved.source["rejected_media_cleanup"]["bytes_freed"] == 13
        assert (frames / "personal.txt").exists() and buffer.exists()
        assert Path(rejected_shared.raw_path).exists()
        assert Path(accepted.final_path).exists()
        assert Path(failed.raw_path).exists() and Path(failed.final_path).exists()
        assert len(store.candidate_media_references()) == 4
        assert (await scheduler.delete_rejected_media(manual=True))["files_deleted"] == 0
        store.close()
    asyncio.run(run())


def test_stored_paths_are_not_ownership_and_linked_roots_are_refused(tmp_path, monkeypatch):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        clip = rejected(paths)
        Path(clip.raw_path).unlink()
        Path(clip.final_path).unlink()
        outside = tmp_path / "family.mp4"
        outside.write_bytes(b"personal")
        clip.raw_path = clip.final_path = str(outside)
        store.upsert_candidate(clip)
        scheduler = Scheduler(Settings(), store, {}, paths)
        assert (await scheduler.delete_rejected_media(manual=True))["files_deleted"] == 0
        assert outside.read_bytes() == b"personal"
        linked = rejected(paths)
        store.upsert_candidate(linked)
        original = sweeper._linked
        monkeypatch.setattr(sweeper, "_linked", lambda path: path in (paths.work, paths.clips) or original(path))
        assert (await scheduler.delete_rejected_media(manual=True))["files_deleted"] == 0
        assert Path(linked.raw_path).exists() and Path(linked.final_path).exists()
        store.close()
    asyncio.run(run())


def test_active_processing_edit_upload_and_successful_posts_are_protected(tmp_path):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        items = [rejected(paths) for _ in range(4)]
        items[2].posted_to = {"youtube": "ok"}
        for item in items:
            store.upsert_candidate(item)
        store.record_post(items[3].id, "youtube", "posted", "", "ok")
        scheduler = Scheduler(Settings(), store, {}, paths)
        scheduler.media_in_use = lambda cid: cid == items[0].id
        lock = scheduler.media_locks.setdefault(items[1].id, asyncio.Lock())
        async with lock:
            result = await scheduler.delete_rejected_media(manual=True)
        assert result["files_deleted"] == 0 and result["clips_skipped"] == 4
        assert all(Path(item.raw_path).exists() and Path(item.final_path).exists() for item in items)
        store.close()
    asyncio.run(run())


def test_hardlinked_personal_media_is_preserved_and_not_counted_as_freed(tmp_path):
    paths = paths_at(tmp_path)
    clip = rejected(paths)
    outside = tmp_path / "personal-copy.mp4"
    os.link(clip.raw_path, outside)
    result = sweeper.remove_rejected_media(Settings(), paths, clip, set())
    assert result["files_deleted"] == 1 and result["bytes_freed"] == 5
    assert result["files_skipped"] == 1
    assert Path(clip.raw_path).exists() and outside.read_bytes() == b"raw"


@pytest.mark.parametrize("review_hours", [0, 0.25])
def test_finished_reject_remains_reviewable_until_managed_cleanup_even_without_keep_raw(tmp_path, review_hours):
    async def run():
        paths = paths_at(tmp_path)
        settings = Settings()
        settings.edit.keep_raw = False
        settings.clip.keep_rejected_hours = review_hours
        pipeline = Pipeline(settings, paths)
        clip = rejected(paths)
        concat = paths.work / f"{clip.id}_concat.txt"
        concat.write_text("scratch")
        await pipeline._finish(clip, Stage.REJECTED, "Saved judgement")
        assert Path(clip.raw_path).exists() and not concat.exists()
        assert pipeline.store.get_candidate(clip.id).stage == Stage.REJECTED
        pipeline.store.close()
    asyncio.run(run())


def test_automatic_cleanup_obeys_review_grace_manual_can_remove_fresh_reject(tmp_path, monkeypatch):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        old, fresh = rejected(paths), rejected(paths, created=9999)
        for item in (old, fresh):
            store.upsert_candidate(item)
        monkeypatch.setattr("clipbot.scheduler.time.time", lambda: 10000)
        scheduler = Scheduler(Settings(), store, {}, paths)
        auto = await scheduler.delete_rejected_media()
        assert auto["files_deleted"] == 2 and auto["clips_skipped"] == 1
        assert Path(fresh.raw_path).exists()
        manual = await scheduler.delete_rejected_media(manual=True)
        assert manual["files_deleted"] == 2 and not Path(fresh.raw_path).exists()
        store.close()
    asyncio.run(run())


def test_cleanup_cadence_waits_twenty_minutes_and_can_be_disabled(tmp_path, monkeypatch):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        clip = rejected(paths)
        store.upsert_candidate(clip)
        now = [10000]
        monkeypatch.setattr("clipbot.scheduler.time.time", lambda: now[0])
        scheduler = Scheduler(Settings(), store, {}, paths)
        scheduler._last_cleanup = now[0]
        scheduler.settings.posting.cleanup_interval_s = 86400
        async def finalize():
            return None
        scheduler._finalize_all = finalize
        scheduler.active_platforms = lambda: []
        await scheduler.tick()
        now[0] += 1199
        await scheduler.tick()
        assert Path(clip.raw_path).exists()
        now[0] += 1
        await scheduler.tick()
        assert not Path(clip.raw_path).exists() and scheduler.rejected_cleanup_result["files_deleted"] == 2
        another = rejected(paths)
        store.upsert_candidate(another)
        scheduler.settings.clip.rejected_cleanup_min = 0
        now[0] += 1200
        await scheduler.tick()
        assert Path(another.raw_path).exists()
        store.close()
    asyncio.run(run())


def test_cancelled_cleanup_retains_media_lock_until_file_worker_stops(tmp_path, monkeypatch):
    async def run():
        paths = paths_at(tmp_path)
        store = Store(paths.db)
        clip = rejected(paths)
        store.upsert_candidate(clip)
        entered, release = threading.Event(), threading.Event()
        original = sweeper.remove_rejected_media
        def blocked(*args):
            entered.set()
            assert release.wait(5)
            return original(*args)
        monkeypatch.setattr("clipbot.scheduler.remove_rejected_media", blocked)
        scheduler = Scheduler(Settings(), store, {}, paths)
        task = asyncio.create_task(scheduler.delete_rejected_media(manual=True))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert scheduler.media_locks[clip.id].locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not scheduler.media_locks[clip.id].locked()
        store.close()
    asyncio.run(run())


def test_cleanup_endpoint_requires_owner_auth_and_explicit_confirmation(tmp_path):
    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, _ = context(tmp_path, engine)
            paths = paths_at(tmp_path)
            store = Store(paths.db)
            clip = rejected(paths)
            store.upsert_candidate(clip)
            ctx.pipeline.store = store
            ctx.pipeline.scheduler = Scheduler(ctx.settings, store, {}, paths)
            transport = httpx.ASGITransport(app=create_app(ctx))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as client:
                route = "/api/clips/rejected/delete-media"
                body = {"confirm": "delete-rejected-media"}
                headers = {"X-ClipBot": "1"}
                assert (await client.post(route, headers=headers, json=body)).status_code == 401
                setup = await client.post("/api/auth/setup", headers=headers, json={"name": "Owner", "password": "test-password"})
                assert setup.status_code == 200, setup.text
                assert (await client.post(route, headers=headers, json={})).status_code == 400
                assert Path(clip.raw_path).exists()
                response = await client.post(route, headers=headers, json=body)
                assert response.status_code == 200, response.text
                assert response.json()["files_deleted"] == 2 and response.json()["bytes_freed"] == 8
                assert store.get_candidate(clip.id).transcript == clip.transcript
            store.close()
    asyncio.run(run())
