"""Cleanup recognizes generated scratch data and leaves shared storage and links alone."""
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipbot import sweeper
from clipbot.capture import Capture, CaptureManager
from clipbot.config import AppPaths, Settings
from clipbot.models import Platform, StreamTarget


CID = "0123456789ab"
NOW = 100000.0


def paths_at(tmp_path):
    paths = AppPaths(data=tmp_path, buffer=tmp_path / "buffer", work=tmp_path / "work",
                     clips=tmp_path / "clips", logs=tmp_path / "logs",
                     db=tmp_path / "db.sqlite", tokens=tmp_path / "tokens.json")
    paths.ensure()
    return paths


def old_file(path, contents=b"owned scratch"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    os.utime(path, (0, 0))
    return path


def buffer_at(root, name="twitch_old"):
    folder = root / name
    old_file(folder / "seg_20260101000000.ts")
    return folder


def test_sweep_reclaims_generated_scratch_and_buffers_only(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    raw = old_file(paths.work / f"{CID}_raw.mp4")
    concat = old_file(paths.work / f"{CID}_concat.txt")
    captions = old_file(paths.work / f"streamer_{CID}.ass")
    frame = old_file(paths.work / "frames" / CID / "0.jpg")
    poster = old_file(paths.work / "posters" / f"{CID}.jpg")
    dead = buffer_at(paths.buffer)
    live = buffer_at(paths.buffer, "kick_live")
    finished = old_file(paths.clips / f"streamer_{CID}.mp4")
    work_finished = old_file(paths.work / f"streamer_{CID}.mp4")
    unrelated = old_file(paths.work / "notes" / "keep.txt")
    buffer_unrelated = old_file(paths.buffer / "family_videos" / "seg_20260101000000.ts")
    mixed = buffer_at(paths.buffer, "twitch_mixed")
    mixed_keeper = old_file(mixed / f"streamer_{CID}.mp4")
    monkeypatch.setattr(sweeper.time, "time", lambda: NOW)
    freed = sweeper.sweep(Settings(), paths, {"kick_live"})
    assert freed > 0
    assert all(not p.exists() for p in (raw, concat, captions, frame, poster, dead))
    assert all(p.exists() for p in (live, finished, work_finished, unrelated, buffer_unrelated, mixed_keeper))


@pytest.mark.parametrize("shared_role", ["work", "clips", "logs"])
def test_shared_buffer_role_disables_buffer_cleanup(tmp_path, shared_role):
    paths = paths_at(tmp_path)
    shared = paths.buffer
    paths = replace(paths, **{shared_role: shared})
    buffer = buffer_at(shared)
    finished = old_file(shared / f"streamer_{CID}.mp4")
    assert sweeper.dead_buffers(paths, set(), 1, NOW) == []
    assert sweeper.oldest_segments(paths, 1) == []
    assert buffer.exists() and finished.exists()


def test_shared_work_and_finished_clips_disable_scratch_cleanup(tmp_path):
    paths = paths_at(tmp_path)
    paths = replace(paths, clips=paths.work)
    raw = old_file(paths.work / f"{CID}_raw.mp4")
    finished = old_file(paths.work / f"streamer_{CID}.mp4")
    assert sweeper.stale_work(paths, 1, NOW) == []
    assert raw.exists() and finished.exists()


def test_buffer_root_containing_finished_clips_is_never_swept(tmp_path):
    paths = paths_at(tmp_path)
    paths = replace(paths, clips=paths.buffer / "clips")
    buffer_at(paths.buffer)
    old_file(paths.clips / f"streamer_{CID}.mp4")
    assert sweeper.dead_buffers(paths, set(), 1, NOW) == []
    assert sweeper.oldest_segments(paths, 1) == []


def test_disk_pressure_only_selects_actual_owned_buffer_segments(tmp_path):
    paths = paths_at(tmp_path)
    old = buffer_at(paths.buffer)
    unrelated = buffer_at(paths.buffer, "my_videos")
    mixed = buffer_at(paths.buffer, "twitch_mixed")
    old_file(mixed / "keep.mp4")
    selected = sweeper.oldest_segments(paths, 1)
    assert selected == [old / "seg_20260101000000.ts"]
    assert unrelated.exists() and mixed.exists()


def test_filesystem_roots_are_refused_without_enumerating_them(tmp_path):
    paths = paths_at(tmp_path)
    root = Path(tmp_path.anchor)
    assert not sweeper.safe_cleanup_path(root)
    assert sweeper.stale_work(replace(paths, work=root), 1, NOW) == []
    assert sweeper.dead_buffers(replace(paths, buffer=root), set(), 1, NOW) == []
    assert sweeper.oldest_segments(replace(paths, buffer=root), 1) == []
    assert sweeper._remove(root) == 0


def test_reparse_points_and_paths_beneath_them_are_not_cleanup_candidates(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    buffer = buffer_at(paths.buffer)
    raw = old_file(paths.work / f"{CID}_raw.mp4")
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path in (buffer, raw):
            return SimpleNamespace(st_mode=stat.S_IFDIR if path == buffer else stat.S_IFREG,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    assert sweeper.dead_buffers(paths, set(), 1, NOW) == []
    assert sweeper.oldest_segments(paths, 1) == []
    assert sweeper.stale_work(paths, 1, NOW) == []
    assert sweeper._remove(buffer) == 0 and sweeper._remove(raw) == 0
    assert not sweeper.safe_cleanup_path(buffer / "seg_20260101000000.ts")
    assert buffer.exists() and raw.exists()


def test_directory_containing_a_reparse_point_cannot_be_recursively_removed(tmp_path, monkeypatch):
    folder = tmp_path / "scratch"
    linked = old_file(folder / "junction" / "keep.mp4").parent
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == linked:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    assert sweeper._remove(folder) == 0 and (linked / "keep.mp4").exists()


def test_real_directory_symlink_is_preserved(tmp_path):
    paths = paths_at(tmp_path)
    outside = buffer_at(tmp_path / "other", "twitch_external")
    link = paths.buffer / "twitch_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable on this Windows host")
    assert sweeper.dead_buffers(paths, set(), 1, NOW) == []
    assert sweeper.oldest_segments(paths, 1) == []
    assert sweeper._remove(link) == 0 and link.is_symlink() and outside.exists()


def test_capture_retired_cleanup_preserves_unrelated_and_mixed_directories(tmp_path):
    root = tmp_path / "buffer"
    owned = buffer_at(root)
    unrelated = buffer_at(root, "personal")
    mixed = buffer_at(root, "twitch_mixed")
    keeper = old_file(mixed / "finished.mp4")
    manager = CaptureManager(Settings(), root, None)
    manager._retired[mixed] = 0
    manager.cleanup_retired()
    assert not owned.exists()
    assert unrelated.exists() and keeper.exists()


def test_capture_cannot_clear_unrelated_files_or_an_unsafe_root(tmp_path):
    target = StreamTarget(Platform.TWITCH, "example", "Example", "Gaming", 0)
    root = tmp_path / "buffer"
    capture = Capture(target, Settings(), root, None)
    keeper = old_file(capture.folder / "finished.mp4")
    with pytest.raises(RuntimeError, match="unrelated files"):
        capture._clear_folder()
    assert keeper.exists()
    unsafe = Capture(target, Settings(), Path(tmp_path.anchor), None)
    with pytest.raises(RuntimeError, match="root, link or junction"):
        unsafe._clear_folder()


def test_capture_restarts_with_its_existing_generated_buffer(tmp_path):
    target = StreamTarget(Platform.TWITCH, "example", "Example", "Gaming", 0)
    capture = Capture(target, Settings(), tmp_path / "buffer", None)
    segment = old_file(capture.folder / "seg_20260101000000.ts")
    capture._clear_folder()
    assert capture.folder.is_dir() and not segment.exists()
