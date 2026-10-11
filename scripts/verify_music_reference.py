"""Exercise the Ashvane reference adapter against the installed local engine."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from fastapi import FastAPI
from clipbot.config import Settings, resolve_paths
from clipbot.music_api import install_music_routes


async def main():
    with tempfile.TemporaryDirectory(prefix="ashvane-reference-check-") as folder:
        settings = Settings()
        settings.app.data_dir = folder
        settings.businesses.resonance_enabled = True
        ctx = SimpleNamespace(settings=settings, paths=resolve_paths(settings))
        app = FastAPI()
        install_music_routes(app, ctx)
        report = {"checks": {}, "scope": "Source adapter and installed local reference worker; authentication covered separately by tests."}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", timeout=30) as client:
            response = await client.post("/api/music/references/upload", headers={"X-File-Name": quote("Ashvane reference verification.wav")}, content=(ROOT / "artifacts/reaper-native-verified.wav").read_bytes())
            response.raise_for_status()
            ident = response.json()["id"]
            report["reference_id"] = ident
            report["checks"]["upload_accepted"] = response.status_code == 202
            for _ in range(60):
                response = await client.get("/api/music/references/" + ident)
                response.raise_for_status()
                record = response.json()
                if record["status"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(1)
            report["checks"]["cpu_analysis_completed"] = record["status"] == "completed"
            report["checks"]["preview_url_rewritten"] = record.get("audio_url") == "/api/music/references/media/" + ident
            if record.get("audio_url"):
                media = await client.get(record["audio_url"], headers={"Range": "bytes=0-43"})
                report["checks"]["bounded_range_preview"] = media.status_code == 206 and len(media.content) == 44 and media.content.startswith(b"RIFF")
            saved = (await client.get("/api/music/references")).json()["references"]
            report["checks"]["saved_reference_visible"] = any(row["id"] == ident for row in saved)
            context = await ctx.music_bridge.reference_context({"reference_id": ident, "reference_notes": "Keep the sparse drum feel"})
            report["checks"]["saved_context_resolves"] = context["what_to_borrow"] == "Keep the sparse drum feel"
            report["checks"]["temporary_upload_removed"] = not list((ctx.paths.work / "music-reference-uploads").iterdir())
            report["reference"] = {key: record.get(key) for key in ("status", "duration_seconds", "tempo_bpm", "analysis_note", "message")}
            report["listener_capabilities"] = (await client.get("/api/music/rap/capabilities")).json()
        (ROOT / "artifacts/resonance-reference-integration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not all(report["checks"].values()):
            raise SystemExit("Reference integration did not pass")


if __name__ == "__main__":
    asyncio.run(main())
