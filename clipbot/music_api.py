"""Authenticated, bounded adapter to the existing local music workstation.

The phone talks to Ashvane, never directly to an unauthenticated studio port.
Only known studio routes are forwarded; model text cannot select URLs or files.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from http import HTTPStatus
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, StreamingResponse

from .util import spawn, terminate

logger = logging.getLogger("clipbot.music_api")
IDENT = r"[a-zA-Z0-9_-]+"
UUID = r"[0-9a-f-]{36}"
READ = re.compile(rf"(?:status|songs(?:/{IDENT})?|jobs/{IDENT}|renders|voices|process/jobs/{IDENT}|rap/capabilities|rap/jobs/{IDENT}|reaper/(?:status|projects(?:/{UUID})?|listening/{UUID}))\Z")
WRITE = re.compile(rf"(?:create|process|jobs/{IDENT}/cancel|process/jobs/{IDENT}/cancel|rap/(?:draft|describe)|reaper/projects(?:/{UUID}/(?:open|export|edit|validate|cancel|revisions/{UUID}/listen))?|reaper/listening/{UUID}/cancel)\Z")
MEDIA = re.compile(rf"/(?:media/{IDENT}|download/{IDENT}|renders/(?:media|download)/{IDENT}|reaper/(?:media|download)/{UUID}/{UUID})\Z")


class MusicBridge:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = asyncio.Lock()
        self.launcher = None
        self.producer = None
        self.message = "Stopped"
        self.started = False

    @property
    def cfg(self):
        return self.ctx.settings.music

    @property
    def base(self):
        return f"http://127.0.0.1:{self.cfg.bridge_port}"

    async def call(self, method: str, path: str, payload=None):
        raw = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        if raw is not None and len(raw) > self.cfg.request_max_bytes:
            raise HTTPException(413, "Music request is too large")
        headers = {"X-Local-Song-Lab": "1", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=self.cfg.request_timeout_s) as client:
                async with client.stream(method, self.base + path, content=raw, headers=headers) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes(self.cfg.chunk_bytes):
                        body.extend(chunk)
                        if len(body) > self.cfg.response_max_bytes:
                            raise HTTPException(502, "Local studio response exceeded its limit")
                    try:
                        data = json.loads(body)
                    except (ValueError, UnicodeError) as exc:
                        raise HTTPException(502, "Local studio returned an invalid response") from exc
                    if response.status_code >= 400:
                        detail = data.get("error", data.get("detail", "Local studio operation failed")) if isinstance(data, dict) else "Local studio operation failed"
                        raise HTTPException(response.status_code, str(detail))
                    return data
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Local Song Lab is unavailable. Start Resonance or check its studio settings.") from exc

    def rewrite(self, value):
        if isinstance(value, list):
            return [self.rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: ("/api/music" + item if isinstance(item, str) and MEDIA.fullmatch(item) else
                          "" if key.endswith("_url") and isinstance(item, str) and item.startswith(("http:", "https:", "file:")) else self.rewrite(item))
                    for key, item in value.items()}
        return value

    async def start(self):
        async with self.lock:
            try:
                await self.call("GET", "/api/status")
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                root = Path(self.cfg.root_dir).expanduser().resolve()
                script = root / "app" / "launch.py"
                python = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "python.exe"
                if not script.is_file() or (getattr(sys, "frozen", False) and not python.is_file()):
                    raise HTTPException(503, "Restore the existing LocalSongLab installation and Python runtime first")
                executable = str(python) if python.is_file() else sys.executable
                self.launcher = await spawn(executable, str(script), "--no-browser", cwd=str(root),
                                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                deadline = asyncio.get_running_loop().time() + self.cfg.launch_timeout_s
                while True:
                    try:
                        await self.call("GET", "/api/status")
                        break
                    except HTTPException:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise HTTPException(503, "Local Song Lab did not start; check its app/server.log")
                        await asyncio.sleep(self.cfg.poll_s)
            await self.call("POST", "/api/runtime", {"enabled": True})
            self.started = True
            self.message = "Running"

    async def stop(self):
        async with self.lock:
            if getattr(self.ctx, "creative_tools", None):
                await self.ctx.creative_tools.cancel_business("music")
            if self.producer:
                await self.producer.close()
            try:
                await self.call("POST", "/api/runtime", {"enabled": False})
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
            self.message = "Stopped"
            self.started = False


def bridge(ctx) -> MusicBridge:
    if not hasattr(ctx, "music_bridge"):
        ctx.music_bridge = MusicBridge(ctx)
    return ctx.music_bridge


async def set_music_running(ctx, enabled: bool):
    await (bridge(ctx).start() if enabled else bridge(ctx).stop())


async def music_runtime_state(ctx):
    service = bridge(ctx)
    try:
        state = await service.call("GET", "/api/status")
        creative = getattr(ctx, "creative_tools", None)
        busy = bool(state.get("busy")) or bool(service.producer and service.producer.busy) or bool(creative and creative.tasks["music"])
        enabled = ctx.settings.businesses.resonance_enabled
        if service.producer and service.producer.error:
            return {"running": False, "busy": busy, "message": service.producer.error}
        return {"running": bool(enabled and state.get("ready")), "busy": busy,
                "message": "Stopping · finishing current work" if not enabled and busy else
                str(state.get("message") or service.message) if enabled else "Stopped"}
    except HTTPException:
        return {"running": False, "busy": False, "message": "Studio unavailable" if ctx.settings.businesses.resonance_enabled else "Stopped"}


async def close_music(ctx):
    service = getattr(ctx, "music_bridge", None)
    if service:
        if service.producer:
            await service.producer.close()
        if service.started:
            try:
                await service.stop()
            except HTTPException:
                logger.exception("Owned music runtime did not confirm shutdown")
        if service.launcher and service.launcher.returncode is None:
            await terminate(service.launcher, service.cfg.poll_s)


async def read_body(request: Request, limit: int):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, "Music request is too large")
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Send a JSON object") from exc


def require_running(ctx):
    if not ctx.settings.businesses.resonance_enabled:
        raise HTTPException(409, "Resonance is stopped. Start it from the business switcher.")


def install_music_routes(app, ctx):
    router = APIRouter(prefix="/api/music")
    service = bridge(ctx)
    from .music_producer import MusicProducer
    service.producer = MusicProducer(ctx, service)

    @router.post("/lyrics")
    async def lyrics(request: Request):
        from .creative_tools import creative_tools
        require_running(ctx)
        return await creative_tools(ctx).lyrics(await read_body(request, ctx.settings.creative.request_max_bytes))

    @router.post("/produce", status_code=202)
    async def produce(request: Request):
        require_running(ctx)
        return service.producer.create(await read_body(request, service.cfg.request_max_bytes))

    @router.get("/production-jobs/{ident}")
    async def production_job(ident: str):
        return service.producer.get(ident)

    @router.post("/production-jobs/{ident}/cancel")
    async def cancel_production(ident: str):
        return await service.producer.cancel(ident)

    @router.api_route("/{path:path}", methods=["GET", "POST"])
    async def proxy(path: str, request: Request):
        media_path = "/" + path
        if request.method == "GET" and MEDIA.fullmatch(media_path):
            client = httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=service.cfg.request_timeout_s)
            headers = {"Range": request.headers["range"]} if "range" in request.headers else {}
            try:
                response = await client.send(client.build_request("GET", service.base + media_path, headers=headers), stream=True)
                if response.status_code >= 400:
                    raise HTTPException(response.status_code, "Music preview is unavailable")
                length = response.headers.get("content-length")
                if length and int(length) > service.cfg.media_max_bytes:
                    raise HTTPException(413, "Music preview exceeds the configured size limit")
            except (httpx.HTTPError, ValueError, HTTPException) as exc:
                await client.aclose()
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(503, "Music preview is unavailable") from exc

            async def audio():
                count = 0
                try:
                    async for chunk in response.aiter_bytes(service.cfg.chunk_bytes):
                        count += len(chunk)
                        if count > service.cfg.media_max_bytes:
                            raise RuntimeError("Music media exceeded its size limit")
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()
            safe = {key: value for key, value in response.headers.items() if key in
                    {"content-type", "content-length", "content-range", "accept-ranges", "content-disposition"}}
            return StreamingResponse(audio(), status_code=response.status_code, headers=safe)
        if request.method == "GET" and READ.fullmatch(path):
            return service.rewrite(await service.call("GET", "/api/" + path))
        if request.method == "POST" and WRITE.fullmatch(path):
            if not path.endswith(("/cancel", "/validate", "/open")):
                require_running(ctx)
            data = await read_body(request, service.cfg.request_max_bytes)
            if path == "create":
                from .creative_tools import creative_tools, text
                mode = data.pop("lyrics_mode", "given")
                direction = data.pop("lyrics_direction", "")
                if mode not in {"given", "generated"}:
                    raise HTTPException(422, "Choose Generate or Use mine for lyrics")
                original = text(data.get("lyrics", ""), "Lyrics", ctx.settings.creative.music_lyrics_max_chars)
                style = text(data.get("style", ""), "Musical direction", ctx.settings.creative.music_style_max_chars)
                if (mode == "generated" and not original) or not style:
                    generated = await creative_tools(ctx).lyrics({"style": style, "direction": direction,
                        "duration_seconds": data.get("duration_seconds", ctx.settings.creative.music_duration_s),
                        "mode": data.get("mode", "general") if mode == "generated" else "instrumental"})
                    if mode == "generated" and not original:
                        data["lyrics"] = generated["lyrics"]
                    if not style:
                        data["style"] = generated["style"]
                    if not data.get("title", "").strip():
                        data["title"] = generated["title"]
            result = await service.call("POST", "/api/" + path, data)
            return JSONResponse(service.rewrite(result), status_code=HTTPStatus.ACCEPTED if path.endswith(("/edit", "/export", "/listen")) or path in {"create", "process"} else HTTPStatus.OK)
        raise HTTPException(404, "Unknown music operation")

    app.include_router(router)
