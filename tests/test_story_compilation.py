"""Real tiny anthology renders, source ownership and bounded cancellation."""
import asyncio
import hashlib
import json
import struct
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clipbot.config import Settings, ffmpeg_exe, ffprobe_exe
from clipbot.story_compilation import StoryCompiler, _plain_path, _snapshot
from clipbot.util import child_count, run_cmd


def test_repeated_snapshot_cancellation_drains_owned_writer(tmp_path, monkeypatch):
    async def run():
        entered, cancelled, release, done = (threading.Event() for _ in range(4))
        def worker(source, target, *, cancelled: threading.Event, **kwargs):
            entered.set()
            while not cancelled.wait(.01):
                pass
            globals_cancelled.set()
            release.wait(5)
            done.set()
        globals_cancelled = cancelled
        monkeypatch.setattr("clipbot.story_compilation._copy_source", worker)
        task = asyncio.create_task(_snapshot(tmp_path / "source", tmp_path / "target", settings().stories, 1024))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            assert await asyncio.to_thread(cancelled.wait, 2)
            task.cancel()
            await asyncio.sleep(.01)
            assert not task.done() and not done.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert done.is_set()
    asyncio.run(run())


def settings():
    result = Settings()
    result.stories.image_width = 256
    result.stories.image_height = 320
    result.stories.fps = 12
    result.stories.compilation_opening_s = .25
    result.stories.compilation_between_s = .25
    result.edit.preset = "ultrafast"
    return result


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


