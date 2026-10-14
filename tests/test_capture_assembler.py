"""Segment timing, cut planning, and a real ffmpeg cut + QC from a synthetic buffer."""
import asyncio
import os
import subprocess
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clipbot.assembler import AssembleError, assemble, parse_qc, plan_cut, quality_check
from clipbot.capture import Capture, Segment, contiguous_run, list_segments, parse_segment_time
from clipbot.config import Settings, merge_incoming
from clipbot.models import Platform, SpikeEvent, StreamTarget


def seg_name(t: float) -> str:
    return time.strftime("seg_%Y%m%d%H%M%S.ts", time.localtime(t))


def test_segment_time_roundtrip_local_tz():
    t = float(int(time.time()))
    assert parse_segment_time(seg_name(t)) == t
    assert parse_segment_time("other.ts") is None


def test_list_segments_needs_successor_and_detects_gaps(tmp_path):
    base = float(int(time.time())) - 100
    for off in (0, 6, 12, 40):            # restart between 12 and 40
        p = tmp_path / seg_name(base + off)
        p.write_bytes(b"x")
        end_write = base + off + 6
        os.utime(p, (end_write, end_write))
    segs = list_segments(tmp_path)
    assert [round(s.start - base) for s in segs] == [0, 6, 12]    # newest has no successor
    assert round(segs[-1].end - base) == 18                       # capped by its own last write
    run = contiguous_run(segs, base + 8, 6)
    assert len(run) == 3


def test_plan_cut_clamps_to_buffer():
    segs = [Segment(Path(f"{i}.ts"), 100.0 + i * 6, 106.0 + i * 6) for i in range(10)]
    used, offset, dur, t0 = plan_cut(segs, 130.0, 25, 12, 6)
    assert t0 == 105.0 and dur == pytest.approx(37.0) and offset == pytest.approx(5.0)
    assert used[0].start == 100.0
    with pytest.raises(AssembleError):
        plan_cut([], 130.0, 25, 12, 6)


def test_parse_qc():
    err = ("Duration: 00:00:37.04, start\n Stream #0:0(und): Video: h264\n Stream #0:1: Audio: aac\n"
           "black_start:0 black_end:2 black_duration:2\nmean_volume: -21.5 dB\n")
    assert parse_qc(err) == (37.04, 2.0, -21.5, True, True)


@pytest.fixture
def buffer(tmp_path, ffmpeg):
    """Write a real 36 s segmented buffer whose file names are wall-clock times."""
    folder = tmp_path / "buffer" / "twitch_tester"
    folder.mkdir(parents=True)
    src = tmp_path / "long.ts"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=30:duration=36", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=36", "-shortest", "-c:v", "libx264", "-g", "30",
                    "-preset", "ultrafast", "-c:a", "aac", "-f", "mpegts", str(src)], check=True)
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-c", "copy", "-f", "segment",
                    "-segment_time", "6", "-reset_timestamps", "1", str(folder / "part%02d.ts")],
                   check=True)
    base = float(int(time.time())) - 60
    parts = sorted(folder.glob("part*.ts"))
    for i, p in enumerate(parts):
        t = base + i * 6
        target = folder / seg_name(t)
        p.rename(target)
        os.utime(target, (t + 6, t + 6))
    return folder, base, len(parts)


def test_assemble_and_qc_real(buffer, tmp_path):
    folder, base, n = buffer
    s = merge_incoming(Settings(), {"clip": {"pre_s": 10, "post_s": 5, "segment_wait_s": 5},
                                    "capture": {"segment_s": 6}})
    t = StreamTarget(Platform.TWITCH, "tester", "Tester", "Art", 5)
    cap = Capture(t, s, tmp_path / "buffer", None)
    assert cap.folder == folder
    ev = SpikeEvent(target=t, t_wall=base + 20, kind="chat", score=1, chat_rate=1, baseline=1)
    c = asyncio.run(assemble(ev, cap, s, tmp_path / "work"))
    assert Path(c.raw_path).exists()
    assert c.end_wall - c.start_wall == pytest.approx(15, abs=0.01)
    qc = asyncio.run(quality_check(Path(c.raw_path), 15, s))
    assert qc.ok, qc.reason
    assert qc.has_audio and qc.has_video and abs(qc.duration - 15) < 1


