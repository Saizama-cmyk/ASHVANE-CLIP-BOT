"""Timing regressions: bounded probes/queues and honest local capture freshness."""
import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from clipbot.capture import Capture, streamlink_args
from clipbot.config import Settings, resolve_paths
from clipbot.detector import Detector
from clipbot.models import Candidate, Platform, SpikeEvent, Stage, StreamTarget
from clipbot.pipeline import Limiter, Pipeline
from clipbot.transcribe import Transcriber


def target(platform=Platform.TWITCH, login="sample"):
    return StreamTarget(platform, login, login, "Art", 1)


def candidate():
    event = SpikeEvent(target(), time.time(), "chat", 1, 1, 1)
    return Candidate(event.id, event, "", event.t_wall - 1, event.t_wall + 1)


@pytest.fixture
def pipeline(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    settings.workers.transcribers = 1
    result = Pipeline(settings, resolve_paths(settings))
    yield result
    result.store.close()


def test_streamlink_transport_settings_and_platform_prefetch_are_explicit():
    settings = Settings()
    settings.capture.hls_live_edge = 4
    settings.capture.hls_segment_threads = 3
    settings.capture.stream_timeout_s = 27
    args = streamlink_args(settings, target())
    assert args[args.index("--hls-live-edge") + 1] == "4"
    assert args[args.index("--stream-segment-threads") + 1] == "3"
    assert float(args[args.index("--stream-timeout") + 1]) == 27
    assert "--hls-segment-stream-data" in args
    assert "--twitch-low-latency" not in args
    settings.capture.twitch_low_latency = True
    settings.capture.kick_low_latency = True
    settings.capture.hls_segment_stream_data = False
    tw = streamlink_args(settings, target())
    kick = streamlink_args(settings, target(Platform.KICK))
    assert "--twitch-low-latency" in tw and "--kick-low-latency" not in tw
    assert "--kick-low-latency" in kick and "--twitch-low-latency" not in kick
    assert "--hls-segment-stream-data" not in kick
    assert tw[-2:] == [target().url, settings.capture.quality]


def test_audio_probe_uses_segment_end_and_reports_no_provider_latency(tmp_path, monkeypatch):
    import clipbot.capture as module
    cap = Capture(target(), Settings(), tmp_path, None)
    cap.folder.mkdir()
    base = int(time.time()) - 30
    for offset in (0, 6, 12):
        file = cap.folder / time.strftime("seg_%Y%m%d%H%M%S.ts", time.localtime(base + offset))
        file.write_bytes(b"x")
        os.utime(file, (base + offset + 6, base + offset + 6))
    monkeypatch.setattr(module, "ffmpeg_exe", lambda _s: "ffmpeg")

    async def level(*_args):
        return -10.0
    monkeypatch.setattr(module, "mean_volume_db", level)
    result = asyncio.run(cap.latest_audio_level())
    assert result[1] == -10.0 and cap.audio_sample_wall == base + 12
    snapshot = cap.snapshot()
    assert snapshot["audio_sample_age_s"] >= 18
    assert snapshot["complete_segment_age_s"] >= 18
    assert snapshot["source_latency_s"] is None
    assert snapshot["audio_probe_s"] >= 0


def test_parallel_audio_probe_slow_stream_does_not_block_fast_and_cancellation_drains(pipeline):
    async def run():
        pipeline.settings.capture.audio_probe_workers = 2
        blocked, fast, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        active = 0
        peak = 0

        class Probe:
            audio_sample_wall = 123.0

            def __init__(self, slow=False):
                self.slow = slow

            async def latest_audio_level(self):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    if self.slow:
                        blocked.set()
                        await release.wait()
                    else:
                        fast.set()
                    return "seg", -10.0
                finally:
                    active -= 1

        caps = {"slow": Probe(True), "fast": Probe(), "also-fast": Probe()}
        pipeline.captures = SimpleNamespace(captures=caps, get=caps.get)
        observed = []
        pipeline.detector.add_audio = lambda *args: observed.append(args)
        poll = asyncio.create_task(pipeline._poll_audio())
        await asyncio.wait_for(blocked.wait(), 1)
        await asyncio.wait_for(fast.wait(), 1)
        await asyncio.sleep(0)
        assert peak == 2 and observed and all(item[-1] == 123.0 for item in observed)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        assert active == 0
    asyncio.run(run())


def test_stale_or_future_audio_cannot_be_refreshed_by_late_evaluation():
    settings = Settings()
    detector = Detector(settings.detector)
    stream = target()
    for index in range(settings.detector.audio_min_samples):
        detector.add_audio(stream.key, -30.0, index)
    detector.add_audio(stream.key, -5.0, 20)
    assert detector.evaluate(stream, 20 + settings.detector.window_s + 1) is None
    detector.add_audio(stream.key, 100.0, 100)
    assert detector.evaluate(stream, 50) is None
    event = detector.evaluate(stream, 101)
    assert event is not None and event.kind == "audio" and event.t_wall == 100


def test_worker_queue_wait_obeys_existing_cut_lifetime_and_frees_slot(pipeline):
    async def run():
        clip = candidate()
        clip.created_at = time.time() - pipeline.settings.clip.abandon_after_h * 3600 + 0.03
        limiter = Limiter(1)
        async with limiter:
            with pytest.raises(RuntimeError, match="lifetime waiting for ai"):
                async with pipeline._candidate_slot(clip, limiter, "ai"):
                    pytest.fail("Expired queue item acquired a worker")
            assert limiter.active == 1
        assert limiter.active == 0
        assert pipeline._latency[clip.id]["stages_s"]["ai_wait"] >= 0
        clip.created_at = time.time()
        async with pipeline._candidate_slot(clip, limiter, "ai"):
            assert limiter.active == 1
        assert limiter.active == 0
    asyncio.run(run())


@pytest.mark.parametrize("stage", [Stage.CLIPABILITY, Stage.EDIT])
def test_recovered_transcript_is_not_decoded_again(pipeline, tmp_path, monkeypatch, stage):
    import clipbot.pipeline as module
    clip = candidate()
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"raw")
    clip.raw_path = str(raw)
    clip.stage = stage
    clip.transcript = "An already saved transcript"

    async def qc(*_args):
        return SimpleNamespace(ok=True, duration=2, reason="")

    async def forbidden(*_args):
        pytest.fail("Saved transcript should be reused after restart")

    async def think(item, _duration):
        assert item.transcript == clip.transcript
        item.verdict = {"passed": False}

    monkeypatch.setattr(module, "quality_check", qc)
    monkeypatch.setattr(module, "looks_like_dead_air", lambda *_a: False)
    monkeypatch.setattr(pipeline.transcriber, "transcribe", forbidden)
    monkeypatch.setattr(pipeline, "_think", think)
    asyncio.run(pipeline._run_candidate(clip))
    assert "transcribe_including_wait" not in pipeline._latency[clip.id]["stages_s"]


