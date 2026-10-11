"""Exercise real authenticated routers with local engine/model calls replaced in-process."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    with tempfile.TemporaryDirectory(prefix="ashvane-workspace-contracts-") as folder:
        os.environ["CLIPBOT_HOME"] = folder
        from clipbot.app import ClipBotApp
        from clipbot.business_runtime import close_business_runtime
        from clipbot.config import Settings, save_settings
        from clipbot.dashboard.server import create_app
        from clipbot.social_api import social_studio
        import httpx

        settings = Settings()
        settings.app.data_dir = str(Path(folder) / "data")
        settings.app.start_with_windows = False
        settings.ai.auto_pull = False
        settings.businesses.surge_enabled = False
        settings.businesses.hollow_enabled = False
        settings.businesses.resonance_enabled = False
        settings.businesses.social_enabled = False
        ctx = ClipBotApp(settings)

        async def commit(new):
            # The real workers stay unstarted in this router-only verifier.
            ctx.settings = new
            ctx.pipeline.settings = new
            save_settings(new)
            return []

        ctx.commit_settings = commit
        app = create_app(ctx)
        calls, checks = [], []
        ident = "11111111-1111-4111-8111-111111111111"
        revision = "22222222-2222-4222-8222-222222222222"
        project = {"id": ident, "title": "Contract session", "parameters": {"bpm": 120, "bars": 8, "tracks": []},
                   "tracks": [], "revisions": [{"id": revision, "status": "completed",
                    "audio_url": f"/reaper/media/{ident}/{revision}", "download_url": f"/reaper/download/{ident}/{revision}"}]}

        async def engine(method, path, payload=None):
            calls.append({"method": method, "path": path})
            if path == "/api/status":
                return {"ready": True, "busy": False, "engine": "Contract fixture", "message": "Ready"}
            if path == "/api/runtime":
                return {"enabled": payload["enabled"]}
            if path == "/api/songs":
                return {"songs": [{"id": ident, "title": "Contract take", "audio_url": f"/media/{ident}"}]}
            if path == "/api/renders":
                return {"renders": []}
            if path == "/api/reaper/status":
                return {"installed": True, "ready": True, "busy": False, "projects": [project],
                        "dry_vocals_available": True, "dry_vocal_renders": [{"id": revision}]}
            if path.startswith("/api/reaper/projects"):
                return project
            raise AssertionError(f"Unexpected engine call {method} {path}")

        ctx.music_bridge.call = engine
        base = f"http://127.0.0.1:{settings.dashboard.port}"

        def checked(name, condition):
            assert condition, name
            checks.append(name)

        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
                checked("music requires authentication", (await client.get("/api/music/status")).status_code == 401)
                checked("social requires authentication", (await client.get("/api/social/clients")).status_code == 401)
                client.headers["X-ClipBot"] = "1"
                response = await client.post("/api/auth/setup", json={"name": "Contract verifier", "password": "preview-only-2026"})
                checked("real auth setup", response.status_code == 200)
                checked("all business runtime rows", {r["id"] for r in (await client.get("/api/businesses")).json()["businesses"]} == {"clips", "stories", "music", "social"})
                checked("music stopped write guard", (await client.post("/api/music/reaper/projects", json={})).status_code == 409)
                checked("music native bridge read", (await client.get("/api/music/status")).json()["ready"])
                data = (await client.get("/api/music/songs")).json()
                checked("source URL rewrite", data["songs"][0]["audio_url"].startswith("/api/music/media/"))
                data = (await client.get("/api/music/reaper/status")).json()
                checked("dry vocal contract", data["dry_vocals_available"] and data["dry_vocal_renders"][0]["id"] == revision)
                checked("revision URL rewrite", data["projects"][0]["revisions"][0]["audio_url"].startswith("/api/music/reaper/media/"))
                checked("explicit music runtime start", (await client.post("/api/businesses/music", json={"enabled": True})).status_code == 200)
                await asyncio.sleep(0)
                checked("music runtime uses managed bridge", any(c["path"] == "/api/runtime" for c in calls))
                checked("real native project router", (await client.post("/api/music/reaper/projects", json={"title": "Contract session"})).json()["id"] == ident)
                checked("unknown music action rejected", (await client.post("/api/music/exec", json={})).status_code == 404)
                created = await client.post("/api/social/clients", json={"name": "Contract client", "platforms": ["youtube"], "rules": "Fresh original footage", "fresh_footage_required": True})
                checked("real social client creation", created.status_code == 200)
                cid = created.json()["client"]["id"]
                checked("client public accounts isolated", (await client.get(f"/api/social/clients/{cid}/accounts")).json()["connected"] == {})
                checked("client assets available while stopped", (await client.get(f"/api/social/clients/{cid}/assets")).json()["assets"] == [])
                post = await client.post(f"/api/social/clients/{cid}/content", json={"title": "Contract post", "script": "Original words", "platforms": ["youtube"], "status": "scheduled", "scheduled_at": "2026-10-12T12:00:00Z"})
                checked("real scoped content router", post.status_code == 200)
                checked("real calendar data", any(row["client_id"] == cid for row in (await client.get("/api/social/calendar")).json()["items"]))
                checked("draft stopped guard", (await client.post(f"/api/social/clients/{cid}/draft", json={"brief": "Fresh gameplay", "style": "C"})).status_code == 409)
                checked("explicit social runtime start", (await client.post("/api/businesses/social", json={"enabled": True})).status_code == 200)
                studio = social_studio(ctx)

                async def local_model(*_args):
                    return {"title": "Model contract", "script": "Fresh footage will demonstrate this.", "caption": "Original caption", "hashtags": ["original"], "pinned_comment": "Your next move?", "notes": "Record fresh footage", "requires_fresh_footage": True}

                studio._model_request = local_model
                drafted = await client.post(f"/api/social/clients/{cid}/draft", json={"brief": "Fresh gameplay", "style": "C", "platforms": ["youtube"]})
                checked("real draft orchestration with local model replaced", drafted.status_code == 200 and drafted.json()["item"]["requires_fresh_footage"])
                client.headers.pop("X-ClipBot")
                checked("runtime action header enforced", (await client.post("/api/businesses/social", json={"enabled": False})).status_code == 403)
                static_results = [await client.get("/static/" + filename) for filename in ["music.js", "social.js", "business.js"]]
                checked("desktop files served by real app", all(response.status_code == 200 for response in static_results))
        finally:
            await close_business_runtime(ctx)
            await ctx.music_bridge.producer.close()
            ctx.pipeline.store.close()
        result = {"checks": len(checks), "passed": checks, "bridge_calls": calls, "actual_generation_or_render": False}
        Path("artifacts/workspace-contract-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
