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
import tempfile
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, StreamingResponse

from .util import spawn, terminate
from .sweeper import safe_cleanup_path

logger = logging.getLogger("clipbot.music_api")
IDENT = r"[a-zA-Z0-9_-]+"
UUID = r"[0-9a-f-]{36}"
REFERENCE_UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
READ = re.compile(rf"(?:status|songs(?:/{IDENT})?|jobs/{IDENT}|renders|voices|process/jobs/{IDENT}|references(?:/{REFERENCE_UUID})?|rap/capabilities|rap/jobs/{IDENT}|reaper/(?:status|projects(?:/{UUID})?|listening/{UUID}))\Z")
WRITE = re.compile(rf"(?:create|process|jobs/{IDENT}/cancel|process/jobs/{IDENT}/cancel|references/(?:describe|{REFERENCE_UUID}/(?:analyze|cancel))|rap/(?:draft|describe)|reaper/projects(?:/{UUID}/(?:open|export|edit|validate|cancel|revisions/{UUID}/listen))?|reaper/listening/{UUID}/cancel)\Z")
MEDIA = re.compile(rf"/(?:media/{IDENT}|download/{IDENT}|renders/(?:media|download)/{IDENT}|references/media/{REFERENCE_UUID}|reaper/(?:media|download)/{UUID}/{UUID})\Z")


