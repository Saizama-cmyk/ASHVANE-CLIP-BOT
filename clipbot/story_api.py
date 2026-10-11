"""Authenticated Stories API; inherits the dashboard's profile and action guards."""
from __future__ import annotations

import asyncio
import json
import logging
import webbrowser

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .config import AccountsCfg, masked_dump, merge_incoming
from .publishers.base import PublishError
from .publishers.oauth import PLATFORMS as OAUTH_PLATFORMS
from .stories import StoryBusy

logger = logging.getLogger("clipbot.story_api")


def install_story_routes(app, ctx) -> None:
    router = APIRouter(prefix="/api/stories")

    def studio():
        result = getattr(ctx.pipeline, "stories", None)
        if result is None:
            raise HTTPException(503, "Stories is still starting")
        from .creative_memory import creative_memory
        result.creative_context = lambda project: creative_memory(ctx).context("stories", account_profile_id=project.get("account_profile_id") or "default")
        return result

    def publisher():
        result = getattr(ctx.pipeline, "story_publishing", None)
        if result is None:
            raise HTTPException(503, "Story publishing is still starting")
        return result

    async def body(request: Request, allowed: set[str]) -> dict:
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > ctx.settings.stories.request_max_bytes:
                raise HTTPException(413, "Story request is too large")
        try:
            data = json.loads(payload or b"{}")
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "Send a JSON object") from exc
        if not isinstance(data, dict) or set(data) - allowed:
            raise HTTPException(422, "Unexpected story request fields")
        return data

    def oauth(platform: str):
        if platform not in OAUTH_PLATFORMS:
            raise HTTPException(404, "This destination does not use OAuth")
        result = getattr(ctx.pipeline, "story_oauth", None)
        if result is None:
            raise HTTPException(503, "Hollow accounts are still starting")
        return result

    def account_state():
        manager = oauth("youtube")
        own, effective = ctx.settings.story_accounts, manager.accounts
        apps = {}
        for name, identity, secret in (("youtube", "youtube_client_id", "youtube_client_secret"),
                                       ("tiktok", "tiktok_client_key", "tiktok_client_secret")):
            configured = bool(getattr(effective, identity) and getattr(effective, secret))
            apps[name] = {"configured": configured,
                          "inherited": configured and not getattr(own, identity) and not getattr(own, secret)}
        return {"accounts": masked_dump(ctx.settings)["story_accounts"],
                "account_profile_id": getattr(ctx.pipeline, "account_profiles", None).active_id("stories") if getattr(ctx.pipeline, "account_profiles", None) else "default",
                "oauth": {name: manager.connected(name) for name in OAUTH_PLATFORMS},
                "redirects": {name: manager.redirect_uri(name) for name in OAUTH_PLATFORMS},
                "app_credentials": apps,
                "destinations": publisher().state()["destinations"]}

    def account_changed(platform):
        publisher().identities.pop(platform, None)
        publisher().errors.pop(platform, None)

    @router.get("/accounts")
    async def accounts():
        return account_state()

    @router.put("/accounts")
    async def save_accounts(request: Request):
        if service := getattr(ctx.pipeline, "account_profiles", None):
            service.require_current("stories", request.headers.get("X-Account-Profile", ""))
        data = await body(request, set(AccountsCfg.model_fields))
        if any(not isinstance(value, str) for value in data.values()):
            raise HTTPException(422, "Account values must be text")
        try:
            settings = merge_incoming(ctx.settings, {"story_accounts": data})
        except ValidationError as exc:
            raise HTTPException(422, "Invalid Hollow account settings") from exc
        if service := getattr(ctx.pipeline, "account_profiles", None):
            await service.edit("stories", service.active_id("stories"), {"accounts": data})
        else:
            await ctx.commit_settings(settings)
        return account_state()

    @router.post("/accounts/{platform}/open")
    async def open_account(platform: str, request: Request):
        if service := getattr(ctx.pipeline, "account_profiles", None):
            service.require_current("stories", request.headers.get("X-Account-Profile", ""))
        manager = oauth(platform)
        try:
            url = manager.start_url(platform)
        except PublishError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        opened = await asyncio.to_thread(webbrowser.open, url)
        return {"ok": True, "opened": bool(opened), "url": url}

    @router.post("/accounts/{platform}/paste")
    async def paste_account(platform: str, request: Request):
        if service := getattr(ctx.pipeline, "account_profiles", None):
            service.require_current("stories", request.headers.get("X-Account-Profile", ""))
        manager = oauth(platform)
        data = await body(request, {"url"})
        if not isinstance(data.get("url"), str):
            raise HTTPException(422, "Paste the full callback address")
        try:
            await manager.callback_from_url(platform, data["url"])
        except (PublishError, httpx.HTTPError, ValueError) as exc:
            logger.warning("story sign-in failed (%s)", type(exc).__name__)
            return JSONResponse({"ok": False, "error": "Hollow sign-in failed. Check the callback address and developer credentials, then connect again."}, status_code=422)
        account_changed(platform)
        return {"ok": True}

    @router.post("/accounts/{platform}/disconnect")
    async def disconnect_account(platform: str, request: Request):
        if service := getattr(ctx.pipeline, "account_profiles", None):
            service.require_current("stories", request.headers.get("X-Account-Profile", ""))
        oauth(platform).disconnect(platform)
        account_changed(platform)
        return {"ok": True}

    def operation(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except StoryBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "Story not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            logger.exception("story persistence failed")
            raise HTTPException(500, "Could not save the story. Check storage and retry.") from exc

    @router.get("")
    async def state():
        return studio().state()

    @router.get("/publishing")
    async def publishing():
        return publisher().state()

    @router.put("/publishing")
    async def set_publishing(request: Request):
        data = await body(request, {"enabled", "destinations", "privacy"})
        if "enabled" in data and not isinstance(data["enabled"], bool):
            raise HTTPException(422, "enabled must be true or false")
        if "destinations" in data and (not isinstance(data["destinations"], list) or
                any(not isinstance(item, str) for item in data["destinations"])):
            raise HTTPException(422, "destinations must be platform IDs")
        changes = {target: data[source] for source, target in
                   (("enabled", "auto_publish"), ("destinations", "publish_destinations"), ("privacy", "publish_privacy")) if source in data}
        try:
            settings = merge_incoming(ctx.settings, {"stories": changes})
        except ValidationError as exc:
            raise HTTPException(422, "Choose supported destinations and a valid visibility") from exc
        await ctx.commit_settings(settings)
        return publisher().state()

    @router.post("/ideas")
    async def ideas(request: Request):
        from .creative_tools import creative_tools
        return await creative_tools(ctx).story_ideas(await body(request, {"genre", "format", "duration_s", "direction"}))

    @router.post("/projects")
    async def create(request: Request):
        from .creative_tools import creative_tools, text
        data = await body(request, {"topic", "topic_mode", "direction", "genre", "format", "duration_s", "voice"})
        cfg = ctx.settings.stories
        mode = data.get("topic_mode", "given")
        if mode not in {"given", "generated"}:
            raise HTTPException(422, "Choose Generate or Use mine for the premise")
        topic = text(data.get("topic", ""), "Story premise", cfg.max_topic_chars)
        if mode == "generated" and not topic:
            suggested = await creative_tools(ctx).story_ideas({key: data[key] for key in ("genre", "format", "duration_s", "direction") if key in data})
            topic = suggested["ideas"][0]["premise"]
        return operation(studio().create, topic, data.get("genre", cfg.default_genre),
                         data.get("format", cfg.default_format), data.get("duration_s", cfg.default_duration_s), data.get("voice", cfg.voice))

    @router.get("/projects/{project_id}")
    async def get(project_id: str):
        result = operation(studio().get, project_id)
        if result is None:
            raise HTTPException(404, "Story not found")
        return result

    @router.put("/projects/{project_id}")
    async def update(project_id: str, request: Request):
        data = await body(request, {"title", "script", "scenes", "public_copy"})
        return operation(studio().update, project_id, **data)

    @router.delete("/projects/{project_id}")
    async def delete(project_id: str):
        if not operation(studio().delete, project_id):
            raise HTTPException(404, "Story not found")
        return {"ok": True}

    @router.post("/projects/{project_id}/render")
    async def render(project_id: str):
        return operation(studio().render, project_id)

    @router.post("/projects/{project_id}/review")
    async def review(project_id: str):
        return operation(studio().review, project_id)

    @router.post("/projects/{project_id}/retry")
    async def retry(project_id: str):
        return operation(studio().retry, project_id)

    @router.post("/projects/{project_id}/cancel")
    async def cancel(project_id: str):
        return {"ok": operation(studio().cancel, project_id)}

    @router.post("/projects/{project_id}/publish")
    async def publish(project_id: str, request: Request):
        data = await body(request, {"destinations"})
        return operation(publisher().request_publish, project_id, data.get("destinations"))

    def media(project_id: str, kind: str):
        story = operation(studio().get, project_id)
        if story is None:
            raise HTTPException(404, "Story not found")
        if story.get("status") != "ready" or not story.get("output", {}).get(kind):
            raise HTTPException(409, "Render this story before previewing it")
        path = operation(studio()._inside, project_id, story["output"][kind])
        return FileResponse(path, media_type="video/mp4" if kind == "video_path" else "audio/mp4",
                            filename=f"ashvane-story-{project_id}.mp4" if kind == "video_path" else f"ashvane-story-{project_id}.m4a")

    @router.get("/projects/{project_id}/video")
    async def video(project_id: str):
        return media(project_id, "video_path")

    @router.get("/projects/{project_id}/audio")
    async def audio(project_id: str):
        return media(project_id, "audio_path")

    app.include_router(router)
