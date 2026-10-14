"""Supervisor controls inherit the dashboard profile, CSRF and host guards."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.responses import Response


def install_supervisor_routes(app, ctx):
    def service():
        supervisor = getattr(ctx, "supervisor", None)
        if supervisor is None:
            raise HTTPException(503, "Supervisor runtime is unavailable")
        return supervisor

    async def body(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > ctx.settings.supervisor.response_max_bytes:
                raise HTTPException(413, "Supervisor request exceeds its size limit")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Use a JSON object")
        if not isinstance(result, dict):
            raise HTTPException(400, "Use a JSON object")
        return result

    @app.get("/api/supervisor")
    async def status():
        return service().snapshot()

    @app.post("/api/supervisor/master")
    async def master(request: Request):
        data = await body(request)
        if type(data.get("enabled")) is not bool:
            raise HTTPException(400, "enabled must be a boolean")
        service()
        settings = ctx.settings.model_copy(deep=True)
        settings.supervisor.enabled = data["enabled"]
        await ctx.commit_settings(settings)
        return service().snapshot()

    @app.post("/api/supervisor/run")
    async def run(request: Request):
        data = await body(request)
        try:
            return service().run(data.get("goal", ""))
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/supervisor/cancel")
    async def cancel(request: Request):
        await body(request)
        await service().cancel()
        return service().snapshot()

    @app.post("/api/supervisor/rollback")
    async def rollback(request: Request):
        data = await body(request)
        try:
            return await service().rollback(data.get("job_id"))
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/supervisor/dataset/{split}")
    async def dataset(split: str):
        try:
            content = service().memory.export(split)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return Response(content, media_type="application/x-ndjson",
                        headers={"Content-Disposition": f'attachment; filename="ashvane-{split}.jsonl"'})
