"""Reclaim disk space without losing anything that still matters.

Order matters: work files first (they are rebuildable), then buffers for streams nobody is
watching any more, then the oldest segments of live buffers. Finished clips are never touched -
they are the product.
"""
from __future__ import annotations

import logging
import re
import shutil
import stat
import time
from pathlib import Path

from .config import AppPaths, Settings
from .models import ID_LEN

logger = logging.getLogger("clipbot.sweeper")

GB = 1024 ** 3
HOUR_S = 3600.0
SEGMENT_GLOB = "seg_*.ts"
_SEGMENT_NAME = re.compile(r"seg_\d{14}\.ts")
_BUFFER_NAME = re.compile(r"(?:twitch|kick)_[A-Za-z0-9_.-]+")
_CANDIDATE_NAME = re.compile(rf"[0-9a-f]{{{ID_LEN}}}")
_WORK_NAME = re.compile(rf"(?:[0-9a-f]+_(?:raw\.mp4|concat\.txt)|"
                        rf"[A-Za-z0-9_.-]+_[0-9a-f]{{{ID_LEN}}}(?:\.ass|_main\.mp4)|"
                        r"clip_[A-Za-z0-9_-]+\.mp4)")


def _linked(path: Path) -> bool:
    """Fail closed for links, junctions and other Windows reparse points."""
    try:
        info = path.lstat()
        return (stat.S_ISLNK(info.st_mode)
                or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))
    except FileNotFoundError:
        return False
    except OSError:
        return True


def safe_cleanup_path(path: Path) -> bool:
    """Never clean a filesystem root or a path reached through a link."""
    absolute = path.absolute()
    return absolute != Path(absolute.anchor) and not any(_linked(p) for p in (absolute, *absolute.parents))


def safe_buffer_folder(folder: Path, *, allow_empty: bool = False) -> bool:
    """Recognize existing generated stream buffers without trusting arbitrary directories."""
    if not safe_cleanup_path(folder.parent) or not safe_cleanup_path(folder):
        return False
    if not _BUFFER_NAME.fullmatch(folder.name) or not folder.is_dir():
        return False
    try:
        entries = list(folder.iterdir())
        return (bool(entries) or allow_empty) and all(
            not _linked(p) and p.is_file() and _SEGMENT_NAME.fullmatch(p.name) for p in entries)
    except OSError:
        return False


def owned_buffer_folders(root: Path) -> list[Path]:
    if not safe_cleanup_path(root) or not root.exists():
        return []
    return [p for p in root.iterdir() if safe_buffer_folder(p)]


def _cleanup_root(paths: AppPaths, role: str) -> bool:
    root = getattr(paths, role).absolute()
    if not safe_cleanup_path(root):
        return False
    for other_role in ("data", "buffer", "work", "clips", "logs", "models"):
        if other_role == role:
            continue
        other = getattr(paths, other_role)
        if other is None:
            continue
        protected = other.absolute()
        if protected == root or protected.is_relative_to(root):
            return False
    # Finished media and models remain protected even when a scratch role is nested inside them.
    return not any(root.is_relative_to(p.absolute()) for p in (paths.clips, paths.models) if p is not None)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _remove(path: Path) -> int:
    """Delete a file or folder, returning the bytes reclaimed (0 if it was in use)."""
    freed = 0
    if not safe_cleanup_path(path):
        return 0
    try:
        if path.is_dir():
            pending, files = [path], []
            while pending:
                for child in pending.pop().iterdir():
                    if _linked(child):
                        return 0
                    if child.is_dir():
                        pending.append(child)
                    elif child.is_file():
                        files.append(child)
            freed = sum(_size(p) for p in files)
            shutil.rmtree(path, ignore_errors=True)
        else:
            freed = _size(path)
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("could not remove %s: %s", path, exc)
        return 0
    return freed


def stale_work(paths: AppPaths, keep_h: float, now: float | None = None) -> list[Path]:
    """Work files older than ``keep_h`` hours: raw cuts, concat lists, extracted frames."""
    now = time.time() if now is None else now
    if not _cleanup_root(paths, "work") or not paths.work.exists():
        return []
    cutoff = now - keep_h * HOUR_S
    out = []
    for child in paths.work.iterdir():
        if _linked(child) or not child.is_file() or not _WORK_NAME.fullmatch(child.name):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                out.append(child)
        except OSError:
            continue
    # Select only individual generated preview files; never recursively delete a shared folder.
    for name in ("frames", "posters", "thumbs", "studio"):
        folder = paths.work / name
        if not safe_cleanup_path(folder) or not folder.is_dir():
            continue
        if name == "frames":
            for candidate in folder.iterdir():
                if not safe_cleanup_path(candidate) or not candidate.is_dir() or not _CANDIDATE_NAME.fullmatch(candidate.name):
                    continue
                out += [p for p in candidate.iterdir() if not _linked(p) and p.is_file()
                        and re.fullmatch(r"\d+\.jpg", p.name) and _mtime(p) < cutoff]
        else:
            for child in folder.iterdir():
                valid = (_BUFFER_NAME.fullmatch(child.stem) if name == "thumbs"
                         else _CANDIDATE_NAME.fullmatch(child.stem))
                suffix = ".mp4" if name == "studio" else ".jpg"
                if valid and not _linked(child) and child.is_file() and child.suffix == suffix and _mtime(child) < cutoff:
                    out.append(child)
    return out


def dead_buffers(paths: AppPaths, live_keys: set[str], idle_h: float,
                 now: float | None = None) -> list[Path]:
    """Buffer folders for streams that are no longer watched and have stopped growing."""
    now = time.time() if now is None else now
    if not _cleanup_root(paths, "buffer") or not paths.buffer.exists():
        return []
    cutoff = now - idle_h * HOUR_S
    out = []
    for child in owned_buffer_folders(paths.buffer):
        if child.name in live_keys:
            continue
        newest = max((_mtime(p) for p in child.glob(SEGMENT_GLOB)), default=0.0)
        if newest < cutoff:
            out.append(child)
    return out


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def oldest_segments(paths: AppPaths, want_bytes: int) -> list[Path]:
    """Oldest buffer segments across every stream, enough to free ``want_bytes``."""
    segs = []
    if not _cleanup_root(paths, "buffer") or not paths.buffer.exists():
        return []
    for folder in owned_buffer_folders(paths.buffer):
        segs += [(p, _mtime(p), _size(p)) for p in folder.glob(SEGMENT_GLOB)]
    segs.sort(key=lambda row: row[1])
    out, freed = [], 0
    for path, _when, size in segs:
        if freed >= want_bytes:
            break
        out.append(path)
        freed += size
    return out


def free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def sweep(settings: Settings, paths: AppPaths, live_keys: set[str],
          want_gb: float = 0.0) -> int:
    """Tidy up, and if ``want_gb`` is set keep going until that much is free. Returns bytes freed.

    Called on a timer, and again by the disk guard before it gives up and pauses capture."""
    freed = 0
    for path in stale_work(paths, settings.app.work_keep_h):
        freed += _remove(path)
    for folder in dead_buffers(paths, live_keys, settings.app.work_keep_h):
        freed += _remove(folder)
    if freed:
        logger.info("tidied up %.1f GB of work files and dead buffers", freed / GB)
    if not want_gb:
        return freed

    missing = int(want_gb * GB) - free_bytes(paths.buffer)
    if missing <= 0:
        return freed
    dropped = 0
    for path in oldest_segments(paths, missing):
        dropped += _remove(path)
    if dropped:
        freed += dropped
        logger.warning("disk was nearly full: dropped %.1f GB of the oldest buffered video",
                       dropped / GB)
    return freed
