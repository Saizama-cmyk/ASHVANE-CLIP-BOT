"""Self-contained Hollow anthologies from ordered, already-finished story videos.

The caller resolves and authorizes source projects. This compiler accepts only
regular local files, copies them before encoding, and never regenerates narration
or story visuals. One caller-owned StoryStudio job runs the compiler at a time.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import shutil
import stat
import threading
import uuid
from pathlib import Path

from .config import Settings, ffmpeg_exe, ffprobe_exe
from .util import ERR_SNIPPET, run_cmd

logger = logging.getLogger("clipbot.story_compilation")


def _plain_path(value, *, file=False):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError("Missing validated compilation asset path")
    path = Path(value)
    if not path.is_absolute() or path.drive.startswith("\\\\"):
        raise ValueError("Compilation assets require validated absolute local paths")
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError("Compilation paths cannot contain links or junctions")
    if file:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Compilation inputs must be regular files without hard links")
        if info.st_size <= 0:
            raise ValueError("Compilation input is empty")
    return path.resolve()


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _copy_source(source, target, *, chunk_bytes, byte_limit, cancelled):
    """Exclusive chunked snapshot; reject an input changed during its copy."""
    before = source.stat()
    copied, digest = 0, hashlib.sha256()
    with source.open("rb") as original, target.open("xb") as snapshot:
        if _signature(os.fstat(original.fileno())) != _signature(before):
            raise ValueError("A story source changed before snapshotting; retry the compilation")
        while not cancelled.is_set():
            chunk = original.read(chunk_bytes)
            if not chunk:
                break
            copied += len(chunk)
            if copied > byte_limit:
                raise ValueError("Compilation source snapshots exceed their configured size limit")
            snapshot.write(chunk)
            digest.update(chunk)
        if cancelled.is_set():
            return None
        if (_signature(os.fstat(original.fileno())) != _signature(before)
                or _signature(source.stat()) != _signature(before) or copied != before.st_size):
            raise ValueError("A story source changed while snapshotting; retry the compilation")
    return {"sha256": digest.hexdigest(), "bytes": copied}


async def _snapshot(source, target, cfg, remaining_bytes):
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(_copy_source, source, target,
        chunk_bytes=cfg.compilation_copy_chunk_bytes, byte_limit=remaining_bytes, cancelled=cancelled))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        # Repeated owner/stop cancellation must not detach a still-owned writer.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                logger.exception("Compilation snapshot failed while cancellation drained its writer")
        raise


def _positive(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing measured {label}") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"Invalid measured {label}")
    return result


def _stream_duration(stream, fallback):
    value = stream.get("duration")
    if value is not None:
        return _positive(value, "stream duration")
    tagged = stream.get("tags", {}).get("DURATION")
    if tagged:
        try:
            hours, minutes, seconds = tagged.split(":")
            return _positive(float(hours) * 3600 + float(minutes) * 60 + float(seconds), "stream duration")
        except (ValueError, TypeError):
            pass
    return fallback


def _metadata_text(value):
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", "\\\n")


def _title_ass(path, title, seconds, width, height, cfg):
    font = cfg.caption_font.replace(",", " ").replace("\r", " ").replace("\n", " ")
    safe = title.replace("\\", "＼").replace("{", "(").replace("}", ")")
    # The ASS fields below are protocol values: center alignment, white text,
    # no outline/shadow. The configured Hollow subtitle face/size is reused.
    path.write_text(
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Title,{font},{cfg.caption_font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,{cfg.caption_font_size},{cfg.caption_font_size},{cfg.caption_font_size},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
        f"Dialogue: 0,0:00:00.00,{_ass_time(seconds)},Title,,0,0,0,,{safe}\n", encoding="utf-8")


def _ass_time(seconds):
    units = math.ceil(seconds * 100)
    hours, units = divmod(units, 3600 * 100)
    minutes, units = divmod(units, 60 * 100)
    seconds, units = divmod(units, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{units:02}"


class StoryCompiler:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _command(self, args, cwd):
        result = await run_cmd(args, self.settings.stories.render_timeout_s, str(cwd),
                               grace_s=self.settings.app.shutdown_timeout_s)
        if result.returncode:
            raise ValueError("Hollow compilation failed: " + result.err_text[-ERR_SNIPPET:])
        return result

    async def _probe(self, path, *, audio_only=False):
        result = await self._command([ffprobe_exe(self.settings), "-v", "error", "-show_format", "-show_streams",
                                      "-show_chapters", "-of", "json", str(path)], path.parent)
        data = json.loads(result.out_text)
        duration = _positive(data.get("format", {}).get("duration"), "media duration")
        streams = data.get("streams", [])
        audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
        video = next((row for row in streams if row.get("codec_type") == "video" and not row.get("disposition", {}).get("attached_pic")), None)
        if audio is None or (not audio_only and video is None):
            raise ValueError("Every compiled story and finished compilation must contain video and original audio")
        audio_duration = _stream_duration(audio, duration)
        video_duration = _stream_duration(video, duration) if video else None
        return {"duration_s": duration, "audio_duration_s": audio_duration, "video_duration_s": video_duration,
                "audio": audio, "video": video, "chapters": data.get("chapters", [])}

    def _encode_args(self):
        # Hollow renders use CPU H.264, independently of Surge's GPU encoder.
        cfg = self.settings.stories
        return ["-c:v", "libx264", "-preset", self.settings.edit.preset, "-crf", str(cfg.crf), "-pix_fmt", "yuv420p",
                "-r", str(cfg.fps), "-c:a", "pcm_s16le", "-ar", str(self.settings.edit.audio_sample_rate), "-ac", "2"]

    async def _normalize(self, source, target, duration, width, height):
        cfg = self.settings.stories
        video = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={cfg.fps},setpts=PTS-STARTPTS,"
                 f"tpad=stop_mode=clone:stop_duration={duration}")
        audio = f"aresample={self.settings.edit.audio_sample_rate}:async=1:first_pts=0,apad"
        await self._command([ffmpeg_exe(self.settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                             "-i", str(source), "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn", "-map_metadata", "-1",
                             "-vf", video, "-af", audio, "-t", str(duration), *self._encode_args(), str(target)], target.parent)

    async def _card(self, title, target, duration, width, height):
        cfg = self.settings.stories
        subtitle = target.with_suffix(".ass")
        _title_ass(subtitle, title, duration, width, height, cfg)
        await self._command([ffmpeg_exe(self.settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={cfg.fps}",
            "-f", "lavfi", "-i", f"anullsrc=r={self.settings.edit.audio_sample_rate}:cl=stereo",
            "-vf", "ass=" + subtitle.name, "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration),
            *self._encode_args(), str(target)], target.parent)

    async def compile(self, inputs, directory, *, title, opening_s=None, between_s=None, landscape=True):
        cfg = self.settings.stories
        if not ffmpeg_exe(self.settings) or not ffprobe_exe(self.settings):
            raise ValueError("Install ffmpeg and ffprobe before compiling finished stories")
        if not isinstance(inputs, list) or not 2 <= len(inputs) <= cfg.compilation_max_stories:
            raise ValueError("Choose between two and the configured maximum number of finished stories")
        if type(landscape) is not bool:
            raise ValueError("Compilation orientation must be a boolean")
        def public_title(value):
            if (not isinstance(value, str) or not value.strip() or len(value) > cfg.max_title_chars
                    or any(ord(char) < ord(" ") for char in value)):
                raise ValueError("Compilation and chapter titles must be bounded public text")
            return value.strip()
        title = public_title(title)
        opening = cfg.compilation_opening_s if opening_s is None else opening_s
        between = cfg.compilation_between_s if between_s is None else between_s
        for value in (opening, between):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Title card duration must be bounded nonnegative seconds")
        # Per-request values use the same schema ceilings as Settings; configured
        # card durations are defaults, not an accidental upper limit.
        type(cfg).model_validate({**cfg.model_dump(), "compilation_opening_s": opening, "compilation_between_s": between})
        destination = _plain_path(directory)
        sources, total_bytes, info = [], 0, []
        maximum_bytes = cfg.compilation_max_source_mb * 1024 * 1024
        for row in inputs:
            if not isinstance(row, dict):
                raise ValueError("Compilation inputs must be ordered finished-story records")
            identifier = row.get("project_id")
            if not isinstance(identifier, str) or uuid.UUID(hex=identifier).hex != identifier:
                raise ValueError("Invalid source story project identifier")
            path = _plain_path(row.get("path"), file=True)
            if path == destination or destination in path.parents or path in destination.parents:
                raise ValueError("Compile into a new edition separate from all source story assets")
            total_bytes += path.stat().st_size
            if total_bytes > maximum_bytes:
                raise ValueError("Selected story files exceed the compilation snapshot size limit")
            sources.append({"project_id": identifier, "title": public_title(row.get("title")), "path": path})
            info.append(await self._probe(path))
        # Align every segment to output video frames without trimming an original
        # audio or visual tail. The last frame/quiet pad covers the shorter stream.
        duration = sum(math.ceil(max(row["duration_s"], row["audio_duration_s"], row["video_duration_s"]) * cfg.fps) / cfg.fps for row in info)
        duration += math.ceil(opening * cfg.fps) / cfg.fps + (len(sources) - 1) * math.ceil(between * cfg.fps) / cfg.fps
        if duration > cfg.compilation_max_duration_s:
            raise ValueError("Selected stories and cards exceed the compilation duration limit")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError("A compilation edition must use a fresh empty project directory")
        destination.mkdir(parents=True, exist_ok=True)
        # Admission reserve: snapshots + normalized/assembled/remuxed video,
        # plus exact stereo 16-bit PCM for measured media duration. This is an
        # explicit estimate, not a promise that CRF output has a fixed bitrate.
        reserved_bytes = total_bytes + total_bytes * 2 + total_bytes + math.ceil(duration * self.settings.edit.audio_sample_rate * 2 * 2)
        free_bytes = (await asyncio.to_thread(shutil.disk_usage, destination)).free
        if free_bytes < reserved_bytes:
            raise ValueError("Insufficient free space for compilation snapshots and render intermediates; choose a project drive with more free space")
        width, height = (cfg.image_height, cfg.image_width) if landscape else (cfg.image_width, cfg.image_height)
        if width % 2 or height % 2:
            raise ValueError("Compilation video dimensions must be even for H.264")
        snapshot_dir, work = destination / "sources", destination / "working"
        snapshot_dir.mkdir()
        work.mkdir()
        succeeded = False
        try:
            snapshots, copied = [], 0
            for index, source in enumerate(sources):
                target = snapshot_dir / f"story-{index}.mp4"
                receipt = await _snapshot(source["path"], target, cfg, maximum_bytes - copied)
                copied += receipt["bytes"]
                measured = await self._probe(target)
                snapshots.append({"project_id": source["project_id"], "title": source["title"], "file": str(target),
                                  **receipt, "duration_s": measured["duration_s"]})
                info[index] = measured
            measured_total = sum(math.ceil(max(row["duration_s"], row["audio_duration_s"], row["video_duration_s"]) * cfg.fps) / cfg.fps for row in info)
            measured_total += math.ceil(opening * cfg.fps) / cfg.fps + (len(sources) - 1) * math.ceil(between * cfg.fps) / cfg.fps
            if measured_total > cfg.compilation_max_duration_s:
                raise ValueError("Snapshotted stories and cards exceed the compilation duration limit")
            parts, chapters, timeline = [], [], 0.0
            async def append_part(kind, text, seconds, source=None):
                nonlocal timeline
                target = work / f"part-{len(parts)}.mov"
                normalized_duration = math.ceil(seconds * cfg.fps) / cfg.fps
                if source is None:
                    await self._card(text, target, normalized_duration, width, height)
                else:
                    await self._normalize(source, target, normalized_duration, width, height)
                measured = await self._probe(target)
                if abs(measured["duration_s"] - normalized_duration) > cfg.compilation_duration_tolerance_s:
                    raise ValueError("A compilation segment failed its measured duration check")
                parts.append({"file": target.name, "duration_s": measured["duration_s"], "kind": kind})
                timeline += measured["duration_s"]
                if timeline > cfg.compilation_max_duration_s:
                    raise ValueError("Measured compilation segments exceed the duration limit")
            if opening:
                chapters.append({"title": title, "start_s": timeline, "kind": "opening"})
                await append_part("opening", title, opening)
            for index, source in enumerate(sources):
                chapter = {"title": source["title"], "start_s": timeline, "kind": "story", "project_id": source["project_id"]}
                chapters.append(chapter)
                if index and between:
                    await append_part("card", source["title"], between)
                chapter["video_start_s"] = timeline
                measured = info[index]
                await append_part("story", source["title"], max(measured["duration_s"], measured["audio_duration_s"], measured["video_duration_s"]), Path(snapshots[index]["file"]))
            listing = work / "parts.txt"
            listing.write_text("\n".join(f"file '{part['file']}'\nduration {part['duration_s']:.9f}" for part in parts), encoding="utf-8")
            normalized_bytes = sum((work / part["file"]).stat().st_size for part in parts)
            if (await asyncio.to_thread(shutil.disk_usage, work)).free < normalized_bytes:
                raise ValueError("Insufficient free space to assemble the measured compilation segments")
            assembled = work / "assembled.mp4"
            await self._command([ffmpeg_exe(self.settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "concat", "-safe", "1", "-i", str(listing), "-map", "0:v:0", "-map", "0:a:0", "-map_metadata", "-1",
                "-c:v", "copy", "-c:a", "aac", "-b:a", cfg.audio_bitrate, "-ar", str(self.settings.edit.audio_sample_rate), "-ac", "2",
                "-af", f"aresample={self.settings.edit.audio_sample_rate}:async=1:first_pts=0", "-movflags", "+faststart", str(assembled)], work)
            assembled_info = await self._probe(assembled)
            if abs(assembled_info["duration_s"] - timeline) > cfg.compilation_duration_tolerance_s:
                raise ValueError("Finished compilation duration differs from its measured segment timeline")
            if (await asyncio.to_thread(shutil.disk_usage, work)).free < assembled.stat().st_size * 2:
                raise ValueError("Insufficient free space for the final chaptered video and audio delivery")
            metadata = [";FFMETADATA1", "title=" + _metadata_text(title)]
            for index, chapter in enumerate(chapters):
                chapter["end_s"] = chapters[index + 1]["start_s"] if index + 1 < len(chapters) else assembled_info["duration_s"]
                metadata += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(chapter['start_s'] * 1000)}",
                             f"END={round(chapter['end_s'] * 1000)}", "title=" + _metadata_text(chapter["title"])]
            chapter_file = work / "chapters.ffmeta"
            chapter_file.write_text("\n".join(metadata) + "\n", encoding="utf-8")
            video, audio = work / "story.mp4", work / "narration.m4a"
            await self._command([ffmpeg_exe(self.settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(assembled), "-f", "ffmetadata", "-i", str(chapter_file), "-map", "0:v:0", "-map", "0:a:0",
                "-map_metadata", "1", "-map_chapters", "1", "-c", "copy", "-movflags", "+faststart", str(video)], work)
            await self._command([ffmpeg_exe(self.settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(video), "-map", "0:a:0", "-vn", "-map_chapters", "-1", "-c:a", "copy", str(audio)], work)
            measured_video, measured_audio = await self._probe(video), await self._probe(audio, audio_only=True)
            tolerance = cfg.compilation_duration_tolerance_s
            if (abs(measured_video["duration_s"] - timeline) > tolerance
                    or abs(measured_video["audio_duration_s"] - measured_video["video_duration_s"]) > tolerance
                    or abs(measured_audio["duration_s"] - measured_video["duration_s"]) > tolerance):
                raise ValueError("Finished compilation failed independent audio/video duration checks")
            streams = measured_video
            frame_rate = streams["video"].get("r_frame_rate", "0/1")
            numerator, denominator = frame_rate.split("/")
            if (streams["video"].get("width") != width or streams["video"].get("height") != height
                    or float(numerator) / _positive(denominator, "frame-rate denominator") != cfg.fps
                    or streams["video"].get("codec_name") != "h264" or streams["audio"].get("codec_name") != "aac"
                    or int(streams["audio"].get("sample_rate", 0)) != self.settings.edit.audio_sample_rate
                    or abs(_positive(streams["video"].get("nb_frames"), "video frame count") / cfg.fps - streams["video_duration_s"]) > tolerance):
                raise ValueError(f"Finished compilation did not match the configured output format: {streams['video'].get('width')}x{streams['video'].get('height')}, fps={frame_rate}, video={streams['video'].get('codec_name')}, audio={streams['audio'].get('codec_name')}, sample_rate={streams['audio'].get('sample_rate')}")
            probed_chapters = measured_video["chapters"]
            if len(probed_chapters) != len(chapters):
                raise ValueError("Finished compilation lost its measured chapter metadata")
            for chapter, actual in zip(chapters, probed_chapters):
                start, end = float(actual["start_time"]), float(actual["end_time"])
                if (abs(start - chapter["start_s"]) > tolerance or abs(end - chapter["end_s"]) > tolerance
                        or actual.get("tags", {}).get("title") != chapter["title"]):
                    raise ValueError("Finished compilation chapter timing or titles changed during muxing")
                chapter.update(start_s=start, end_s=end)
            final_video, final_audio = destination / video.name, destination / audio.name
            video.replace(final_video)
            audio.replace(final_audio)
            result = {"video_path": str(final_video), "audio_path": str(final_audio), "duration_s": measured_video["duration_s"],
                      "width": width, "height": height, "fps": cfg.fps, "visual_mode": "Compilation of original finished stories",
                      "narrator": "Original story voices", "chapters": chapters, "source_snapshots": snapshots,
                      "av_metadata": {"video_codec": "h264", "audio_codec": "aac", "sample_rate": self.settings.edit.audio_sample_rate,
                                      "frame_rate": frame_rate, "average_frame_rate": streams["video"].get("avg_frame_rate"),
                                      "video_duration_s": measured_video["video_duration_s"], "audio_duration_s": measured_video["audio_duration_s"]},
                      "warnings": ["Each original video's visuals and voice are retained with letterboxing and output-format normalization; title cards are silent."]}
            (destination / "compilation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            succeeded = True
            return result
        finally:
            await asyncio.to_thread(shutil.rmtree, work)
            if not succeeded:
                # Only this fresh edition's compiler-owned files are removed.
                await asyncio.to_thread(shutil.rmtree, snapshot_dir)
                for name in ("story.mp4", "narration.m4a", "compilation.json"):
                    (destination / name).unlink(missing_ok=True)
