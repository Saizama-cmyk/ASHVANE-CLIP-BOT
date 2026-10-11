"""Authenticated Stories API; inherits the dashboard's profile and action guards."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .config import merge_incoming
from .stories import StoryBusy

logger = logging.getLogger("clipbot.story_api")


def install_story_routes(app, ctx) -> None:
    router = APIRouter(prefix="/api/stories")

    def studio():
        result = getattr(ctx.pipeline, "stories", None)
        if result is None:
            raise HTTPException(503, "Stories is still starting")
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

    @router.post("/projects")
    async def create(request: Request):
        data = await body(request, {"topic", "genre", "format", "duration_s", "voice"})
        cfg = ctx.settings.stories
        return operation(studio().create, data.get("topic"), data.get("genre", cfg.default_genre),
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
