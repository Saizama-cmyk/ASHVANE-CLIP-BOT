"""Named business destination profiles; credentials never cross profile boundaries."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import uuid
import webbrowser
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Request

from .config import AccountsCfg, ConfigError, load_tokens, save_tokens, masked_dump, merge_incoming
from .publishers import PLATFORMS
from .publishers.base import PublishError
from .publishers.oauth import PLATFORMS as OAUTH_PLATFORMS

logger = logging.getLogger("clipbot.account_profiles")
BUSINESSES = {"clips": "Surge", "stories": "Hollow", "music": "Resonance"}
APP_FIELDS = {"youtube_client_id", "youtube_client_secret", "tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri"}


class AccountProfiles:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.path = pipeline.paths.data / "account-profiles.json"
        self.error = ""
        self.switching: set[str] = set()
        self.uploads = {business: 0 for business in BUSINESSES}
        self.ctx = None
        self._lock = asyncio.Lock()
        self.data = {"version": 1, "businesses": {business: {"active_profile_id": "default", "profiles": [
            {"id": "default", "name": f"{label} main", "description": "", "public_handles": {}, "accounts": {}}
        ]} for business, label in BUSINESSES.items()}}
        if self.path.exists():
            try:
                if self.path.stat().st_size > pipeline.settings.account_profiles.store_max_bytes * 2:
                    raise ValueError("Registry exceeds its storage limit")
                incoming = load_tokens(self.path)
                if not isinstance(incoming, dict) or incoming.get("version") != 1:
                    raise ValueError("Unsupported profile registry")
                for business in BUSINESSES:
                    group = incoming["businesses"][business]
                    rows = group["profiles"]
                    if not isinstance(rows, list) or not rows or len(rows) > pipeline.settings.account_profiles.max_profiles:
                        raise ValueError("Invalid profile list")
                    ids = []
                    for row in rows:
                        self._validate_id(row["id"])
                        self._metadata(row)
                        AccountsCfg.model_validate(row.get("accounts", {}))
                        ids.append(row["id"])
                    if len(set(ids)) != len(ids) or "default" not in ids or group["active_profile_id"] not in ids:
                        raise ValueError("Invalid profile ownership")
                self.data = incoming
            except (ConfigError, OSError, ValueError, KeyError, TypeError, HTTPException):
                self.error = "Saved account profiles could not be read. Publishing is held; the original file has been preserved."
                logger.exception("account profile registry could not be loaded")

    def _business(self, business):
        if business not in BUSINESSES:
            raise HTTPException(404, "Use Social Studio's client profiles for social accounts")
        return self.data["businesses"][business]

    def _validate_id(self, profile_id):
        if not isinstance(profile_id, str) or not (profile_id == "default" or re.fullmatch(r"[a-f0-9]{32}", profile_id)):
            raise ValueError("Invalid account profile ID")

    def active_id(self, business):
        return self._business(business)["active_profile_id"]

    active = active_id

    def _row(self, business, profile_id):
        group = self._business(business)
        row = next((row for row in group["profiles"] if row["id"] == profile_id), None)
        if row is None:
            raise HTTPException(404, "Account profile not found in this business")
        return row

    def get(self, business, profile_id):
        return copy.deepcopy({key: value for key, value in self._row(business, profile_id).items() if key != "accounts"})

    def _metadata(self, data):
        cfg = self.pipeline.settings.account_profiles
        result = {}
        for key, maximum in (("name", cfg.max_name_chars), ("description", cfg.max_description_chars)):
            if key not in data:
                continue
            value = data[key]
            if not isinstance(value, str) or len(value) > maximum or "\x00" in value or (key == "name" and not value.strip()):
                raise HTTPException(422, f"Invalid profile {key}")
            result[key] = value.strip()
        if "public_handles" in data:
            handles = data["public_handles"]
            if not isinstance(handles, dict) or set(handles) - set(PLATFORMS):
                raise HTTPException(422, "Choose supported public account links")
            if any(not isinstance(value, str) or len(value) > cfg.max_handle_chars or "\x00" in value for value in handles.values()):
                raise HTTPException(422, "Invalid public account link")
            result["public_handles"] = {key: value.strip() for key, value in handles.items()}
        return result

    def _save(self):
        if self.error:
            raise HTTPException(409, self.error)
        if len(json.dumps(self.data).encode("utf-8")) > self.pipeline.settings.account_profiles.store_max_bytes:
            raise HTTPException(409, "Account profile storage is full")
        save_tokens(self.path, self.data)

    def _section(self, business):
        return "accounts" if business == "clips" else "story_accounts"

    def _token_path(self, business, profile_id):
        if profile_id == "default":
            return self.pipeline.paths.tokens if business == "clips" else self.pipeline.paths.story_tokens
        return self.pipeline.paths.data / f"tokens-{business}-{profile_id}.json"

    def bind(self):
        """Called before business workers start; legacy stores retain their original paths."""
        p = self.pipeline
        p.scheduler.account_profiles = self
        p.story_publishing.account_profiles = self
        p.stories.account_profile_id = lambda: self.active_id("stories")
        p.oauth.profile_hold = lambda: self.held_reason("clips", self.active_id("clips"))
        p.story_oauth.profile_hold = lambda: self.held_reason("stories", self.active_id("stories"))
        if not self.error:
            for business in ("clips", "stories"):
                row = self._row(business, self.active_id(business))
                section = self._section(business)
                if row.get("accounts"):
                    setattr(p.settings, section, AccountsCfg.model_validate(row["accounts"]))
                else:
                    row["accounts"] = getattr(p.settings, section).model_dump()
            p.oauth.apply(p.settings)
            p.story_oauth.apply(p.settings)
            p.scheduler.apply(p.settings)
            p.story_publishing.apply(p.settings)
        self.apply(p.settings)

    def apply(self, settings):
        for business, tokens in (("clips", getattr(self.pipeline, "tokens", None)), ("stories", getattr(self.pipeline, "story_tokens", None))):
            if tokens is not None and not self.error:
                tokens.path = self._token_path(business, self.active_id(business))
                self._row(business, self.active_id(business))["accounts"] = getattr(settings, self._section(business)).model_dump()
        if not self.error:
            self._save()

    def _busy(self, business):
        p = self.pipeline
        if self.uploads[business] or business in self.switching:
            return True
        manager = getattr(p, "oauth" if business == "clips" else "story_oauth", None) if business != "music" else None
        if manager and (manager.pending() or getattr(manager, "_exchanging", 0)):
            return True
        if business == "clips" and (any(not task.done() for task in getattr(p, "_inflight", {}).values()) or
                                   getattr(p, "_publish_batch_lock", asyncio.Lock()).locked()):
            return True
        if business == "stories" and (getattr(getattr(p, "stories", None), "busy", False) or
                                     getattr(getattr(p, "story_publishing", None), "_tick_lock", asyncio.Lock()).locked()):
            return True
        if self.ctx is not None:
            creative = getattr(self.ctx, "creative_tools", None)
            if creative and any(not task.done() for task in creative.tasks.get(business, set())):
                return True
            if business == "music" and getattr(getattr(getattr(self.ctx, "music_bridge", None), "producer", None), "busy", False):
                return True
        return False

    def held_reason(self, business, owner="default"):
        if self.error:
            return self.error
        if business in self.switching:
            return "Account profile is changing; queued work is held"
        if (owner or "default") != self.active_id(business):
            return "This item belongs to another account profile. Switch back to its profile to publish it."
        return ""

    def require_current(self, business, expected=""):
        group = self._business(business)
        if self.error or business in self.switching:
            raise HTTPException(409, self.error or "Account profile is changing")
        if (expected and expected != self.active_id(business)) or (len(group["profiles"]) > 1 and not expected):
            raise HTTPException(409, "Account profiles changed. Use the profile's account panel to edit or connect its accounts.")

    async def _rollback(self, ctx, before, old_settings):
        self.data = before
        try:
            self._save()
            if ctx.settings is not old_settings:
                await ctx.commit_settings(old_settings)
            self.apply(old_settings)
        except Exception:
            self.error = "The account profile change could not be restored. Publishing is held; restart after checking storage."
            logger.exception("account profile rollback failed; publishing held")

    @asynccontextmanager
    async def upload(self, business):
        reason = self.held_reason(business, self.active_id(business))
        if reason:
            raise PublishError(reason)
        self.uploads[business] += 1
        try:
            yield
        finally:
            self.uploads[business] -= 1

    def state(self, business):
        group = self._business(business)
        output = []
        for row in group["profiles"]:
            active = row["id"] == group["active_profile_id"]
            connections = {}
            for platform in PLATFORMS:
                connection = {"ready": False, "account_id": "", "account_label": "", "reason": "Select this profile to check its connection"}
                if business == "music":
                    connection["reason"] = "Public artist link only; music distribution is not connected"
                elif active and not self.error:
                    if business == "stories" and hasattr(self.pipeline, "story_publishing"):
                        connection.update(self.pipeline.story_publishing._destination(platform))
                    elif hasattr(self.pipeline, "publishers"):
                        ready, reason = self.pipeline.publishers[platform].configured()
                        manager = self.pipeline.oauth
                        token = manager.tokens.get(platform)
                        connection.update(ready=ready, reason=reason, account_id=token.get("open_id", ""))
                connections[platform] = connection
            public = {key: copy.deepcopy(row.get(key, {} if key == "public_handles" else "")) for key in ("id", "name", "description", "public_handles")}
            if business != "music":
                snapshot = self.pipeline.settings.model_copy(deep=True)
                section = self._section(business)
                if not active:
                    setattr(snapshot, section, AccountsCfg.model_validate(row.get("accounts", {})))
                public["accounts"] = masked_dump(snapshot)[section]
            output.append(public | {"connections": connections})
        return {"profiles": output, "active_profile_id": group["active_profile_id"], "business": business,
                "connection_mode": "public_links" if business == "music" else "oauth", "error": self.error,
                "queue_policy": "Items stay bound to their original profile; changing profiles holds the other queues."}

    async def create(self, business, data):
        async with self._lock:
            if "accounts" in data:
                raise HTTPException(422, "Create the profile first, then edit its destination accounts")
            group = self._business(business)
            if len(group["profiles"]) >= self.pipeline.settings.account_profiles.max_profiles:
                raise HTTPException(409, "This business has reached its account profile limit")
            metadata = self._metadata(data)
            if not metadata.get("name"):
                raise HTTPException(422, "Give this account profile a name")
            accounts = {}
            if business != "music":
                current = getattr(self.pipeline.settings, self._section(business))
                accounts = {key: getattr(current, key) for key in APP_FIELDS}
            row = {"id": uuid.uuid4().hex, "description": "", "public_handles": {}, "accounts": accounts, **metadata}
            group["profiles"].append(row)
            try:
                self._save()
            except Exception:
                group["profiles"].remove(row)
                raise
            return self.state(business)

    async def edit(self, business, profile_id, data):
        async with self._lock:
            row = self._row(business, profile_id)
            before = copy.deepcopy(row)
            before_registry = copy.deepcopy(self.data)
            old_settings = self.ctx.settings if self.ctx is not None else self.pipeline.settings
            settings = None
            active = profile_id == self.active_id(business)
            if "accounts" in data:
                accounts = data["accounts"]
                if business == "music" or not isinstance(accounts, dict) or set(accounts) - set(AccountsCfg.model_fields):
                    raise HTTPException(422, "Choose supported destination account fields")
                if any(not isinstance(value, str) or len(value) > self.pipeline.settings.account_profiles.max_handle_chars for value in accounts.values()):
                    raise HTTPException(422, "Account fields must be bounded text")
                if active and self._busy(business):
                    raise HTTPException(409, "Finish current work and sign-in before changing account credentials")
                section = self._section(business)
                snapshot = self.pipeline.settings.model_copy(deep=True)
                if not active:
                    setattr(snapshot, section, AccountsCfg.model_validate(row.get("accounts", {})))
                settings = merge_incoming(snapshot, {section: accounts})
                row["accounts"] = getattr(settings, section).model_dump()
            row.update(self._metadata(data))
            try:
                self._save()
                if settings is not None and active:
                    if self.ctx is None:
                        raise HTTPException(503, "Account settings are still starting")
                    self.switching.add(business)
                    await self.ctx.commit_settings(settings)
                    self.apply(settings)
            except Exception:
                if self.ctx is not None:
                    await self._rollback(self.ctx, before_registry, old_settings)
                else:
                    row.clear()
                    row.update(before)
                    self._save()
                raise
            finally:
                self.switching.discard(business)
            return self.state(business)

    async def activate(self, ctx, business, profile_id):
        async with self._lock:
            target = self._row(business, profile_id)
            if self.error:
                raise HTTPException(409, self.error)
            if profile_id == self.active_id(business):
                return self.state(business)
            if self._busy(business):
                raise HTTPException(409, "Finish or stop this business's current work and complete or cancel its sign-in before changing profiles")
            self.switching.add(business)
            before = copy.deepcopy(self.data)
            old_settings = ctx.settings
            try:
                if business != "music":
                    section = self._section(business)
                    self._row(business, self.active_id(business))["accounts"] = getattr(ctx.settings, section).model_dump()
                    settings = ctx.settings.model_copy(deep=True)
                    setattr(settings, section, AccountsCfg.model_validate(target["accounts"]))
                else:
                    settings = ctx.settings
                self._business(business)["active_profile_id"] = profile_id
                self._save()
                if business != "music":
                    await ctx.commit_settings(settings)
                self.apply(settings)
            except Exception:
                await self._rollback(ctx, before, old_settings)
                raise
            finally:
                self.switching.discard(business)
            return self.state(business)


def account_profiles(ctx):
    service = getattr(ctx.pipeline, "account_profiles", None)
    if service is None:
        service = ctx.pipeline.account_profiles = AccountProfiles(ctx.pipeline)
    service.ctx = ctx
    return service


def install_account_profile_routes(app, ctx):
    if service := getattr(ctx.pipeline, "account_profiles", None):
        service.ctx = ctx
    router = APIRouter(prefix="/api/account-profiles")

    async def body(request):
        from .music_api import read_body
        data = await read_body(request, ctx.settings.account_profiles.request_max_bytes)
        if set(data) - {"name", "description", "public_handles", "accounts"}:
            raise HTTPException(422, "Unexpected account profile fields")
        return data

    @router.get("/{business}")
    async def state(business: str):
        return account_profiles(ctx).state(business)

    @router.post("/{business}")
    async def create(business: str, request: Request):
        return await account_profiles(ctx).create(business, await body(request))

    @router.patch("/{business}/{profile_id}")
    async def edit(business: str, profile_id: str, request: Request):
        return await account_profiles(ctx).edit(business, profile_id, await body(request))

    @router.post("/{business}/{profile_id}/activate")
    async def activate(business: str, profile_id: str):
        return await account_profiles(ctx).activate(ctx, business, profile_id)

    @router.post("/{business}/{profile_id}/cancel-signin")
    async def cancel_signin(business: str, profile_id: str):
        service = account_profiles(ctx)
        service._row(business, profile_id)
        if profile_id != service.active_id(business):
            raise HTTPException(409, "Select this profile before changing its sign-in")
        if business in {"clips", "stories"}:
            manager = ctx.pipeline.oauth if business == "clips" else ctx.pipeline.story_oauth
            for platform in ("youtube", "tiktok"):
                manager.cancel_pending(platform)
        return service.state(business)

    @router.post("/{business}/{profile_id}/{platform}/{action}")
    async def connection(business: str, profile_id: str, platform: str, action: str, request: Request):
        service = account_profiles(ctx)
        if business not in {"clips", "stories"} or platform not in OAUTH_PLATFORMS or action not in {"open", "paste", "disconnect"}:
            raise HTTPException(404, "Unsupported account connection")
        async with service._lock:
            service._row(business, profile_id)
            if profile_id != service.active_id(business):
                raise HTTPException(409, "The selected account profile changed. Open its account panel again.")
            manager = ctx.pipeline.oauth if business == "clips" else ctx.pipeline.story_oauth
            try:
                if action == "open":
                    url = manager.start_url(platform)
                    opened = await asyncio.to_thread(webbrowser.open, url)
                    return {"ok": True, "opened": bool(opened), "url": url}
                if action == "paste":
                    from .music_api import read_body
                    data = await read_body(request, ctx.settings.account_profiles.request_max_bytes)
                    if set(data) != {"url"} or not isinstance(data["url"], str):
                        raise HTTPException(422, "Paste the full callback address")
                    await manager.callback_from_url(platform, data["url"])
                else:
                    if service.uploads[business] or manager._exchanging:
                        raise HTTPException(409, "Wait for the account's current request to finish")
                    manager.disconnect(platform)
                if business == "stories":
                    ctx.pipeline.story_publishing.identities.pop(platform, None)
                return {"ok": True}
            except PublishError as exc:
                logger.warning("profile connection failed (%s)", type(exc).__name__)
                raise HTTPException(422, "Connection failed. Check the account's developer settings and start sign-in again.") from exc

    app.include_router(router)