class MusicBridge:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = asyncio.Lock()
        self.launcher = None
        self.producer = None
        self.message = "Stopped"
        self.started = False
        self.reference_uploads = asyncio.Semaphore(ctx.settings.music.reference_upload_slots)

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

    async def upload_reference(self, request):
        """Bound and spool the incoming body before forwarding to the fixed service."""
        require_running(self.ctx)
        cfg = self.cfg
        encoded = request.headers.get("x-file-name", "")
        if re.search(r"%(?![0-9a-fA-F]{2})", encoded):
            raise HTTPException(422, "Invalid reference filename")
        try:
            name = unquote(encoded, errors="strict")
        except UnicodeError as exc:
            raise HTTPException(422, "Invalid reference filename") from exc
        if (not name or len(name) > cfg.reference_filename_max_chars or name in {".", ".."}
                or any(char in name for char in ("/", "\\", ":", "\x00", "\r", "\n"))):
            raise HTTPException(422, "Choose a reference with a simple filename")
        if Path(name).suffix.lower() not in cfg.reference_extensions:
            raise HTTPException(415, "Choose a supported audio or video reference")
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isdecimal():
                raise HTTPException(422, "Invalid reference size")
            if int(length) > cfg.reference_upload_max_bytes:
                raise HTTPException(413, "Music reference exceeds the configured size limit")
        root = (getattr(self.ctx, "paths", None) or self.ctx.pipeline.paths).work / "music-reference-uploads"
        if not safe_cleanup_path(root):
            raise HTTPException(503, "Music reference temporary storage is unavailable")
        async with asyncio.timeout(cfg.reference_upload_timeout_s), self.reference_uploads:
            await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
            # The temporary file is deleted even after a disconnect or rejected upload.
            with tempfile.TemporaryFile(dir=root) as file:
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > cfg.reference_upload_max_bytes:
                        raise HTTPException(413, "Music reference exceeds the configured size limit")
                    write = asyncio.create_task(asyncio.to_thread(file.write, chunk))
                    try:
                        await asyncio.shield(write)
                    except asyncio.CancelledError:
                        await asyncio.gather(write, return_exceptions=True)
                        raise
                if not size or (length is not None and size != int(length)):
                    raise HTTPException(422, "Music reference is empty or its transfer was incomplete")
                require_running(self.ctx)
                await asyncio.to_thread(file.seek, 0)

                async def body():
                    while True:
                        read = asyncio.create_task(asyncio.to_thread(file.read, cfg.chunk_bytes))
                        try:
                            chunk = await asyncio.shield(read)
                        except asyncio.CancelledError:
                            await asyncio.gather(read, return_exceptions=True)
                            raise
                        if not chunk:
                            break
                        yield chunk

                try:
                    async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                                 timeout=cfg.reference_upload_timeout_s) as client:
                        headers = {"X-Local-Song-Lab": "1", "X-File-Name": quote(name, safe=""),
                                   "Content-Type": "application/octet-stream", "Content-Length": str(size)}
                        async with client.stream("POST", self.base + "/api/references/upload", headers=headers, content=body()) as response:
                            raw = bytearray()
                            async for chunk in response.aiter_bytes(cfg.chunk_bytes):
                                raw.extend(chunk)
                                if len(raw) > cfg.response_max_bytes:
                                    raise HTTPException(502, "Music reference response exceeded its limit")
                            try:
                                result = json.loads(raw)
                            except (ValueError, UnicodeError) as exc:
                                raise HTTPException(502, "Music reference service returned an invalid response") from exc
                            if not isinstance(result, dict):
                                raise HTTPException(502, "Music reference service returned an invalid response")
                            if response.status_code >= 400:
                                raise HTTPException(response.status_code, str(result.get("error", "Music reference could not be saved")))
                            return self.rewrite(result)
                except httpx.HTTPError as exc:
                    raise HTTPException(503, "Music reference transfer failed. Check saved references before retrying.") from exc

    async def reference_context(self, data):
        """Resolve reference observations before spending local model/generation time."""
        from .creative_tools import text
        ident = data.get("reference_id", "")
        notes = text(data.get("reference_notes", ""), "Reference direction", self.cfg.reference_notes_max_chars)
        if not isinstance(ident, str) or (ident and not re.fullmatch(REFERENCE_UUID, ident)):
            raise HTTPException(422, "Select a saved music reference")
        if not ident:
            return {"what_to_borrow": notes} if notes else {}
        record = await self.call("GET", "/api/references/" + ident)
        if not isinstance(record, dict) or record.get("id") != ident:
            raise HTTPException(502, "Music reference service returned the wrong reference")
        if record.get("status") != "completed":
            raise HTTPException(409, "Wait for this reference to finish analyzing, or select no reference")
        return {"what_to_borrow": notes, "tempo_estimate_bpm": record.get("tempo_bpm"),
                "analysis_note": record.get("analysis_note", ""),
                "description": record.get("caption", ""), "style_hint": record.get("style_hint", ""),
                "basis": "Saved local reference observations; tempo may be half/double time. A description is available only if a local listening job completed. Never copy source lyrics or assume voice cloning."}

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

    @router.get("/references/options")
    async def reference_options():
        return {"max_upload_bytes": service.cfg.reference_upload_max_bytes,
                "extensions": service.cfg.reference_extensions,
                "max_notes_chars": service.cfg.reference_notes_max_chars,
                "max_lyrics_file_bytes": service.cfg.lyrics_file_max_bytes,
                "poll_ms": service.cfg.poll_s * 1000}

    @router.post("/references/upload", status_code=202)
    async def upload_reference(request: Request):
        try:
            return await service.upload_reference(request)
        except TimeoutError as exc:
            raise HTTPException(408, "Reference transfer timed out. Check saved references before retrying.") from exc

    @router.post("/lyrics")
    async def lyrics(request: Request):
        from .creative_tools import creative_tools
        require_running(ctx)
        data = await read_body(request, ctx.settings.creative.request_max_bytes)
        reference = await service.reference_context(data)
        data.pop("reference_id", None)
        data.pop("reference_notes", None)
        return await creative_tools(ctx).lyrics(data, **({"reference": reference} if reference else {}))

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
                reference = await service.reference_context(data)
                mode = data.pop("lyrics_mode", "given")
                direction = data.pop("lyrics_direction", "")
                if mode not in {"given", "generated"}:
                    raise HTTPException(422, "Choose Generate or Use mine for lyrics")
                original = text(data.get("lyrics", ""), "Lyrics", ctx.settings.creative.music_lyrics_max_chars)
                style = text(data.get("style", ""), "Musical direction", ctx.settings.creative.music_style_max_chars)
                if (mode == "generated" and not original) or not style:
                    generated = await creative_tools(ctx).lyrics({"style": style, "direction": direction,
                        "duration_seconds": data.get("duration_seconds", ctx.settings.creative.music_duration_s),
                        "mode": data.get("mode", "general") if mode == "generated" else "instrumental"},
                        **({"reference": reference} if reference else {}))
                    if mode == "generated" and not original:
                        data["lyrics"] = generated["lyrics"]
                    if not style:
                        data["style"] = generated["style"]
                    if not data.get("title", "").strip():
                        data["title"] = generated["title"]
            result = await service.call("POST", "/api/" + path, data)
            return JSONResponse(service.rewrite(result), status_code=HTTPStatus.ACCEPTED if path.endswith(("/edit", "/export", "/listen", "/analyze", "/describe")) or path in {"create", "process"} else HTTPStatus.OK)
        raise HTTPException(404, "Unknown music operation")

    app.include_router(router)
