"""Independent original-fiction production and publication queue.

No streamer candidates, clip templates or clip scheduling switches enter this
queue. A durable upload marker precedes every remote side effect.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from .config import story_account_settings
from .public_copy import check_public_text
from .publishers import PLATFORMS, PostText, build_publishers
from .publishers.base import PublishError
from .publishers.discord import CONTENT_MAX
from .publishers.facebook import GRAPH as FACEBOOK_GRAPH
from .publishers.instagram import GRAPH as INSTAGRAM_GRAPH, CAPTION_MAX as INSTAGRAM_CAPTION_MAX
from .publishers.tiktok import API as TIKTOK_API, CAPTION_MAX as TIKTOK_CAPTION_MAX
from .publishers.youtube import CHANNELS_URL, upload_metadata
from .stories import StoryBusy
from .util import ERR_SNIPPET

logger = logging.getLogger("clipbot.story_publishing")
LABELS = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram",
          "facebook": "Facebook", "discord": "Discord"}


def _digest_file(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


class _BoundOAuth:
    """Keep an in-flight upload on the exact access token checked for its account."""

    def __init__(self, platform: str, token: str):
        self.platform, self.token = platform, token

    def connected(self, platform):
        return platform == self.platform and bool(self.token)

    async def access_token(self, platform):
        if not self.connected(platform):
            raise PublishError("The story destination changed before upload")
        return self.token


class _BoundTokens:
    def __init__(self, original):
        self.values = {name: original.get(name) for name in PLATFORMS}

    def get(self, name):
        return copy.deepcopy(self.values.get(name, {}))

    def set(self, name, value):
        self.values[name] = copy.deepcopy(value)


class StoryPublishing:
    def __init__(self, settings, http, tokens, oauth, studio, renderer):
        self.settings, self.http, self.tokens, self.oauth = settings, http, tokens, oauth
        self.studio, self.renderer = studio, renderer
        self.publishers = build_publishers(self._publisher_settings(), http, tokens, oauth)
        self.identities: dict[str, dict] = {}
        self.errors: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._tick_lock = asyncio.Lock()
        self._publishing = False
        self._settings_generation = 0

    def _publisher_settings(self):
        settings = self.settings.model_copy(deep=True)
        settings.accounts = story_account_settings(self.settings)
        cfg = settings.stories
        youtube = settings.posting.youtube
        youtube.category_id, youtube.privacy = cfg.youtube_category_id, cfg.publish_privacy
        youtube.shorts_suffix = ""
        youtube.age_restrict = False
        return settings

    def apply(self, settings):
        self._settings_generation += 1
        self.settings = settings
        self.publishers = build_publishers(self._publisher_settings(), self.http, self.tokens, self.oauth)
        self.identities.clear()

    def _credentials(self, name):
        accounts = story_account_settings(self.settings)
        if name in {"youtube", "tiktok"}:
            stored = self.tokens.get(name)
            values = {"account": stored.get("open_id", ""),
                      "credential": stored.get("refresh_token") or stored.get("access_token", ""),
                      "client": accounts.youtube_client_id if name == "youtube" else accounts.tiktok_client_key}
        elif name == "instagram":
            values = {"credential": accounts.instagram_token, "account": accounts.instagram_user_id}
        elif name == "facebook":
            values = {"credential": accounts.facebook_page_token, "account": accounts.facebook_page_id}
        else:
            values = {"credential": accounts.discord_webhook}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def _destination(self, name):
        configured, reason = self.publishers[name].configured()
        reason = reason.replace("Settings → Accounts", "Hollow accounts")
        identity = self.identities.get(name, {})
        current = identity.get("credential_hash") == self._credentials(name)
        ready = configured and current and bool(identity.get("account_id")) and not identity.get("error")
        if configured and not ready:
            reason = identity.get("error") if current else "Checking the connected destination account"
        return {"id": name, "label": LABELS[name], "ready": ready, "reason": reason or "",
                "account_id": identity.get("account_id", "") if current else "",
                "account_label": identity.get("account_label", "") if current else ""}

    def state(self):
        cfg = self.settings.stories
        return {"destinations": [self._destination(name) for name in PLATFORMS],
                "config": {"enabled": cfg.auto_publish, "destinations": list(cfg.publish_destinations),
                           "privacy": cfg.publish_privacy},
                "busy": self._publishing, "errors": dict(self.errors)}

    async def _identity(self, name):
        fingerprint = self._credentials(name)
        generation = self._settings_generation
        snapshot = self._publisher_settings()
        pub = self.publishers[name]
        configured, _ = pub.configured()
        cached = self.identities.get(name, {})
        cache_current = cached.get("credential_hash") == fingerprint
        retry_due = cached.get("error") and time.time() - cached.get("checked_at", 0) >= snapshot.stories.account_retry_s
        if not configured or (cache_current and not retry_due):
            return
        try:
            timeout = snapshot.discovery.http_timeout_s
            if name == "youtube":
                token = await self.oauth.access_token(name)
                fingerprint = self._credentials(name)
                stored_token = self.tokens.get(name).get("access_token")
                if generation != self._settings_generation or (stored_token and stored_token != token):
                    return
                response = await self.http.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                                               headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
                response.raise_for_status()
                items = response.json().get("items", [])
                account = items[0] if items else {}
                account_id, label = account.get("id", ""), account.get("snippet", {}).get("title", "")
                extra = {}
            elif name == "tiktok":
                token = await self.oauth.access_token(name)
                fingerprint = self._credentials(name)
                stored_token = self.tokens.get(name).get("access_token")
                if generation != self._settings_generation or (stored_token and stored_token != token):
                    return
                response = await self.http.post(f"{TIKTOK_API}/creator_info/query/", json={},
                                                headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
                response.raise_for_status()
                body = response.json()
                if body.get("error", {}).get("code") not in (None, "ok"):
                    raise ValueError("TikTok creator information was refused")
                account = body.get("data", {})
                account_id = self.tokens.get(name).get("open_id") or account.get("creator_username", "")
                label = account.get("creator_nickname") or account.get("creator_username", "")
                extra = {"max_duration_s": account.get("max_video_post_duration_sec"),
                         "privacy_options": account.get("privacy_level_options", [])}
            elif name == "instagram":
                token = await pub._token()
                fingerprint = self._credentials(name)
                if generation != self._settings_generation:
                    return
                response = await self.http.get(f"{INSTAGRAM_GRAPH}/me", timeout=timeout,
                                               params={"fields": "user_id,username", "access_token": token})
                response.raise_for_status()
                account = response.json()
                account_id, label = account.get("user_id", ""), account.get("username", "")
                expected = snapshot.accounts.instagram_user_id
                if expected and str(account_id) != expected:
                    raise ValueError("Instagram token belongs to a different account than the configured user ID")
                extra = {}
            elif name == "facebook":
                page = snapshot.accounts.facebook_page_id
                response = await self.http.get(f"{FACEBOOK_GRAPH}/{page}", timeout=timeout,
                                               params={"fields": "id,name", "access_token": snapshot.accounts.facebook_page_token})
                response.raise_for_status()
                account = response.json()
                account_id, label = account.get("id", ""), account.get("name", "")
                if str(account_id) != page:
                    raise ValueError("Facebook Page identity does not match the configured page")
                extra = {}
            else:
                hook = snapshot.accounts.discord_webhook
                parsed = urlsplit(hook)
                if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"} or not parsed.path.startswith("/api/webhooks/"):
                    raise ValueError("Use an official Discord HTTPS webhook")
                response = await self.http.get(hook, timeout=timeout)
                response.raise_for_status()
                account = response.json()
                account_id = account.get("id", "")
                label = account.get("name") or f"Discord channel {account.get('channel_id', '')}"
                extra = {}
            if not account_id:
                raise ValueError(f"{LABELS[name]} returned no connected account identity")
            if generation != self._settings_generation or fingerprint != self._credentials(name):
                return
            self.identities[name] = {"credential_hash": fingerprint, "account_id": str(account_id),
                                     "account_label": str(label), "error": "", "checked_at": time.time(), **extra}
            self.errors.pop(name, None)
        except (httpx.HTTPError, PublishError, ValueError, KeyError, TypeError) as exc:
            if generation != self._settings_generation or fingerprint != self._credentials(name):
                return
            reason = f"Account verification failed: {type(exc).__name__}. Reconnect this destination in Hollow accounts."
            # Never display raw HTTP URLs or tokens from account errors.
            self.identities[name] = {"credential_hash": fingerprint, "account_id": "", "account_label": "", "error": reason,
                                     "checked_at": time.time()}
            self.errors[name] = reason
            logger.warning("story destination %s verification failed (%s)", name, type(exc).__name__)

    async def initialize(self):
        await asyncio.gather(*(self._identity(name) for name in PLATFORMS))

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="story-publishing")

    async def stop(self):
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("story publication queue failed")
            await asyncio.sleep(self.settings.stories.publish_tick_s)

    def _supported(self, project, name):
        output = project.get("output", {})
        landscape = output.get("width", 0) > output.get("height", 0)
        if landscape and name not in {"youtube", "discord"}:
            return False, "Landscape episodes are supported by YouTube and Discord; this destination uses portrait Reels"
        if name == "discord":
            video = self.studio._inside(project["id"], output.get("video_path"))
            if video.stat().st_size > self.publishers[name].settings.posting.discord.max_file_mb * 1024 * 1024:
                return False, "The story exceeds the Discord attachment limit; Stories does not send a text-only substitute"
        if name == "tiktok":
            identity = self.identities.get(name, {})
            maximum = identity.get("max_duration_s")
            if maximum and output.get("duration_s", 0) > maximum:
                return False, "Story exceeds this TikTok creator's maximum video duration"
            options = identity.get("privacy_options", [])
            if options and self.publishers[name].settings.posting.tiktok.privacy not in options:
                return False, "The selected TikTok privacy is unavailable for this creator"
        return True, ""

    def request_publish(self, project_id, destinations=None):
        project = self.studio.get(project_id)
        if project is None:
            raise KeyError("Story not found")
        targets = self.settings.stories.publish_destinations if destinations is None else destinations
        if not isinstance(targets, list) or not targets or any(not isinstance(name, str) or name not in PLATFORMS for name in targets):
            raise ValueError("Choose supported story destinations")
        identity = self.studio.content_fingerprint(project_id)
        # Preflight every target before changing the durable queue.
        for name in set(targets):
            destination = self._destination(name)
            if not destination["ready"]:
                raise ValueError(f"{LABELS[name]}: {destination['reason']}")
            supported, reason = self._supported(project, name)
            if not supported:
                raise ValueError(reason)
            prior = project.get("publishing", {}).get(name, {})
            if prior.get("content_hash") == identity and prior.get("status") in {"uploading", "uncertain", "published"}:
                raise StoryBusy(f"{LABELS[name]} already uploaded or needs reconciliation")
        for name in dict.fromkeys(targets):
            self.studio.record_publish(project_id, name, "pending", content_hash=identity,
                                       account_id=self._destination(name)["account_id"])
        return self.studio.get(project_id)

    def _limits(self, name, now):
        cfg = self.settings.stories
        attempts = []
        for project in self.studio.projects:
            history = project.get("publication_history", [])
            if history:
                attempts.extend(row for row in history if row.get("platform") == name)
            else:
                attempts.extend(row for platform, row in project.get("publishing", {}).items()
                                if platform == name and row.get("status") in {"uploading", "published", "uncertain", "failed"})
        times = [row.get("attempted_at", row["updated_at"]) for row in attempts]
        day_count = sum(1 for attempted in times if now - attempted < 86400)
        if day_count >= cfg.publish_daily_cap:
            return False, "Story daily publication cap reached"
        if times and now - max(times) < cfg.publish_gap_min * 60:
            return False, "Waiting for the story publication gap"
        return True, ""

    def _post(self, project, name, settings):
        public = project["public_copy"]["youtube"]
        title, caption = public["title"], public.get("description", "")
        if "<" in title or ">" in title:
            raise ValueError("YouTube titles cannot contain angle brackets")
        tags = public.get("tags", [])
        hashtags = " ".join(f"#{value.lstrip('#')}" for value in public.get("hashtags", []))
        if hashtags:
            caption = f"{caption}\n\n{hashtags}".strip()
        post = PostText(title=title, caption=caption, hashtags=list(tags),
                        contains_synthetic_media=settings.stories.synthetic_disclosure)
        if name == "youtube":
            outgoing = upload_metadata(post, settings.posting.youtube)
        elif name in {"tiktok", "instagram"}:
            maximum = TIKTOK_CAPTION_MAX if name == "tiktok" else INSTAGRAM_CAPTION_MAX
            combined = f"{post.title}\n\n{post.caption}".strip()
            if len(combined) > maximum:
                raise ValueError(f"The public description exceeds {LABELS[name]}'s caption limit")
            outgoing = {"caption": combined}
        elif name == "discord":
            combined = f"**{post.title}**\n{post.caption}".strip()
            if len(combined) > CONTENT_MAX:
                raise ValueError("The public description exceeds Discord's message limit")
            outgoing = {"content": combined}
        else:
            outgoing = {"description": f"{post.title}\n\n{post.caption}".strip()}
        check_public_text(SimpleNamespace(verdict={}, visual="", words=[], transcript=""), outgoing, settings)
        return post, outgoing

    async def _publish_one(self, project, name):
        pid, identity = project["id"], self.studio.content_fingerprint(project["id"])
        destination = self._destination(name)
        prior = project.get("publishing", {}).get(name, {})
        if prior.get("account_id") and prior["account_id"] != destination["account_id"]:
            self.errors[name] = "The destination account changed. Queue this story again for the new account."
            return
        credential_hash = self._credentials(name)
        settings = self._publisher_settings()
        post, outgoing = self._post(project, name, settings)
        video = self.studio._inside(pid, project["output"]["video_path"])
        digest = await asyncio.to_thread(_digest_file, video)
        token = await self.oauth.access_token(name) if name in {"youtube", "tiktok"} else ""
        if credential_hash != self._credentials(name):
            self.identities.pop(name, None)
            return  # token refresh/reconnection must be rebound to its verified account
        bound_tokens = _BoundTokens(self.tokens)
        bound_oauth = _BoundOAuth(name, token)
        publisher = build_publishers(settings, self.http, bound_tokens, bound_oauth)[name]
        manifest = {"project_id": pid, "content_hash": identity, "file_sha256": digest,
                    "account_id": destination["account_id"], "account_label": destination["account_label"],
                    "platform": name, "created_at": time.time(), "metadata": outgoing,
                    "video_path": video.name}
        directory = self.studio._directory(pid)
        manifest_path = directory / f"publish-{name}.json"
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        temporary.replace(manifest_path)
        self.studio.record_publish(pid, name, "uploading", content_hash=identity, account_id=destination["account_id"])
        self._publishing = True
        try:
            result = await publisher.publish(video, post)
            if result.ok and result.remote_id:
                url = result.url
                if name == "youtube" and project["output"].get("width", 0) > project["output"].get("height", 0):
                    url = f"https://youtube.com/watch?v={result.remote_id}"
                self.studio.record_publish(pid, name, "published", external_id=result.remote_id,
                                           url=url, content_hash=identity, account_id=destination["account_id"])
                self.errors.pop(name, None)
            else:
                # Existing publishers collapse transport/processing failures into one
                # result. We cannot prove that no remote post was created.
                self.studio.record_publish(pid, name, "uncertain", content_hash=identity,
                                           error="Upload result is uncertain. Check the destination account before retrying.")
                self.errors[name] = "Upload result is uncertain; check the destination account"
        except asyncio.CancelledError:
            self.studio.record_publish(pid, name, "uncertain", content_hash=identity,
                                       error="Upload interrupted. Check the destination account before retrying.")
            raise
        except Exception as exc:
            logger.warning("story upload %s failed (%s)", name, type(exc).__name__)
            self.studio.record_publish(pid, name, "uncertain", content_hash=identity,
                                       error="Upload result is uncertain. Check the destination account before retrying.")
            self.errors[name] = "Upload result is uncertain; check the destination account"
        finally:
            self._publishing = False

    async def tick(self):
        if (self._tick_lock.locked() or not self.settings.stories.enabled
                or not self.settings.businesses.hollow_enabled):
            return
        async with self._tick_lock:
            await self.initialize()
            cfg = self.settings.stories
            for project in sorted(self.studio.projects, key=lambda row: row.get("created_at", 0)):
                identity = self.studio.content_fingerprint(project["id"])
                approved = project.get("review", {}).get("passed") is True and project["review"].get("content_hash") == identity
                if cfg.auto_render and approved and project.get("status") == "draft" and not self.studio.busy:
                    try:
                        self.studio.render(project["id"])
                    except (StoryBusy, ValueError) as exc:
                        self.errors["render"] = str(exc)[:ERR_SNIPPET]
                    continue
                if not approved or project.get("status") != "ready":
                    continue
                for name in PLATFORMS:
                    record = project.get("publishing", {}).get(name, {})
                    current = record.get("content_hash") == identity
                    queued = current and record.get("status") == "pending"
                    automatic = cfg.auto_publish and name in cfg.publish_destinations and not current
                    if not queued and not automatic:
                        continue
                    destination = self._destination(name)
                    if not destination["ready"]:
                        self.errors[name] = destination["reason"]
                        continue
                    supported, reason = self._supported(project, name)
                    eligible, limit_reason = self._limits(name, time.time())
                    if not supported or not eligible:
                        self.errors[name] = reason or limit_reason
                        continue
                    try:
                        if not queued:
                            self.studio.record_publish(project["id"], name, "pending", content_hash=identity,
                                                       account_id=destination["account_id"])
                        await self._publish_one(self.studio.get(project["id"]), name)
                    except (OSError, ValueError, KeyError, StoryBusy, httpx.HTTPError, PublishError) as exc:
                        self.errors[name] = f"Story publication preflight failed ({type(exc).__name__}); edit or queue the story again"
                        logger.warning("story publication preflight %s failed (%s)", name, type(exc).__name__)
                        saved = self.studio.get(project["id"])
                        pending = saved.get("publishing", {}).get(name, {}) if saved else {}
                        if pending.get("status") == "pending" and pending.get("content_hash") == identity:
                            self.studio.record_publish(project["id"], name, "failed", content_hash=identity,
                                                       error=self.errors[name])