def test_latency_diagnostics_are_bounded_and_distinguish_active_from_recent(pipeline):
    async def run():
        pipeline.settings.dashboard.samples_limit = 10
        for _ in range(15):
            clip = candidate()
            async with pipeline._measure(clip, "ai_wait"):
                pass
            pipeline._done(clip.id)
        active = candidate()
        async with pipeline._measure(active, "qc"):
            snapshot = pipeline.latency_snapshot()
            assert snapshot["active_jobs"][0]["phase"] == "qc"
        assert len(snapshot["recent_jobs"]) == 10
        assert snapshot["source_latency_available"] is False
        assert snapshot["ai_slots"] == {"active": 0, "limit": pipeline.settings.workers.ai_stage}
    asyncio.run(run())


def test_transcriber_deadline_expires_in_queue_without_starting_native_inference(tmp_path):
    async def run():
        settings = Settings()
        settings.workers.transcribers = 1
        transcriber = Transcriber(settings)
        called = []
        transcriber._transcribe_sync = lambda _path: called.append(True)
        await transcriber._sem.acquire()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await transcriber.transcribe(tmp_path / "source.mp4", deadline=time.time() + 0.02,
                                              on_slot=lambda: called.append("slot"))
            assert transcriber.jobs == 0 and called == []
        finally:
            transcriber._sem.release()
        await transcriber.transcribe(tmp_path / "source.mp4", deadline=time.time() + 1,
                                      on_slot=lambda: called.append("slot"))
        assert called == ["slot", True] and transcriber.jobs == 0
    asyncio.run(run())


def test_transcription_metrics_split_queue_wait_and_native_work_and_drain_cancel(pipeline, tmp_path):
    async def run():
        clip = candidate()
        clip.raw_path = str(tmp_path / "source.mp4")
        entered, release = threading.Event(), threading.Event()

        def decode(_path):
            entered.set()
            assert release.wait(5)
            return "done"

        pipeline.transcriber._transcribe_sync = decode
        await pipeline.transcriber._sem.acquire()
        task = asyncio.create_task(pipeline._transcribe_candidate(clip))
        await asyncio.sleep(0)
        assert pipeline.latency_snapshot()["active_jobs"][0]["phase"] == "transcribe_wait"
        pipeline.transcriber._sem.release()
        assert await asyncio.to_thread(entered.wait, 1)
        assert pipeline.latency_snapshot()["active_jobs"][0]["phase"] == "transcribe"
        task.cancel()
        await asyncio.sleep(0)
        assert pipeline.transcriber.jobs == 1 and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        durations = pipeline._latency[clip.id]["stages_s"]
        assert durations["transcribe_wait"] >= 0 and durations["transcribe"] >= 0
        assert durations["transcribe_including_wait"] >= durations["transcribe"]
        assert pipeline.transcriber.jobs == 0
    asyncio.run(run())


def test_business_resume_preserves_old_job_age_but_renews_active_queue_lifetime(pipeline):
    async def run():
        clip = candidate()
        clip.created_at = time.time() - 3600
        old_age = clip.created_at

        async def kept(_clip):
            await asyncio.Event().wait()

        async def nothing():
            return None

        pipeline._run_candidate = kept
        pipeline._sync_capture_pause = nothing
        pipeline._launch(clip, resumed=True)
        assert clip.created_at == old_age
        assert pipeline._candidate_deadline(clip) > time.time()
        task = pipeline._inflight[clip.id]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert clip.id not in pipeline._queue_deadlines
    asyncio.run(run())
