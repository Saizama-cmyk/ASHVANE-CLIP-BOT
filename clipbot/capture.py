"""Rolling capture buffers: streamlink → ffmpeg segmenter per stream.

Each target writes ``seg_%Y%m%d%H%M%S.ts`` files (local wall-clock time, parsed back with the
same local timezone) into ``<buffer>/<platform>_<login>/``. A segment's start is the time in
its name and its end is the next segment's start, so only segments with a successor are
complete. Old segments are pruned past ``capture.buffer_s``. Dead or stalled captures restart
with exponential backoff; Kick falls back to reading the channel's playback URL with ffmpeg.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from .config import Settings, ffmpeg_exe, streamlink_cmd
from .models import Platform, StreamTarget
from .sweeper import _remove, owned_buffer_folders, safe_buffer_folder, safe_cleanup_path
from .util import Backoff, CmdTimeout, run_cmd, spawn, terminate
from .storage_io import StorageIO

logger = logging.getLogger("clipbot.capture")

SEGMENT_PATTERN = "seg_%Y%m%d%H%M%S.ts"
_SEG_RE = re.compile(r"^seg_(\d{14})\.ts$")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf)\s*dB")

KickLookup = Callable[[str], Awaitable[dict | None]]


@dataclass(frozen=True)
class Segment:
    path: Path
    start: float
    end: float


def parse_segment_time(name: str) -> float | None:
    m = _SEG_RE.match(name)
    if not m:
        return None
    return time.mktime(time.strptime(m.group(1), "%Y%m%d%H%M%S"))


def _scan_segments(folder: Path) -> tuple[list[Segment], float | None]:
    """Complete segments (those with a successor), oldest first.

    A segment ends at the next one's start, or at its own last write if that is earlier —
    so a capture restart shows up as a gap instead of one impossibly long segment."""
    try:
        entries = []
        with os.scandir(folder) as listing:
            for entry in listing:
                stamp = parse_segment_time(entry.name)
                if stamp is None or not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    entries.append((stamp, Path(entry.path), entry.stat(follow_symlinks=False).st_mtime))
                except FileNotFoundError:
                    continue
    except FileNotFoundError:
        return [], None
    timed = sorted(entries)
    out = []
    for i, (t, p, written) in enumerate(timed[:-1]):
        nxt = timed[i + 1][0]
        out.append(Segment(p, t, max(t, min(nxt, written))))
    return out, timed[-1][0] if timed else None


def list_segments(folder: Path) -> list[Segment]:
    return _scan_segments(folder)[0]


def contiguous_run(segs: list[Segment], t: float, max_gap_s: float) -> list[Segment]:
    """The run of back-to-back segments that contains (or is nearest before) time ``t``."""
    runs: list[list[Segment]] = []
    for seg in segs:
        if runs and seg.start - runs[-1][-1].end <= max_gap_s:
            runs[-1].append(seg)
        else:
            runs.append([seg])
    for run in runs:
        if run[0].start <= t <= run[-1].end:
            return run
    before = [r for r in runs if r[-1].end <= t]
    return before[-1] if before else []


def newest_segment_time(folder: Path) -> float | None:
    try:
        times = [t for p in folder.iterdir() if (t := parse_segment_time(p.name)) is not None]
    except FileNotFoundError:
        return None
    return max(times) if times else None


def streamlink_args(settings: Settings, target: StreamTarget) -> list[str]:
    """Explicit transport policy; ringbuffer capacity is not a latency measurement."""
    c = settings.capture
    args = [*streamlink_cmd(settings), "--stdout", "--loglevel", "warning",
            "--hls-live-edge", str(c.hls_live_edge), "--stream-segment-threads",
            str(c.hls_segment_threads), "--stream-timeout", str(c.stream_timeout_s)]
    if c.hls_segment_stream_data:
        args.append("--hls-segment-stream-data")
    if target.platform == Platform.TWITCH and c.twitch_low_latency:
        args.append("--twitch-low-latency")
    if target.platform == Platform.KICK and c.kick_low_latency:
        args.append("--kick-low-latency")
    return [*args, target.url, c.quality]


async def mean_volume_db(ffmpeg: str, path: Path, timeout_s: float) -> float | None:
    """volumedetect mean volume of a media file, None if it has no audio."""
    res = await run_cmd([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0?",
                         "-af", "volumedetect", "-f", "null", "-"], timeout_s)
    m = _MEAN_RE.search(res.err_text)
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


class Capture:
    """One stream's capture processes and buffer folder."""

    def __init__(self, target: StreamTarget, settings: Settings, root: Path,
                 kick_lookup: KickLookup | None, storage_io: StorageIO | None = None) -> None:
        self.target = target
        self.settings = settings
        self.folder = root / f"{target.platform}_{re.sub(r'[^A-Za-z0-9_.-]', '_', target.login.lower())}"
        self.kick_lookup = kick_lookup
        self.storage_io = storage_io
        self._task: asyncio.Task | None = None
        self._procs: list = []
        self._use_fallback = False
        self.status = "stopped"
        self.restarts = 0
        self.last_error = ""
        self.started_at = 0.0
        self._audio_cache: tuple[str, float, float | None] = ("", 0.0, None)
        self.audio_sample_wall: float | None = None
        self.audio_probe_s: float | None = None
        self._cleared = False
        self._last_lines: dict[str, str] = {}
        # Immutable observations published by existing buffer workers. Dashboard reads
        # must never enumerate/stat a capture drive on the shared asyncio engine loop.
        self._buffer_observation: dict = {}
        self._buffer_error = ""

    @property
    def key(self) -> str:
        return self.target.key

    async def run_io(self, function, *args):
        if self.storage_io is not None:
            return await self.storage_io.run(function, *args)
        return await asyncio.to_thread(function, *args)

    async def read_segments(self):
        return await self.run_io(self.segments)

    @property
    def cached_segments(self) -> tuple[Segment, ...]:
        """Last complete buffer observation; never performs capture-drive I/O."""
        return self._buffer_observation.get("complete", ())

    def _reset_observation(self) -> None:
        # A scan already in flight cannot publish files from before a clear/start.
        self._buffer_observation = {"started": time.perf_counter()}
        self._buffer_error = ""

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._reset_observation()
        self._task = asyncio.create_task(self._supervise(), name=f"capture:{self.key}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._kill()
        self.status = "stopped"

    async def _kill(self) -> None:
        procs, self._procs = self._procs, []
        grace = self.settings.app.shutdown_timeout_s
        await asyncio.gather(*(terminate(p, grace) for p in procs), return_exceptions=True)

    # ------------------------------------------------------------------ supervisor
    async def _supervise(self) -> None:
        cap = self.settings.capture
        backoff = Backoff(cap.restart_backoff_min_s, cap.restart_backoff_max_s)
        if not self._cleared:  # stale files from an earlier run; keep the buffer across restarts
            await self.run_io(self._clear_folder)
            self._cleared = True
        while True:
            produced = False
            try:
                produced = await self._run_once()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError) as exc:
                self.last_error = str(exc)
                logger.warning("capture %s failed: %s", self.key, exc)
            finally:
                await self._kill()
            if produced:
                backoff.reset()
            elif (self.target.platform == Platform.KICK and cap.kick_ffmpeg_fallback
                  and self.kick_lookup is not None):
                self._use_fallback = not self._use_fallback
            self.restarts += 1
            delay = backoff.next()
            self.status = f"restarting in {delay:.0f}s"
            logger.info("capture %s ended (%s); restarting in %.0fs", self.key,
                        self.last_error or "stream ended", delay)
            await asyncio.sleep(delay)

    def _clear_folder(self) -> None:
        self._reset_observation()
        if not safe_cleanup_path(self.folder.parent) or not safe_cleanup_path(self.folder):
            raise RuntimeError("capture buffer path is a root, link or junction; choose a dedicated buffer folder")
        if self.folder.exists():
            if not safe_buffer_folder(self.folder, allow_empty=True):
                raise RuntimeError("capture buffer contains unrelated files; choose a dedicated buffer folder")
            _remove(self.folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._reset_observation()

    async def _run_once(self) -> bool:
        """Run one capture attempt until it dies or stalls. Returns True if it produced."""
        s = self.settings
        ffmpeg = await asyncio.to_thread(ffmpeg_exe, s)
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found (Settings → Paths)")
        seg_args = ["-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy", "-f", "segment",
                    "-segment_time", str(s.capture.segment_s), "-reset_timestamps", "1",
                    "-strftime", "1", SEGMENT_PATTERN]
        log_args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
        self.last_error = ""
        if self._use_fallback:
            info = await self.kick_lookup(self.target.login) if self.kick_lookup else None
            url = (info or {}).get("playback_url")
            if not url:
                raise RuntimeError("Kick fallback: no playback_url (channel API blocked or offline)")
            ff = await spawn(*log_args, "-i", url, *seg_args, cwd=str(self.folder),
                             stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                             stderr=asyncio.subprocess.PIPE)
            self._procs = [ff]
            readers = [self._drain(ff.stderr, "ffmpeg")]
            self.status = "capturing (direct)"
        else:
            # streamlink >= 7 filters Twitch ads itself (--twitch-disable-ads is a no-op now)
            sl_args = streamlink_args(s, self.target)
            r_fd, w_fd = os.pipe()
            try:
                sl = await spawn(*sl_args, stdin=asyncio.subprocess.DEVNULL, stdout=w_fd,
                                 stderr=asyncio.subprocess.PIPE)
                self._procs.append(sl)
                ff = await spawn(*log_args, "-i", "pipe:0", *seg_args, cwd=str(self.folder),
                                 stdin=r_fd, stdout=asyncio.subprocess.DEVNULL,
                                 stderr=asyncio.subprocess.PIPE)
                self._procs.append(ff)
            finally:
                os.close(r_fd)
                os.close(w_fd)
            readers = [self._drain(sl.stderr, "streamlink"), self._drain(ff.stderr, "ffmpeg")]
            self.status = "capturing"
        self.started_at = time.time()
        self._last_lines = {}
        reader_tasks = [asyncio.create_task(r) for r in readers]
        produced = False
        try:
            while True:
                await asyncio.sleep(s.capture.prune_interval_s)
                if any(p.returncode is not None for p in self._procs):
                    break
                await self.run_io(self.prune)
                newest = self._buffer_observation.get("newest")
                if newest is not None and newest >= self.started_at - s.capture.segment_s:
                    produced = True
                last = newest if newest is not None and newest >= self.started_at else self.started_at
                idle = time.time() - last
                if idle > s.capture.stall_timeout_s + s.capture.segment_s:
                    self.last_error = f"stalled ({idle:.0f}s without a new segment)"
                    break
        finally:
            for t in reader_tasks:
                t.cancel()
            await asyncio.gather(*reader_tasks, return_exceptions=True)
        if not self.last_error:
            self.last_error = self._explain_exit()
        return produced

    def _explain_exit(self) -> str:
        """Blame the process that died first: streamlink (offline, no playable streams)
        before ffmpeg (which then only sees an empty pipe)."""
        names = ["streamlink", "ffmpeg"] if len(self._procs) > 1 else ["ffmpeg"]
        for name, proc in zip(names, self._procs):
            if proc.returncode not in (None, 0) and name in self._last_lines:
                return f"{name}: {self._last_lines[name]}"
        for name in names:
            if name in self._last_lines:
                return f"{name}: {self._last_lines[name]}"
        return ""

    async def _drain(self, stream: asyncio.StreamReader | None, name: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._last_lines[name] = text
                logger.debug("%s %s: %s", self.key, name, text)

    # ------------------------------------------------------------------ buffer access
    def segments(self) -> list[Segment]:
        # Windows monotonic() can share a coarse clock tick across overlapping scans;
        # the high-resolution monotonic counter preserves completion ordering.
        started = time.perf_counter()
        try:
            segs, newest = _scan_segments(self.folder)
        except OSError as exc:
            self._buffer_error = str(exc)
            raise
        if started >= self._buffer_observation.get("started", 0):
            self._buffer_observation = {
                "started": started, "observed_at": time.time(), "newest": newest,
                "segments": len(segs), "first": segs[0].start if segs else None,
                "last": segs[-1].end if segs else None,
                "complete": tuple(segs),
            }
            self._buffer_error = ""
        return segs

    def prune(self) -> None:
        horizon = time.time() - self.settings.capture.buffer_s
        for seg in self.segments():
            if seg.end < horizon:
                try:
                    seg.path.unlink()
                except FileNotFoundError:
                    continue
                except PermissionError:
                    logger.debug("segment %s in use, pruning later", seg.path.name)

    async def latest_audio_level(self) -> tuple[str, float | None] | None:
        """(segment name, mean dB) of the newest complete segment.

        Measured at most once per segment and never more often than ``audio_cache_s``;
        callers feed the detector only when the segment name changes."""
        segs = await self.read_segments()
        if not segs:
            return None
        newest = segs[-1]
        name, when, level = self._audio_cache
        if name == newest.path.name or time.time() - when < self.settings.capture.audio_cache_s:
            return (name, level) if name else None
        ffmpeg = await asyncio.to_thread(ffmpeg_exe, self.settings)
        if not ffmpeg:
            return None
        try:
            started = time.monotonic()
            level = await mean_volume_db(ffmpeg, newest.path, self.settings.capture.probe_timeout_s)
        except CmdTimeout as exc:
            logger.debug("audio level %s: %s", self.key, exc)
            level = None
        self.audio_probe_s = time.monotonic() - started
        self.audio_sample_wall = newest.end
        self._audio_cache = (newest.path.name, time.time(), level)
        return newest.path.name, level

    def snapshot(self) -> dict:
        observed = self._buffer_observation
        if "observed_at" not in observed:
            observed = {}
        newest, last = observed.get("newest"), observed.get("last")
        now = time.time()
        return {"key": self.key, "status": self.status, "restarts": self.restarts,
                "error": self.last_error, "segments": observed.get("segments", 0),
                "metadata_available": bool(observed), "metadata_error": self._buffer_error,
                "metadata_updated_at": observed.get("observed_at"),
                "metadata_age_s": round(max(0, now - observed["observed_at"]), 2) if observed else None,
                "latest_segment_wall": newest,
                "segment_open_age_s": round(max(0, now - newest), 2) if newest is not None else None,
                "complete_segment_age_s": round(max(0, now - last), 2) if last is not None else None,
                "source_latency_s": None,  # Local filenames cannot measure provider/broadcaster delay.
                "audio_sample_age_s": round(max(0, now - self.audio_sample_wall), 2) if self.audio_sample_wall is not None else None,
                "audio_probe_s": round(self.audio_probe_s, 2) if self.audio_probe_s is not None else None,
                "buffered_s": round(last - observed["first"]) if last is not None else 0}


class CaptureManager:
    def __init__(self, settings: Settings, root: Path, kick_lookup: KickLookup | None) -> None:
        self.settings = settings
        self.root = root
        self.kick_lookup = kick_lookup
        self.storage_io = StorageIO(settings.capture.storage_workers)
        self.captures: dict[str, Capture] = {}
        self._retired: dict[Path, float] = {}
        self.paused = False

    def apply(self, settings: Settings) -> None:
        self.settings = settings
        for c in self.captures.values():
            c.settings = settings

    async def set_targets(self, targets: list[StreamTarget]) -> None:
        wanted = {t.key: t for t in targets}
        for key in [k for k in self.captures if k not in wanted]:
            cap = self.captures.pop(key)
            await cap.stop()
            self._retired[cap.folder] = time.time()
        for key, t in wanted.items():
            if key in self.captures:
                self.captures[key].target = t
                continue
            cap = Capture(t, self.settings, self.root, self.kick_lookup, self.storage_io)
            self._retired.pop(cap.folder, None)
            self.captures[key] = cap
            if not self.paused:
                cap.start()

    async def pause(self) -> None:
        self.paused = True
        await asyncio.gather(*(c.stop() for c in self.captures.values()))
        for c in self.captures.values():
            c.status = "paused"

    def resume(self) -> None:
        self.paused = False
        for c in self.captures.values():
            c.start()

    async def stop_all(self) -> None:
        await asyncio.gather(*(c.stop() for c in self.captures.values()),
                             return_exceptions=True)

    def get(self, key: str) -> Capture | None:
        return self.captures.get(key)

    async def close(self):
        await self.stop_all()
        self.storage_io.close()

    def cleanup_retired(self) -> None:
        """Delete buffer folders of streams no longer captured once they age out."""
        horizon = time.time() - self.settings.capture.buffer_s - self.settings.clip.segment_wait_s
        for folder, when in list(self._retired.items()):
            if when < horizon:
                if safe_buffer_folder(folder):
                    _remove(folder)
                self._retired.pop(folder, None)
        # folders left over from a previous run
        active = {c.folder for c in self.captures.values()} | set(self._retired)
        for d in owned_buffer_folders(self.root):
            if d not in active:
                newest = newest_segment_time(d)
                if newest is not None and newest < horizon:
                    _remove(d)