def test_qc_rejects_silence_and_black(tmp_path, ffmpeg):
    silent = tmp_path / "silent.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=5",
                    "-f", "lavfi", "-i", "anullsrc=d=5", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    str(silent)], check=True)
    qc = asyncio.run(quality_check(silent, 5, Settings()))
    assert not qc.ok and ("black" in qc.reason or "silent" in qc.reason)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_clip_disk_operations_do_not_block_dashboard_loop(tmp_path, monkeypatch, outcome):
    """Regression for a live engine stuck in work_dir.mkdir on slow capture storage."""
    import clipbot.assembler as module
    segment = tmp_path / "segment.ts"
    segment.write_bytes(b"captured")
    target = StreamTarget(Platform.TWITCH, "fixture", "Fixture", "Art", 1)
    event = SpikeEvent(target, 103, "chat", 1, 1, 1)
    settings = merge_incoming(Settings(), {"clip": {"pre_s": 3, "post_s": 3}})
    monkeypatch.setattr(module, "ffmpeg_exe", lambda _settings: "fixture-ffmpeg")
    monkeypatch.setattr(module, "wait_for_coverage", AsyncMock(return_value=[Segment(segment, 100, 106)]))
    loop_thread = threading.get_ident()
    touched = []
    for name in ("mkdir", "exists", "resolve", "write_text", "unlink"):
        original = getattr(Path, name)

        def guarded(path, *args, _name=name, _original=original, **kwargs):
            if str(path).startswith(str(tmp_path)):
                assert threading.get_ident() != loop_thread, f"{_name} blocked the engine event loop"
                touched.append(_name)
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(Path, name, guarded)

    async def command(args, *_args, **_kwargs):
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "success":
            await asyncio.to_thread(Path(args[-1]).write_bytes, b"encoded")
        return SimpleNamespace(returncode=0 if outcome == "success" else 1, err_text="fixture failure")

    monkeypatch.setattr(module, "run_cmd", command)

    async def run():
        if outcome == "success":
            result = await assemble(event, None, settings, tmp_path / "work")
            assert result.id == event.id and result.end_wall - result.start_wall == 6
        else:
            with pytest.raises(asyncio.CancelledError if outcome == "cancel" else AssembleError):
                await assemble(event, None, settings, tmp_path / "work")

    asyncio.run(run())
    assert "mkdir" in touched and "unlink" in touched


def test_dashboard_capture_snapshot_never_scans_storage(tmp_path, monkeypatch):
    """A stalled metadata worker cannot stall dashboard controls or invent fresh data."""
    import clipbot.capture as module
    target = StreamTarget(Platform.TWITCH, "fixture", "Fixture", "Art", 1)
    cap = Capture(target, Settings(), tmp_path, None)
    entered, release = threading.Event(), threading.Event()

    def slow_scan(_folder):
        entered.set()
        assert release.wait(2), "test worker was not released"
        return [Segment(tmp_path / "segment.ts", 100, 106)], 106

    monkeypatch.setattr(module, "_scan_segments", slow_scan)

    async def run():
        worker = asyncio.create_task(asyncio.to_thread(cap.segments))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            unknown = cap.snapshot()
            assert not unknown["metadata_available"] and unknown["metadata_age_s"] is None
        finally:
            release.set()
            await worker
        snapshot = cap.snapshot()
        assert snapshot["segments"] == 1 and snapshot["buffered_s"] == 6
        assert snapshot["metadata_available"] and snapshot["metadata_age_s"] >= 0
        monkeypatch.setattr(cap, "segments", lambda: pytest.fail("dashboard enumerated capture storage"))
        monkeypatch.setattr(module, "newest_segment_time", lambda _path: pytest.fail("dashboard enumerated capture storage"))
        assert cap.snapshot()["latest_segment_wall"] == 106

    asyncio.run(run())
