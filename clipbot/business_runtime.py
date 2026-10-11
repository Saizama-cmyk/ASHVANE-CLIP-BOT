"""Independent, persisted business controls under the dashboard's auth/action guards."""
from __future__ import annotations

import asyncio
import importlib
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse

from .config import merge_incoming

logger = logging.getLogger("clipbot.business_runtime")
BUSINESSES = {"clips": ("Surge", "surge_enabled"), "stories": ("Hollow", "hollow_enabled"),
              "music": ("Resonance", "resonance_enabled"), "social": ("Social Studio", "social_enabled")}
RUNTIME_HOOKS = {"music": ("music_api", "music_runtime_state", "set_music_running"),
                 "social": ("social_api", "social_runtime_state", "set_social_running")}


def _work_business(path: str, method: str) -> str | None:
    if method != "POST":
        return None
    if path in {"/api/research/refresh", "/api/research/draft", "/api/clip_import/run",
                "/api/studio/render", "/api/analytics/refresh", "/api/publishing/batch"}:
        return "clips"
    if path.startswith("/api/clips/") and path.endswith("/publish"):
        return "clips"
    if path == "/api/stories" or (path.startswith("/api/stories/") and
            path.rsplit("/", 1)[-1] in {"render", "review", "retry", "publish"}):
        return "stories"
    return None


class _BusinessWorkGuard:
    def __init__(self, app, ctx):
        self.app, self.ctx = app, ctx

    async def __call__(self, scope, receive, send):
        business = _work_business(scope.get("path", ""), scope.get("method", ""))
        if scope["type"] != "http" or business is None:
            return await self.app(scope, receive, send)
        pipeline = self.ctx.pipeline
        if not pipeline.business_enabled(business) or business in pipeline._business_transition:
            response = JSONResponse({"detail": "This business is stopped or changing state. Start it from the business switcher."},
                                    status_code=409)
            return await response(scope, receive, send)
        task = asyncio.current_task()
        # Surge uploads lack durable uncertainty records. Let the current request
        # finish while stopping all new intake. Hollow has explicit uncertain states.
        drain = business == "clips" and scope["path"].endswith("/publish")
        pipeline._business_requests[business][task] = drain
        started = False

        async def wrapped_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except asyncio.CancelledError:
            if started:
                raise
            response = JSONResponse({"detail": "Business stopped. Saved work is kept."}, status_code=409)
            await response(scope, receive, send)
        finally:
            pipeline._business_requests[business].pop(task, None)


def install_business_runtime_routes(app, ctx) -> None:
    router = APIRouter(prefix="/api/businesses")
    lock = asyncio.Lock()
    runtime_tasks: set[asyncio.Task] = set()
    ctx.business_runtime_tasks = runtime_tasks
    runtime_locks = {business: asyncio.Lock() for business in RUNTIME_HOOKS}
    runtime_errors: dict[str, str] = {}

    async def state():
        rows = []
        for business in ("clips", "stories"):
            name, _field = BUSINESSES[business]
            rows.append({"id": business, "name": name, **ctx.pipeline.business_state(business)})
        for business, (module_name, state_hook, _set_hook) in RUNTIME_HOOKS.items():
            name, field = BUSINESSES[business]
            module = importlib.import_module(f".{module_name}", package=__package__)
            runtime = await getattr(module, state_hook)(ctx)
            rows.append({"id": business, "name": name, **runtime,
                         "enabled": getattr(ctx.settings.businesses, field)})
            if business in runtime_errors:
                rows[-1]["message"] = runtime_errors[business]
        return {"businesses": rows}

    async def change_runtime(business, enabled):
        module_name, _state_hook, set_hook = RUNTIME_HOOKS[business]
        try:
            module = importlib.import_module(f".{module_name}", package=__package__)
            async with runtime_locks[business]:
                # A later click supersedes an older transition waiting for the lock.
                if enabled == getattr(ctx.settings.businesses, BUSINESSES[business][1]):
                    await getattr(module, set_hook)(ctx, enabled)
                    runtime_errors.pop(business, None)
        except Exception as exc:
            runtime_errors[business] = f"Business transition failed: {exc}"
            logger.exception("%s business transition failed", business)

    @router.get("")
    async def businesses():
        return await state()

    @router.post("/{business}")
    async def toggle(business: str, request: Request):
        if business not in BUSINESSES:
            raise HTTPException(404, "Unknown business")
        try:
            data = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "Send an enabled boolean") from exc
        if not isinstance(data, dict) or set(data) != {"enabled"} or not isinstance(data["enabled"], bool):
            raise HTTPException(422, "Send only an enabled boolean")
        async with lock:
            settings = merge_incoming(ctx.settings, {"businesses": {BUSINESSES[business][1]: data["enabled"]}})
            await ctx.commit_settings(settings)
            if business in RUNTIME_HOOKS:
                task = asyncio.create_task(change_runtime(business, data["enabled"]), name=f"{business}-business-runtime")
                runtime_tasks.add(task)
                task.add_done_callback(runtime_tasks.discard)
            else:
                ctx.pipeline.request_business_reconcile()
            # Transitions drain native inference/uploads in the background. Return
            # promptly so the user can still operate another business independently.
            await asyncio.sleep(0)
            return {"ok": True, **await state()}

    app.add_middleware(_BusinessWorkGuard, ctx=ctx)
    app.include_router(router)


async def close_business_runtime(ctx) -> None:
    tasks = list(getattr(ctx, "business_runtime_tasks", ()))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
