"""Post finished clips on a schedule and expire old ones.

Per enabled + configured platform: respect ``daily_cap`` (successful posts in the last 24 h)
and ``min_gap_min`` (since the last attempt), and only post inside the posting-hours window.
The oldest SCHEDULED clip goes first, except that once clips have waited
``prefer_score_after_min`` the highest-scoring of those goes first. Every attempt is recorded;
a clip becomes POSTED once every enabled platform has a final result (ok, or failed
``max_attempts`` times). Expired clips (``retention_days``) are removed on a timer, optionally
deleting their remote posts too.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from .config import AppPaths, Settings
from .media import delete_candidate_media
from .db import Store
from .models import Candidate, Platform, Stage
from .safety import Filter
from .publishers import PLATFORMS, PostText, Publisher
from .publishers.base import PublishResult
from .publishers.youtube import upload_metadata
from .public_copy import check_public_text, require_public_copy, UnsafePublicCopy
from .sweeper import remove_rejected_media

logger = logging.getLogger("clipbot.scheduler")

DAY_S = 86400
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render_template(template: str, values: dict[str, str]) -> str:
    """Fill {name} placeholders; unknown names and stray braces are left untouched."""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template).strip()


def brand_handle(settings: Settings, target: str) -> str:
    b = settings.brand
    return {"youtube": b.youtube_handle, "tiktok": b.tiktok_handle,
            "instagram": b.instagram_handle, "facebook": b.facebook_page_name}.get(target) or b.name


def compose_post(c: Candidate, settings: Settings, target: str = "") -> PostText:
    p = settings.posting
    pc = require_public_copy(c, settings, target)
    tags = []
    title_text, caption_text = "", ""
    if target == "youtube" and pc:
        title_text, caption_text, tags = pc["title"], pc.get("description", ""), pc.get("tags", [])
    elif target in ("tiktok", "instagram") and pc:
        # these publishers post title + caption as one text: the story caption goes first
        title_text, caption_text, tags = pc["caption"], "", pc.get("hashtags", tags)
    elif target == "facebook" and pc:
        title_text, caption_text = pc.get("title") or title_text, pc.get("description", "")
    elif target == "discord" and pc:
        title_text, caption_text = pc["message"], ""
    platform = "Twitch" if c.event.target.platform == Platform.TWITCH else "Kick"
    values = {"title": title_text, "caption": caption_text,
              "streamer": c.event.target.display_name or c.event.target.login,
              "platform": platform, "category": c.event.target.category,
              "hashtags": " ".join(f"#{t}" for t in (pc.get('hashtags', []) if target == 'youtube' else tags)), "brand": settings.brand.name,
              "handle": brand_handle(settings, target)}
    values["clipper"] = str(c.source.get("clipper", ""))
    credit_tpl = (settings.clip_import.credit_template if c.source.get("type") == "twitch_clip"
                  else p.credit_template)
    values["credit"] = render_template(credit_tpl, values) if p.credit_line else ""
    title = render_template(p.title_template, values) or values["title"]
    caption = render_template(p.caption_template, values)
    caption = re.sub(r"\n{3,}", "\n\n", caption)
    flt = Filter(settings)
    post = PostText(title=flt.mask(title), caption=flt.mask(caption), hashtags=flt.clean(tags))
    check_public_text(c, public_snapshot(post, settings, target), settings)
    return post


def public_snapshot(post: PostText, settings: Settings, target: str) -> dict:
    if target == 'youtube':
        snippet = upload_metadata(post, settings.posting.youtube)['snippet']
        return {key: snippet[key] for key in ('title', 'description', 'tags')}
    return {'title': post.title, 'description': post.caption, 'tags': post.hashtags}


def in_posting_window(settings: Settings, now: datetime) -> bool:
    start, end = settings.posting.hours_start, settings.posting.hours_end
    if start == end or (start == 0 and end == 24):
        return True
    h = now.hour
    return start <= h < end if start < end else (h >= start or h < end)


def pick_candidate(cands: list[Candidate], now: float, prefer_after_s: float) -> Candidate | None:
    if not cands:
        return None
    waited = [c for c in cands if now - c.created_at >= prefer_after_s]
    if waited:
        return max(waited, key=lambda c: (float(c.verdict.get("score", 0) or 0), -c.created_at))
    return min(cands, key=lambda c: c.created_at)


class Scheduler:
    def __init__(self, settings: Settings, store: Store, publishers: dict[str, Publisher],
                 paths: AppPaths | None = None) -> None:
        self.settings = settings
        self.paths = paths
        self.store = store
        self.publishers = publishers
        self._busy: dict[str, asyncio.Task] = {}
        self.last_error: dict[str, str] = {}
        self._last_cleanup = 0.0
        self._last_rejected_cleanup = time.time()
        self._rejected_cleanup_lock = asyncio.Lock()
        self.rejected_cleanup_result: dict = {}
        self._task: asyncio.Task | None = None
        self._cand_lock = asyncio.Lock()
        self.analytics = None        # set by the pipeline: steers picks and caps flooding
        self.quality_guard = None    # pipeline's final-cut gate, including older scheduled clips
        self.media_locks: dict[str, asyncio.Lock] = {}
        self.media_in_use = None     # pipeline owns active candidate processing
        self.account_profiles = None

    def _profile_hold(self, candidate):
        return (self.account_profiles.held_reason("clips", candidate.source.get("account_profile_id", "default"))
                if self.account_profiles else "")

    def apply(self, settings: Settings) -> None:
        self.settings = settings
        for pub in self.publishers.values():
            pub.apply(settings)

    def platform_cfg(self, name: str):
        return getattr(self.settings.posting, name)

    def active_platforms(self) -> list[str]:
        return [n for n in PLATFORMS
                if self.platform_cfg(n).enabled and self.publishers[n].configured()[0]]

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        tasks = [t for t in [self._task, *self._busy.values()] if t]
        self._task = None
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._busy.clear()

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the scheduler alive; the traceback goes to the log
                logger.exception("scheduler tick failed")
            await asyncio.sleep(self.settings.posting.tick_s)

    # ------------------------------------------------------------------ core
    async def _eligible(self, name: str, now: float) -> tuple[bool, str]:
        cfg = self.platform_cfg(name)
        posted = await asyncio.to_thread(self.store.posts_since, name, now - DAY_S)
        if posted >= cfg.daily_cap:
            return False, f"daily cap reached ({posted}/{cfg.daily_cap})"
        last = await asyncio.to_thread(self.store.last_post_time, name)
        if last is not None and now - last < cfg.min_gap_min * 60:
            return False, f"next slot in {int((last + cfg.min_gap_min * 60 - now) / 60) + 1} min"
        return True, ""

    async def tick(self) -> None:
        now = time.time()
        interval = self.settings.clip.rejected_cleanup_min
        if interval > 0 and now - self._last_rejected_cleanup >= interval * 60:
            self._last_rejected_cleanup = now
            await self.delete_rejected_media()
        if now - self._last_cleanup >= self.settings.posting.cleanup_interval_s:
            self._last_cleanup = now
            await self.cleanup()
        await self._finalize_all()
        if not in_posting_window(self.settings, datetime.now()):
            return
        for name in self.active_platforms():
            if name in self._busy and not self._busy[name].done():
                continue
            ok, _ = await self._eligible(name, now)
            if not ok:
                continue
            cands = await self._pending_for(name)
            chosen = await self._choose(name, cands, now)
            if chosen:
                self._busy[name] = asyncio.create_task(self._post(name, chosen.id),
                                                       name=f"post:{name}")

    async def _choose(self, name: str, cands: list[Candidate], now: float) -> Candidate | None:
        """Pick the next clip for ``name``: anti-flood caps first, then analytics priority
        (except on exploration picks, which use the plain oldest / best-after-waiting rule)."""
        if not cands:
            return None
        prefer = self.settings.posting.prefer_score_after_min * 60
        an = self.analytics
        if an is None:
            return pick_candidate(cands, now, prefer)
        midnight = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0,
                                                       microsecond=0).timestamp()
        today = await asyncio.to_thread(self.store.posts_today, name, midnight)
        allowed = [c for c in cands if an.within_caps(c, today)]
        if not allowed:
            return None
        if not an.active or an.explore_now(name):
            return pick_candidate(allowed, now, prefer)
        return max(allowed, key=lambda c: (float(c.verdict.get("score", 0) or 0) + an.bias(c),
                                           -c.created_at))

    async def _pending_for(self, name: str) -> list[Candidate]:
        cands = await asyncio.to_thread(self.store.candidates_in_stage, Stage.SCHEDULED)
        out = []
        for c in cands:
            lock = self.media_locks.setdefault(c.id, asyncio.Lock())
            async with lock:
                # A manual batch may be restoring this render or posting it while this tick waits.
                fresh = await asyncio.to_thread(self.store.get_candidate, c.id)
                if fresh is None or fresh.stage != Stage.SCHEDULED or fresh.posted_to.get(name) in ("ok", "failed"):
                    continue
                if self._profile_hold(fresh):
                    continue
                if not fresh.final_path or not Path(fresh.final_path).exists():
                    fresh.stage = Stage.FAILED
                    fresh.error = "Finished video is missing from its saved path. Restore the file or make a new clip before posting."
                    await asyncio.to_thread(self.store.upsert_candidate, fresh)
                    self.last_error[name] = fresh.error
                    logger.warning("scheduled clip %s cannot post: finished video is missing", fresh.id)
                    continue
                out.append(fresh)
        return out

    async def _post(self, name: str, cand_id: str):
        # Share this lock with Studio: the bytes reviewed must be the bytes uploaded.
        lock = self.media_locks.setdefault(cand_id, asyncio.Lock())
        async with lock:
            return await self._post_checked(name, cand_id)

    async def _post_checked(self, name: str, cand_id: str):
        if self.account_profiles:
            if reason := self.account_profiles.held_reason("clips", self.account_profiles.active_id("clips")):
                return PublishResult(False, error=reason)
            async with self.account_profiles.upload("clips"):
                return await self._post_for_profile(name, cand_id)
        return await self._post_for_profile(name, cand_id)

    async def _post_for_profile(self, name: str, cand_id: str):
        c = await asyncio.to_thread(self.store.get_candidate, cand_id)
        if c is None:
            return None
        if reason := self._profile_hold(c):
            self.last_error[name] = reason
            return PublishResult(False, error=reason)
        # Recheck under the media lock: a manual or automatic upload may have finished while waiting.
        if c.posted_to.get(name) == "ok":
            posts = await asyncio.to_thread(self.store.posts_for_candidate, cand_id)
            previous = next((p for p in reversed(posts) if p["platform"] == name and p["status"] == "ok"), {})
            return PublishResult(True, remote_id=previous.get("remote_id", ""), url=previous.get("url", ""))
        try:
            if self.quality_guard and not await self.quality_guard(c):
                self.last_error[name] = c.error or "Final-cut review did not pass"
                return PublishResult(False, error=self.last_error[name])
            post = compose_post(c, self.settings, name)
        except UnsafePublicCopy as exc:
            c.error = self.last_error[name] = str(exc)
            await asyncio.to_thread(self.store.upsert_candidate, c)
            return PublishResult(False, error=str(exc))
        if not self.settings.businesses.surge_enabled:
            return PublishResult(False, error="Surge is stopped; this clip remains queued")
        logger.info("posting %s to %s: %s", c.id, name, post.title)
        result = await self.publishers[name].publish(Path(c.final_path), post)
        await asyncio.to_thread(self.store.record_post, c.id, name, result.remote_id, result.url,
                                "ok" if result.ok else "failed", result.error,
                                public_text=public_snapshot(post, self.settings, name))
        attempts = sum(1 for p in await asyncio.to_thread(self.store.posts_for_candidate, c.id)
                       if p["platform"] == name)
        async with self._cand_lock:
            fresh = await asyncio.to_thread(self.store.get_candidate, c.id)
            if fresh is None:
                return result
            if result.ok:
                fresh.posted_to[name] = "ok"
                self.last_error.pop(name, None)
            else:
                self.last_error[name] = result.error
                logger.warning("%s post of %s failed (attempt %d/%d): %s", name, c.id, attempts,
                               self.settings.posting.max_attempts, result.error)
                if attempts >= self.settings.posting.max_attempts:
                    fresh.posted_to[name] = "failed"
            self._maybe_finish(fresh)
            await asyncio.to_thread(self.store.upsert_candidate, fresh)
        return result

    async def publish_now(self, cand_id: str, platforms: list[str]) -> dict[str, dict]:
        """Post one clip right away, ignoring caps, gaps and the posting window (testing /
        pushing a specific video). Each platform's result is recorded like a scheduled post."""
        lock = self.media_locks.setdefault(cand_id, asyncio.Lock())
        async with lock:
            return await self._publish_now_locked(cand_id, platforms)

    async def _publish_now_locked(self, cand_id: str, platforms: list[str]) -> dict[str, dict]:
        """The caller holds the clip's media lock through render, review and every upload."""
        out: dict[str, dict] = {}
        for name in platforms:
            pub = self.publishers.get(name)
            if pub is None:
                out[name] = {"ok": False, "error": "unknown platform"}
                continue
            ready, reason = pub.configured()
            if not ready:
                out[name] = {"ok": False, "error": reason}
                continue
            current = await asyncio.to_thread(self.store.get_candidate, cand_id)
            already_posted = bool(current and current.posted_to.get(name) == "ok")
            res = await self._post_checked(name, cand_id)
            out[name] = ({"ok": res.ok, "url": res.url, "error": res.error} if res is not None
                         else {"ok": False, "error": "clip not found"})
            if already_posted:
                out[name]["already_posted"] = True
        return out

    def _maybe_finish(self, c: Candidate) -> None:
        if self._profile_hold(c):
            return
        active = self.active_platforms()
        if active and all(c.posted_to.get(p) in ("ok", "failed") for p in active):
            c.stage = Stage.POSTED

    async def _finalize_all(self) -> None:
        """Clips whose remaining platforms were disabled meanwhile become POSTED."""
        if not self.active_platforms():
            return
        async with self._cand_lock:
            for c in await asyncio.to_thread(self.store.candidates_in_stage, Stage.SCHEDULED):
                if c.posted_to:
                    before = c.stage
                    self._maybe_finish(c)
                    if c.stage != before:
                        await asyncio.to_thread(self.store.upsert_candidate, c)

    # ------------------------------------------------------------------ cleanup
    async def cleanup(self) -> int:
        horizon = time.time() - self.settings.posting.retention_days * DAY_S
        expired = await asyncio.to_thread(self.store.expired_candidates, horizon)
        for c in expired:
            if self._profile_hold(c):
                continue
            if self.settings.posting.delete_remote_on_expiry:
                for p in await asyncio.to_thread(self.store.posts_for_candidate, c.id):
                    if p["status"] != "ok" or p["deleted"] or p["platform"] not in self.publishers:
                        continue
                    res = await self.publishers[p["platform"]].delete(p["remote_id"])
                    if res.ok:
                        await asyncio.to_thread(self.store.mark_post_deleted, p["id"])
                    else:
                        logger.info("could not delete %s post %s: %s", p["platform"],
                                    p["remote_id"], res.error)
            for path in (c.final_path, c.raw_path):
                if path:
                    try:
                        await asyncio.to_thread(Path(path).unlink, True)
                    except OSError as exc:
                        logger.warning("could not delete %s: %s", path, exc)
            await asyncio.to_thread(self.store.delete_candidate, c.id)
            if self.paths:
                await asyncio.to_thread(delete_candidate_media, self.paths, c.id)
        if expired:
            logger.info("expired %d clip(s) older than %d days", len(expired),
                        self.settings.posting.retention_days)
        return len(expired)

    async def delete_rejected_media(self, *, manual: bool = False) -> dict:
        """Remove only owned rejected media. Keep decisions and never interrupt an edit/upload."""
        async with self._rejected_cleanup_lock:
            result = {"clips_cleaned": 0, "files_deleted": 0, "bytes_freed": 0,
                      "files_skipped": 0, "clips_skipped": 0, "manual": manual}
            horizon = time.time() - self.settings.clip.keep_rejected_hours * 3600
            candidates = await asyncio.to_thread(self.store.candidates_in_stage, Stage.REJECTED)
            for original in candidates:
                if not self.paths or (not manual and original.created_at >= horizon):
                    result["clips_skipped"] += 1
                    continue
                lock = self.media_locks.setdefault(original.id, asyncio.Lock())
                if lock.locked() or (self.media_in_use and self.media_in_use(original.id)):
                    result["clips_skipped"] += 1
                    continue
                async with lock:
                    candidate = await asyncio.to_thread(self.store.get_candidate, original.id)
                    if (candidate is None or candidate.stage != Stage.REJECTED
                            or self._profile_hold(candidate)
                            or any(status == "ok" for status in candidate.posted_to.values())
                            or (self.media_in_use and self.media_in_use(original.id))):
                        result["clips_skipped"] += 1
                        continue
                    posts = await asyncio.to_thread(self.store.posts_for_candidate, candidate.id)
                    if any(post["status"] == "ok" for post in posts):
                        result["clips_skipped"] += 1
                        continue
                    references = await asyncio.to_thread(self.store.candidate_media_references)
                    protected = {Path(row[field]).resolve() for row in references
                                 if row["id"] != candidate.id for field in ("raw_path", "final_path")
                                 if row[field]}
                    deletion = asyncio.create_task(asyncio.to_thread(
                        remove_rejected_media, self.settings, self.paths, candidate, protected))
                    try:
                        removed = await asyncio.shield(deletion)
                    except asyncio.CancelledError:
                        # A worker thread cannot be cancelled. Retain the media lock until its
                        # deletions finish so shutdown/retry never races an edit or upload.
                        await deletion
                        raise
                    for key in ("files_deleted", "bytes_freed", "files_skipped"):
                        result[key] += removed[key]
                    if not removed["files_deleted"]:
                        continue
                    result["clips_cleaned"] += 1
                    deleted = {Path(path).resolve() for path in removed["removed"]}
                    if candidate.raw_path and Path(candidate.raw_path).resolve() in deleted:
                        candidate.raw_path = ""
                    if candidate.final_path and Path(candidate.final_path).resolve() in deleted:
                        candidate.final_path = ""
                    candidate.source = {**candidate.source, "rejected_media_cleanup": {
                        "at": time.time(), "files_deleted": removed["files_deleted"],
                        "bytes_freed": removed["bytes_freed"]}}
                    await asyncio.to_thread(self.store.upsert_candidate, candidate)
            self.rejected_cleanup_result = {**result, "finished_at": time.time()}
            if result["files_deleted"]:
                logger.info("deleted %d rejected-media files (%d bytes); decisions kept",
                            result["files_deleted"], result["bytes_freed"])
            return dict(self.rejected_cleanup_result)

    # ------------------------------------------------------------------ dashboard
    async def snapshot(self) -> dict:
        now = time.time()
        out = {}
        for name in PLATFORMS:
            cfg = self.platform_cfg(name)
            ready, reason = self.publishers[name].configured()
            posted = await asyncio.to_thread(self.store.posts_since, name, now - DAY_S)
            eligible, why = await self._eligible(name, now) if ready and cfg.enabled else (False, "")
            out[name] = {"enabled": cfg.enabled, "configured": ready,
                         "reason": reason if not ready else why,
                         "posted_24h": posted, "cap": cfg.daily_cap,
                         "busy": name in self._busy and not self._busy[name].done(),
                         "ready_now": eligible, "error": self.last_error.get(name, "")}
        return {"platforms": out, "window_open": in_posting_window(self.settings, datetime.now())}
