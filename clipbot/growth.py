"""Growth telemetry and an explicitly requested, read-only linked YouTube library.

Local snapshots never contact a platform. Sync runs inside the requesting task and
holds the Surge account-profile lease until its bounded read/cache transaction ends.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request

from .analytics import DAY_S, compute_insights
from .config import atomic_write
from .publishers.base import PublishError
from .publishers.youtube import CHANNELS_URL, IDS_PER_CALL, TITLE_MAX, VIDEOS_URL

logger = logging.getLogger("clipbot.growth")
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
API_URLS = frozenset({CHANNELS_URL, PLAYLIST_ITEMS_URL, VIDEOS_URL})
THUMB_HOSTS = frozenset({"i.ytimg.com", "img.youtube.com", "yt3.ggpht.com", "yt3.googleusercontent.com"})
PROFILE_ID = re.compile(r"(?:default|[a-f0-9]{32})")
REMOTE_ID = re.compile(r"[A-Za-z0-9_-]+")
CACHE_FIELDS = frozenset({"business", "account_profile_id", "status", "last_run", "last_attempt", "error", "videos", "channel", "truncated"})
VIDEO_FIELDS = frozenset({"id", "title", "url", "published_at", "thumbnail", "views", "likes", "comments"})
CHANNEL_FIELDS = frozenset({"id", "title", "subscribers", "total_views", "video_count"})
LOCAL_FIELDS = ("status", "backlog", "latency", "scheduler", "ai", "copywriter", "capture_storage")


def _count(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 and str(value).isdigit() else None


def _text(value, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _remote_id(value, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or not REMOTE_ID.fullmatch(value):
        raise ValueError("YouTube returned an invalid resource identifier")
    return value


def _thumbnail(snippet: dict) -> str:
    thumbnails = snippet.get("thumbnails")
    if not isinstance(thumbnails, dict):
        return ""
    candidates = [row for row in thumbnails.values() if isinstance(row, dict)]
    candidates.sort(key=lambda row: _count(row.get("width")) or 0, reverse=True)
    for row in candidates:
        value = row.get("url")
        if not isinstance(value, str):
            continue
        try:
            parsed = urlsplit(value)
            if (parsed.scheme == "https" and parsed.hostname in THUMB_HOSTS
                    and parsed.username is None and parsed.password is None
                    and httpx.URL(value).port is None):
                return value
        except (ValueError, httpx.InvalidURL):
            continue
    return ""


class Growth:
    def __init__(self, ctx):
        self.ctx = ctx
        self._sync_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._attempts: dict[str, float] = {}
        self._outcome_attempts: dict[str, float] = {}
        self._closed = False

    @property
    def cfg(self):
        return self.ctx.settings.analytics

    @property
    def profiles(self):
        return self.ctx.pipeline.account_profiles

    def _cache_path(self, profile_id: str) -> Path:
        if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
            raise ValueError("Invalid Growth account profile")
        root = Path(self.ctx.paths.data).absolute()
        path = root / "growth" / "youtube" / "clips" / (profile_id + ".json")
        for item in (path, *path.parents):
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise ValueError("Growth cache paths cannot contain links")
            if item == root:
                break
        if path.exists() and not path.is_file():
            raise ValueError("Growth cache must be a regular file")
        if path.is_file() and path.stat().st_nlink != 1:
            raise ValueError("Growth cache cannot be a hardlink")
        return path

    def _empty(self, profile_id: str) -> dict:
        return {"business": "clips", "account_profile_id": profile_id, "status": "not_synced",
                "last_run": 0.0, "last_attempt": 0.0, "error": "", "videos": [], "channel": None}

    def _load(self, profile_id: str) -> dict:
        empty = self._empty(profile_id)
        try:
            path = self._cache_path(profile_id)
            if not path.exists():
                return empty
            if path.stat().st_size > self.cfg.youtube_response_max_bytes:
                raise ValueError("YouTube cache exceeds its configured limit")
            with path.open("rb") as stream:
                raw = stream.read(self.cfg.youtube_response_max_bytes + 1)
            if len(raw) > self.cfg.youtube_response_max_bytes:
                raise ValueError("YouTube cache grew beyond its configured limit")
            data = json.loads(raw)
            if (not isinstance(data, dict) or data.get("business") != "clips"
                    or data.get("account_profile_id") != profile_id or not isinstance(data.get("videos"), list)
                    or len(data["videos"]) > self.cfg.youtube_library_limit
                    or not isinstance(data.get("last_run"), (int, float))
                    or not isinstance(data.get("last_attempt", 0), (int, float))):
                raise ValueError("YouTube cache belongs to another profile or is invalid")
            if (set(data) - CACHE_FIELDS or not isinstance(data.get("status"), str) or data.get("status") not in {"not_synced", "ready", "error"}
                    or not isinstance(data.get("error"), str)
                    or any(type(data.get(key, 0)) not in (int, float) or not math.isfinite(data.get(key, 0))
                           or data.get(key, 0) < 0 for key in ("last_run", "last_attempt"))):
                raise ValueError("Invalid YouTube cache metadata")
            channel = data.get("channel")
            if channel is not None:
                if (not isinstance(channel, dict) or set(channel) != CHANNEL_FIELDS
                        or not isinstance(channel["title"], str)
                        or any(channel[key] is not None and (type(channel[key]) is not int or channel[key] < 0)
                               for key in ("subscribers", "total_views", "video_count"))):
                    raise ValueError("Invalid YouTube channel cache")
                _remote_id(channel["id"], self.ctx.settings.account_profiles.max_handle_chars)
            for row in data["videos"]:
                if (not isinstance(row, dict) or set(row) != VIDEO_FIELDS
                        or any(not isinstance(row[key], str) for key in ("id", "title", "url", "published_at", "thumbnail"))
                        or any(row[key] is not None and (type(row[key]) is not int or row[key] < 0)
                               for key in ("views", "likes", "comments"))):
                    raise ValueError("Invalid YouTube video cache")
                _remote_id(row["id"], self.ctx.settings.account_profiles.max_handle_chars)
                if row["url"] != "https://www.youtube.com/watch?v=" + row["id"]:
                    raise ValueError("Invalid cached YouTube video link")
            return {**empty, **data}
        except (OSError, ValueError, RecursionError):
            logger.warning("Growth YouTube cache rejected for selected profile")
            return {**empty, "status": "error", "error": "Saved YouTube library could not be read; sync this profile again."}

    def _save(self, profile_id: str, data: dict) -> None:
        if data.get("business") != "clips" or data.get("account_profile_id") != profile_id:
            raise ValueError("YouTube cache ownership mismatch")
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > self.cfg.youtube_response_max_bytes:
            raise ValueError("YouTube cache exceeds its configured limit")
        path = self._cache_path(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, raw)

    def _local_records(self, profile_id: str, now: float) -> tuple[list, dict, list]:
        store = self.ctx.pipeline.store
        since = now - self.cfg.dashboard_window_days * DAY_S
        posts = [row for row in store.measurable_posts(since)
                 if (row.get("account_profile_id") or "default") == profile_id]
        posts.sort(key=lambda row: row["posted_at"], reverse=True)
        posts = posts[:self.cfg.dashboard_posts_limit]
        metrics = store.metrics_for([row["post_id"] for row in posts])
        # Legacy account snapshots lack a destination-profile column. Never assign
        # those observations to a newly selected non-default destination.
        history = store.account_history(since) if profile_id == "default" else []
        return posts, metrics, history

    @staticmethod
    async def _thread(function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def snapshot(self) -> dict:
        if self._closed:
            raise HTTPException(503, "Growth is shutting down")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with self.profiles.upload("clips"):
                profile_id = self.profiles.active_id("clips")
                now = time.time()
                local = await self.ctx.pipeline.snapshot()
                records = await self._thread(self._local_records, profile_id, now)
                library = await self._thread(self._load, profile_id)
                posts, metrics, history = records
                outcomes = await self._thread(self.ctx.pipeline.store.outcomes_for,
                                             [row["post_id"] for row in posts], profile_id)
                analytics = copy.deepcopy(self.ctx.pipeline.analytics.snapshot())
                accounts = {}
                channel = library.get("channel")
                if isinstance(channel, dict):
                    accounts["youtube"] = {"followers": channel.get("subscribers"),
                        "total_views": channel.get("total_views"), "posts": channel.get("video_count")}
                learning_since = now - self.cfg.lookback_days * DAY_S
                learning_posts = [row for row in posts if row["posted_at"] >= learning_since]
                insights = compute_insights(learning_posts, metrics, self.ctx.settings, accounts, outcomes)
                insights.updated = max((row.get("captured_at", 0) for rows in metrics.values() for row in rows), default=0)
                analytics.update(insights.to_dict())
                analytics.update(history=history, account_profile_id=profile_id,
                    learning_window_days=self.cfg.lookback_days, display_window_days=self.cfg.dashboard_window_days,
                    history_ownership="legacy_unattributed" if profile_id == "default" else "unavailable_for_profile",
                    account_ownership="profile_youtube_cache" if accounts else "unavailable_for_profile")
                supervisor = getattr(self.ctx, "supervisor", None)
                state = supervisor.snapshot() if supervisor is not None else {}
                agents = state.get("agents", [])
                if isinstance(agents, dict):
                    agents = list(agents.values())
                return {"analytics": analytics,
                    "posts": [{**row, "metrics": metrics.get(row["post_id"], []),
                               "outcome": outcomes.get(row["post_id"])} for row in posts],
                    "fetched_at": now, "poll_s": self.cfg.growth_poll_s, "account_profile_id": profile_id,
                    "local": {key: copy.deepcopy(local.get(key)) for key in LOCAL_FIELDS},
                    "supervisor": {"enabled": state.get("enabled", self.ctx.settings.supervisor.enabled),
                        "state": state.get("state", "not_started"),
                        "agents": [{key: row.get(key, "") for key in ("id", "name", "status")}
                                   for row in agents if isinstance(row, dict)]},
                    "youtube_library": library}
        except PublishError:
            raise HTTPException(409, "Account profile is changing; try Growth again") from None
        finally:
            self._tasks.discard(task)

    async def _get(self, url: str, token: str, params: dict) -> dict:
        if url not in API_URLS:
            raise ValueError("Growth only reads fixed official YouTube endpoints")
        async with self.ctx.pipeline.http.stream("GET", url, params=params,
                headers={"Authorization": "Bearer " + token}, follow_redirects=False,
                timeout=self.ctx.settings.discovery.http_timeout_s) as response:
            if response.status_code != 200:
                raise HTTPException(502, "YouTube could not read the linked channel. Check its connection and API access.")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > self.cfg.youtube_response_max_bytes:
                    raise ValueError("YouTube response exceeds its configured limit")
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("items"), list) or len(value["items"]) > IDS_PER_CALL:
            raise ValueError("YouTube returned invalid or excessive items")
        return value

    async def _read_library(self, token: str) -> tuple[dict, list, bool]:
        limit = self.cfg.youtube_library_limit
        text_limit = self.ctx.settings.account_profiles.max_handle_chars
        response = await self._get(CHANNELS_URL, token, {"mine": "true", "part": "snippet,statistics,contentDetails",
            "fields": "items(id,snippet(title),statistics,contentDetails/relatedPlaylists/uploads)"})
        if len(response["items"]) != 1:
            raise ValueError("Connect one YouTube channel before syncing its library")
        mine = response["items"][0]
        if not isinstance(mine, dict):
            raise ValueError("YouTube returned invalid channel details")
        channel_id = _remote_id(mine.get("id"), text_limit)
        snippet, stats, details = mine.get("snippet", {}), mine.get("statistics", {}), mine.get("contentDetails", {})
        if not all(isinstance(row, dict) for row in (snippet, stats, details)):
            raise ValueError("YouTube returned invalid channel fields")
        channel = {"id": channel_id, "title": _text(snippet.get("title"), TITLE_MAX),
            "subscribers": None if stats.get("hiddenSubscriberCount") else _count(stats.get("subscriberCount")),
            "total_views": _count(stats.get("viewCount")), "video_count": _count(stats.get("videoCount"))}
        related = details.get("relatedPlaylists")
        uploads = related.get("uploads") if isinstance(related, dict) else None
        if not uploads:
            if channel["video_count"] == 0:
                return channel, [], False
            raise ValueError("YouTube did not identify the linked channel's uploads playlist")
        uploads = _remote_id(uploads, text_limit)
        videos, seen, pages = [], set(), set()
        cursor = ""
        for _ in range(math.ceil(limit / IDS_PER_CALL)):
            params = {"part": "snippet,contentDetails", "playlistId": uploads,
                "maxResults": min(IDS_PER_CALL, limit - len(videos)),
                "fields": "nextPageToken,items(contentDetails/videoId,snippet(title,publishedAt,videoOwnerChannelId,thumbnails))"}
            if cursor:
                params["pageToken"] = cursor
            listing = await self._get(PLAYLIST_ITEMS_URL, token, params)
            for item in listing["items"]:
                if not isinstance(item, dict):
                    raise ValueError("YouTube returned invalid playlist entries")
                snippet, details = item.get("snippet", {}), item.get("contentDetails", {})
                if not isinstance(snippet, dict) or not isinstance(details, dict):
                    raise ValueError("YouTube returned invalid playlist fields")
                owner = snippet.get("videoOwnerChannelId")
                if owner and owner != channel_id:
                    raise ValueError("Uploads playlist returned a video from another channel")
                video_id = _remote_id(details.get("videoId"), text_limit)
                if video_id in seen:
                    continue
                seen.add(video_id)
                videos.append({"id": video_id, "title": _text(snippet.get("title"), TITLE_MAX),
                    "url": "https://www.youtube.com/watch?v=" + video_id,
                    "published_at": _text(snippet.get("publishedAt"), text_limit), "thumbnail": _thumbnail(snippet),
                    "views": None, "likes": None, "comments": None})
                if len(videos) >= limit:
                    break
            cursor = listing.get("nextPageToken", "")
            if cursor and (not isinstance(cursor, str) or len(cursor) > text_limit or cursor in pages):
                raise ValueError("YouTube returned invalid or repeating pagination")
            if not cursor or len(videos) >= limit:
                break
            pages.add(cursor)
        by_id = {row["id"]: row for row in videos}
        for start in range(0, len(videos), IDS_PER_CALL):
            ids = [row["id"] for row in videos[start:start + IDS_PER_CALL]]
            got = await self._get(VIDEOS_URL, token, {"part": "snippet,statistics", "id": ",".join(ids),
                "fields": "items(id,snippet(title,publishedAt,channelId,thumbnails),statistics)"})
            for item in got["items"]:
                if not isinstance(item, dict) or item.get("id") not in ids:
                    raise ValueError("YouTube returned an unrequested video")
                snippet, stats = item.get("snippet", {}), item.get("statistics", {})
                if not isinstance(snippet, dict) or not isinstance(stats, dict):
                    raise ValueError("YouTube returned invalid video fields")
                if snippet.get("channelId") and snippet["channelId"] != channel_id:
                    raise ValueError("Video details belong to a different channel")
                row = by_id[item["id"]]
                row.update(title=_text(snippet.get("title"), TITLE_MAX) or row["title"],
                    published_at=_text(snippet.get("publishedAt"), text_limit) or row["published_at"],
                    thumbnail=_thumbnail(snippet) or row["thumbnail"], views=_count(stats.get("viewCount")),
                    likes=_count(stats.get("likeCount")), comments=_count(stats.get("commentCount")))
        return channel, videos, bool(cursor)

    async def sync(self, expected: str = "") -> dict:
        if self._closed:
            raise HTTPException(503, "Growth is shutting down")
        self.profiles.require_current("clips", expected)
        if self._sync_lock.locked():
            raise HTTPException(409, "A YouTube library sync is already running")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with self._sync_lock:
                async with self.profiles.upload("clips"):
                    self.profiles.require_current("clips", expected)
                    profile_id = self.profiles.active_id("clips")
                    previous = await self._thread(self._load, profile_id)
                    now = time.time()
                    last = max(self._attempts.get(profile_id, 0), previous.get("last_attempt", 0))
                    if last and now - last < self.cfg.youtube_sync_min_s:
                        raise HTTPException(429, "Wait for the YouTube sync cooldown before syncing this profile again")
                    if not self.ctx.pipeline.oauth.connected("youtube"):
                        raise HTTPException(409, "Connect this Surge profile's YouTube channel before syncing")
                    self._attempts[profile_id] = now
                    try:
                        async def fetch():
                            token = await self.ctx.pipeline.oauth.access_token("youtube")
                            return await self._read_library(token)
                        channel, videos, truncated = await asyncio.wait_for(fetch(), self.cfg.youtube_sync_timeout_s)
                        result = {**self._empty(profile_id), "status": "ready", "last_run": time.time(),
                            "last_attempt": now, "channel": channel, "videos": videos, "truncated": truncated}
                        await self._thread(self._save, profile_id, result)
                        return result
                    except asyncio.CancelledError:
                        raise
                    except (HTTPException, httpx.HTTPError, PublishError, OSError, ValueError, TimeoutError, RecursionError) as exc:
                        logger.warning("Growth YouTube sync failed (%s)", type(exc).__name__)
                        error = "YouTube library sync could not complete. Check the selected profile's connection and retry."
                        failed = {**previous, "status": "error", "error": error, "last_attempt": now}
                        try:
                            await self._thread(self._save, profile_id, failed)
                        except (OSError, ValueError):
                            logger.warning("Growth could not persist selected profile's sync failure")
                        raise HTTPException(502, error) from None
        except PublishError:
            raise HTTPException(409, "Account profile is changing; try syncing again") from None
        finally:
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        pending = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def growth(ctx) -> Growth:
    service = getattr(ctx, "growth", None)
    if service is None:
        service = ctx.growth = Growth(ctx)
    return service


def install_growth_routes(app, ctx) -> None:
    router = APIRouter(prefix="/api/growth")
    @router.get("")
    async def snapshot():
        return await growth(ctx).snapshot()
    @router.post("/youtube/sync")
    async def sync(request: Request):
        return await growth(ctx).sync(request.headers.get("X-Account-Profile", ""))
    @router.post("/outcomes/refresh")
    async def outcomes_refresh(request: Request):
        service = growth(ctx)
        expected = request.headers.get("X-Account-Profile", "")
        service.profiles.require_current("clips", expected)
        expected = expected or service.profiles.active_id("clips")
        now = time.monotonic()
        if expected in service._outcome_attempts and now - service._outcome_attempts[expected] < service.cfg.youtube_sync_min_s:
            raise HTTPException(429, "Wait for the platform-outcome refresh cooldown before retrying this profile")
        service._outcome_attempts[expected] = now
        try:
            await ctx.pipeline.analytics.tick(force=True, expected_profile=expected)
        except PublishError:
            raise HTTPException(409, "Account profile changed; refresh its Growth data again") from None
        return {"ok": True, "status": ctx.pipeline.analytics.snapshot().get("youtube_outcomes", "not_checked")}
    app.include_router(router)


async def close_growth(ctx) -> None:
    service = getattr(ctx, "growth", None)
    if service is not None:
        await service.close()