async def fixture_stories(folder, cfg):
    if not ffmpeg_exe(cfg) or not ffprobe_exe(cfg):
        pytest.skip("ffmpeg/ffprobe unavailable")
    folder.mkdir()
    inputs = []
    for index, (color, size, fps, tone, rate, duration) in enumerate([
            ("red", "256x144", 12, 440, 32000, .75),
            ("blue", "144x256", 30, 880, 44100, 1.15)]):
        path = folder / f"source-{index}.mp4"
        result = await run_cmd([ffmpeg_exe(cfg), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
            f"color=c={color}:s={size}:r={fps}", "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate={rate}",
            "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(path)], cfg.stories.render_timeout_s)
        assert result.returncode == 0, result.err_text
        inputs.append({"project_id": uuid.uuid4().hex, "title": f"Original story {index + 1}", "path": path})
    return inputs


async def frame(path, seconds, cfg):
    result = await run_cmd([ffmpeg_exe(cfg), "-v", "error", "-ss", str(seconds), "-i", str(path),
                            "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], 30)
    assert result.returncode == 0 and len(result.stdout) == 3
    return tuple(result.stdout)


def test_real_mixed_story_compilation_preserves_order_audio_sources_and_measured_chapters(tmp_path):
    async def run():
        cfg = settings()
        inputs = await fixture_stories(tmp_path / "originals", cfg)
        original_hashes = [digest(row["path"]) for row in inputs]
        compiler = StoryCompiler(cfg)
        result = await compiler.compile(inputs, tmp_path / "edition", title="Opening #1 = dusk; {literal}")
        video, audio = Path(result["video_path"]), Path(result["audio_path"])
        assert video.is_file() and audio.is_file()
        assert [digest(row["path"]) for row in inputs] == original_hashes
        assert [row["sha256"] for row in result["source_snapshots"]] == original_hashes
        assert [row["title"] for row in result["chapters"]] == ["Opening #1 = dusk; {literal}", "Original story 1", "Original story 2"]
        assert result["chapters"][0]["start_s"] == 0
        assert result["chapters"][1]["start_s"] == .25
        assert result["chapters"][2]["start_s"] >= 1
        assert result["chapters"][2]["video_start_s"] > result["chapters"][2]["start_s"]
        assert result["chapters"][-1]["end_s"] == pytest.approx(result["duration_s"], abs=.01)
        red = await frame(video, result["chapters"][1]["video_start_s"] + .2, cfg)
        blue = await frame(video, result["chapters"][2]["video_start_s"] + .2, cfg)
        assert red[0] > red[2] * 2 and blue[2] > blue[0] * 2
        silence = await run_cmd([ffmpeg_exe(cfg), "-v", "error", "-ss", "0.05", "-i", str(video), "-t", "0.05",
                                  "-map", "0:a:0", "-f", "f32le", "-ac", "1", "pipe:1"], 30)
        assert silence.returncode == 0, silence.err_text
        samples = struct.unpack("<" + "f" * (len(silence.stdout) // 4), silence.stdout)
        assert samples and max(abs(sample) for sample in samples) < .0001
        for chapter, frequency in zip(result["chapters"][1:], (440, 880)):
            sound = await run_cmd([ffmpeg_exe(cfg), "-v", "error", "-ss", str(chapter["video_start_s"] + .2),
                                   "-i", str(video), "-t", "0.2", "-map", "0:a:0", "-f", "f32le", "-ac", "1", "pipe:1"], 30)
            assert sound.returncode == 0, sound.err_text
            values = struct.unpack("<" + "f" * (len(sound.stdout) // 4), sound.stdout)
            crossings = sum(a < 0 <= b for a, b in zip(values, values[1:]))
            actual_frequency = crossings / (len(values) / cfg.edit.audio_sample_rate)
            assert actual_frequency == pytest.approx(frequency, abs=20)
        probe = await compiler._probe(video)
        assert probe["video"]["width"] == 320 and probe["video"]["height"] == 256
        assert probe["audio"]["sample_rate"] == str(cfg.edit.audio_sample_rate)
        assert len(probe["chapters"]) == 3
        assert json.loads((video.parent / "compilation.json").read_text())["chapters"] == result["chapters"]
        for row in inputs:
            row["path"].unlink()
        assert (await compiler._probe(video))["duration_s"] == result["duration_s"]
        assert all(Path(row["file"]).is_file() for row in result["source_snapshots"])
        assert not (video.parent / "working").exists()
    asyncio.run(run())


def test_real_direct_cut_starts_first_story_at_zero_without_title_cards(tmp_path):
    async def run():
        cfg = settings()
        inputs = await fixture_stories(tmp_path / "originals", cfg)
        result = await StoryCompiler(cfg).compile(list(reversed(inputs)), tmp_path / "edition", title="Reverse order",
                                                  opening_s=0, between_s=0, landscape=False)
        assert len(result["chapters"]) == 2 and result["chapters"][0]["start_s"] == 0
        assert [row["project_id"] for row in result["chapters"]] == [row["project_id"] for row in reversed(inputs)]
        assert result["width"] == 256 and result["height"] == 320
        blue = await frame(Path(result["video_path"]), .2, cfg)
        assert blue[2] > blue[0] * 2
    asyncio.run(run())


def test_cancelling_actual_ffmpeg_drains_child_and_leaves_original_sources_untouched(tmp_path, monkeypatch):
    async def run():
        cfg = settings()
        inputs = await fixture_stories(tmp_path / "originals", cfg)
        original_hashes = [digest(row["path"]) for row in inputs]
        compiler, entered = StoryCompiler(cfg), asyncio.Event()
        async def slow_normalize(source, target, *args):
            assert source.parent.name == "sources"
            entered.set()
            await compiler._command([ffmpeg_exe(cfg), "-v", "error", "-nostdin", "-re", "-f", "lavfi", "-i",
                                      "testsrc2=size=64x64:rate=12", "-f", "null", "-"], target.parent)
        monkeypatch.setattr(compiler, "_normalize", slow_normalize)
        baseline = child_count()
        task = asyncio.create_task(compiler.compile(inputs, tmp_path / "edition", title="Cancel test", opening_s=0, between_s=0))
        await asyncio.wait_for(entered.wait(), 30)
        while child_count() == baseline:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert child_count() == baseline
        assert [digest(row["path"]) for row in inputs] == original_hashes
        assert not list((tmp_path / "edition").iterdir())
    asyncio.run(run())


def test_copy_cancellation_drains_its_writer_before_return(tmp_path, monkeypatch):
    async def run():
        from clipbot import story_compilation as module
        cfg = settings().stories
        source, target = tmp_path / "source.mp4", tmp_path / "copy.mp4"
        source.write_bytes(b"original")
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        done = []
        def copy(source, target, *, cancelled, **kwargs):
            target.write_bytes(b"partial")
            loop.call_soon_threadsafe(entered.set)
            assert cancelled.wait(5)
            done.append(True)
        monkeypatch.setattr(module, "_copy_source", copy)
        task = asyncio.create_task(_snapshot(source, target, cfg, 100))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert done and source.read_bytes() == b"original"
    asyncio.run(run())


@pytest.mark.parametrize("opening,between,title", [(31, 0, "Title"), (0, 31, "Title"), (-1, 0, "Title"), (float("nan"), 0, "Title"), (0, 0, "Bad\nTitle")])
def test_invalid_cards_and_titles_are_rejected_before_writes(tmp_path, opening, between, title):
    async def run():
        with pytest.raises(ValueError):
            await StoryCompiler(settings()).compile([{}, {}], tmp_path / "edition", title=title, opening_s=opening, between_s=between)
        assert not (tmp_path / "edition").exists()
    asyncio.run(run())


def test_count_duration_size_disk_and_link_bounds_reject_without_encoding(tmp_path, monkeypatch):
    async def run():
        cfg = settings()
        compiler = StoryCompiler(cfg)
        with pytest.raises(ValueError, match="between two"):
            await compiler.compile([{}], tmp_path / "one", title="One")
        with pytest.raises(ValueError, match="between two"):
            await compiler.compile([{}] * (cfg.stories.compilation_max_stories + 1), tmp_path / "many", title="Many")
        inputs = []
        for index in range(2):
            path = tmp_path / f"source-{index}.mp4"
            path.write_bytes(b"fake bounded fixture")
            inputs.append({"path": path, "project_id": uuid.uuid4().hex, "title": "Original title"})
        measured = {"duration_s": 40, "audio_duration_s": 40, "video_duration_s": 40}
        monkeypatch.setattr(compiler, "_probe", AsyncMock(return_value=measured))
        monkeypatch.setattr(compiler, "_normalize", AsyncMock(side_effect=AssertionError("Must reject before encoding")))
        cfg.stories.compilation_max_duration_s = 60
        with pytest.raises(ValueError, match="duration limit"):
            await compiler.compile(inputs, tmp_path / "long", title="Long")
        cfg.stories.compilation_max_duration_s = 120
        monkeypatch.setattr("clipbot.story_compilation.shutil.disk_usage", lambda path: SimpleNamespace(free=0))
        with pytest.raises(ValueError, match="Insufficient free space"):
            await compiler.compile(inputs, tmp_path / "no-space", title="No space")
        cfg.stories.compilation_max_source_mb = 1
        with inputs[0]["path"].open("wb") as source:
            source.truncate(1024 * 1024 + 1)
        with pytest.raises(ValueError, match="snapshot size limit"):
            await compiler.compile(inputs, tmp_path / "big", title="Big")
        with pytest.raises(ValueError, match="absolute"):
            _plain_path("relative.mp4", file=True)
        selected = inputs[1]["path"]
        original_is_link = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == selected or original_is_link(path))
        with pytest.raises(ValueError, match="links"):
            _plain_path(selected, file=True)
        compiler._normalize.assert_not_awaited()
    asyncio.run(run())


def test_missing_audio_source_is_rejected_before_compilation_writes(tmp_path):
    async def run():
        cfg = settings()
        if not ffmpeg_exe(cfg) or not ffprobe_exe(cfg):
            pytest.skip("ffmpeg/ffprobe unavailable")
        source = tmp_path / "silent-video.mp4"
        made = await run_cmd([ffmpeg_exe(cfg), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                              "color=c=black:s=64x64:r=12", "-t", "0.25", "-c:v", "libx264", str(source)], 30)
        assert made.returncode == 0
        inputs = [{"path": source, "project_id": uuid.uuid4().hex, "title": "Missing original audio"}] * 2
        with pytest.raises(ValueError, match="original audio"):
            await StoryCompiler(cfg).compile(inputs, tmp_path / "edition", title="No replacement narration")
        assert source.is_file() and not (tmp_path / "edition").exists()
    asyncio.run(run())


def test_all_sources_are_snapshotted_before_any_story_encode(tmp_path, monkeypatch):
    async def run():
        cfg = settings()
        inputs = await fixture_stories(tmp_path / "originals", cfg)
        compiler = StoryCompiler(cfg)
        snapshots = []
        async def stop_before_encoding(source, target, *args):
            snapshots.extend(sorted(source.parent.iterdir()))
            assert len(snapshots) == 2
            assert [digest(path) for path in snapshots] == [digest(row["path"]) for row in inputs]
            # The owner can remove originals after snapshotting; the encoder
            # receives an edition-owned copy, not an original path.
            for row in inputs:
                row["path"].unlink()
            assert source.is_file()
            raise RuntimeError("Deterministic stop before encoding")
        monkeypatch.setattr(compiler, "_normalize", stop_before_encoding)
        with pytest.raises(RuntimeError, match="Deterministic stop"):
            await compiler.compile(inputs, tmp_path / "edition", title="Snapshot boundary", opening_s=0, between_s=0)
        assert not list((tmp_path / "edition").iterdir())
    asyncio.run(run())

