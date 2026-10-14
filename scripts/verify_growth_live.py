"""Read-only linked-channel verification, without starting capture or publishing."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from clipbot.account_profiles import AccountProfiles
from clipbot.config import load_settings, resolve_paths
from clipbot.growth import Growth
from clipbot.publishers.base import TokenStore
from clipbot.publishers.oauth import OAuthManager


async def main():
    settings = load_settings()
    paths = resolve_paths(settings)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as http:
        pipeline = SimpleNamespace(settings=settings, paths=paths, http=http)
        profiles = pipeline.account_profiles = AccountProfiles(pipeline)
        if profiles.error:
            raise RuntimeError(profiles.error)
        profile = profiles.active_id("clips")
        tokens = TokenStore(profiles._token_path("clips", profile))
        pipeline.oauth = OAuthManager(settings, http, tokens)
        ctx = SimpleNamespace(settings=settings, paths=paths, pipeline=pipeline)
        growth = Growth(ctx)
        try:
            data = await growth.sync(profile)
            report = {"status": data["status"], "channel": data.get("channel"),
                      "videos": len(data["videos"]), "last_run": data["last_run"],
                      "truncated": data.get("truncated", False), "operations": "Channel metadata/statistics GETs only; no media download or publication"}
            target = Path(__file__).resolve().parent.parent / "artifacts" / "growth-live-report.json"
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            await growth.close()


if __name__ == "__main__":
    asyncio.run(main())
