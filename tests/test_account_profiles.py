"""Profile names never authorize a different destination or change an existing queue."""
import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException

from clipbot.account_profiles import AccountProfiles
from clipbot.config import MASK, Settings, load_tokens
from clipbot.dashboard.server import create_app
from clipbot.publishers import PLATFORMS, build_publishers
from clipbot.publishers.base import TokenStore
from clipbot.publishers.oauth import OAuthManager
from clipbot.scheduler import Scheduler
from tests.test_scheduler import FakePub, cand, pubs
from tests.test_story_publishing import prepare


def context(tmp_path, http):
    settings = Settings()
    settings.accounts.youtube_client_id = "developer-app"
    settings.accounts.youtube_client_secret = "developer-secret"
    settings.accounts.discord_webhook = "https://discord.test/default-secret"
    paths = SimpleNamespace(data=tmp_path, tokens=tmp_path / "tokens.json", story_tokens=tmp_path / "tokens-stories.json")
    pipeline = SimpleNamespace(settings=settings, paths=paths, tokens=TokenStore(paths.tokens), story_tokens=TokenStore(paths.story_tokens), _inflight={})
    pipeline.oauth = OAuthManager(settings, http, pipeline.tokens)
    pipeline.story_oauth = OAuthManager(settings, http, pipeline.story_tokens, account_section="story_accounts", callback_scope="stories")
    pipeline.publishers = build_publishers(settings, http, pipeline.tokens, pipeline.oauth)
    pipeline.scheduler = SimpleNamespace(apply=lambda s: None)
    pipeline.analytics = SimpleNamespace(select_profile=lambda _: None)
    pipeline.stories = SimpleNamespace(busy=False)
    pipeline.story_publishing = SimpleNamespace(_tick_lock=asyncio.Lock(), apply=lambda s: None,
                                               _destination=lambda name: {"ready": False, "account_id": "", "account_label": "", "reason": "Not connected"})
    service = pipeline.account_profiles = AccountProfiles(pipeline)
    ctx = SimpleNamespace(settings=settings, pipeline=pipeline, paths=paths, pet_token="test", restart_pending=set())

    async def commit(incoming):
        ctx.settings = pipeline.settings = incoming
        pipeline.oauth.apply(incoming)
        pipeline.story_oauth.apply(incoming)
        for publisher in pipeline.publishers.values():
            publisher.apply(incoming)
        service.apply(incoming)
    ctx.commit_settings = commit
    service.ctx = ctx
    service.bind()
    return ctx, service


def test_profile_credentials_tokens_and_public_handles_do_not_inherit(tmp_path):
    async def run():
        async with httpx.AsyncClient() as http:
            ctx, service = context(tmp_path, http)
            ctx.pipeline.tokens.set("youtube", {"access_token": "default-channel-token"})
            state = await service.create("clips", {"name": "Another channel", "public_handles": {"youtube": "https://youtube.com/@another"}})
            identity = state["profiles"][-1]["id"]
            await service.activate(ctx, "clips", identity)
            assert not ctx.pipeline.oauth.connected("youtube")
            assert ctx.settings.accounts.discord_webhook == ""
            assert ctx.settings.accounts.youtube_client_id == "developer-app"
            assert not service.state("clips")["profiles"][-1]["connections"]["youtube"]["ready"]
            ctx.pipeline.tokens.set("youtube", {"access_token": "other-channel-token"})
            await service.edit("clips", identity, {"accounts": {"discord_webhook": "https://discord.test/other-secret"}})
            await service.edit("clips", identity, {"accounts": {"discord_webhook": MASK}})
            assert ctx.settings.accounts.discord_webhook.endswith("other-secret")
            assert service.state("clips")["profiles"][-1]["accounts"]["discord_webhook"] == MASK
            await service.activate(ctx, "clips", "default")
            assert ctx.pipeline.tokens.get("youtube")["access_token"] == "default-channel-token"
            assert ctx.settings.accounts.discord_webhook.endswith("default-secret")
            assert not ctx.pipeline.story_oauth.connected("youtube")
            await service.activate(ctx, "clips", identity)
            assert ctx.pipeline.tokens.get("youtube")["access_token"] == "other-channel-token"
            assert ctx.settings.accounts.discord_webhook.endswith("other-secret")
            restored = AccountProfiles(ctx.pipeline)
            assert restored.active_id("clips") == identity
            assert restored.get("clips", identity)["name"] == "Another channel"
            assert "accounts" not in restored.get("clips", identity)
    asyncio.run(run())


def test_signin_and_exchanging_callback_block_switches_and_bind_original_profile(tmp_path):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        async def exchange(request):
            entered.set()
            await finish.wait()
            return httpx.Response(200, json={"access_token": "authorized-original-profile", "expires_in": 3600})
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as http:
            ctx, service = context(tmp_path, http)
            state = await service.create("clips", {"name": "Another"})
            identity = state["profiles"][-1]["id"]
            url = ctx.pipeline.oauth.start_url("youtube")
            pending = parse_qs(urlsplit(url).query)["state"][0]
            with pytest.raises(HTTPException) as held:
                await service.activate(ctx, "clips", identity)
            assert held.value.status_code == 409
            task = asyncio.create_task(ctx.pipeline.oauth.callback("youtube", "code", pending))
            await entered.wait()
            assert not ctx.pipeline.oauth._states
            with pytest.raises(HTTPException):
                await service.activate(ctx, "clips", identity)
            finish.set()
            await task
            await service.activate(ctx, "clips", identity)
            assert ctx.pipeline.tokens.get("youtube") == {}
            assert load_tokens(ctx.pipeline.paths.tokens)["youtube"]["access_token"] == "authorized-original-profile"
    asyncio.run(run())


def test_upload_and_creative_jobs_block_activation(tmp_path):
    async def run():
        async with httpx.AsyncClient() as http:
            ctx, service = context(tmp_path, http)
            identity = (await service.create("clips", {"name": "Another"}))["profiles"][-1]["id"]
            async with service.upload("clips"):
                with pytest.raises(HTTPException):
                    await service.activate(ctx, "clips", identity)
            music_id = (await service.create("music", {"name": "Artist"}))["profiles"][-1]["id"]
            ctx.creative_tools = SimpleNamespace(tasks={"music": {asyncio.current_task()}})
            with pytest.raises(HTTPException):
                await service.activate(ctx, "music", music_id)
            ctx.creative_tools.tasks["music"].clear()
            await service.activate(ctx, "music", music_id)
            assert service.state("music")["connection_mode"] == "public_links"
            assert all(not row["ready"] for row in service.state("music")["profiles"][-1]["connections"].values())
    asyncio.run(run())


def test_other_profile_clips_never_publish_or_expire_using_current_credentials(tmp_path):
    async def run():
        from clipbot.db import Store
        async with httpx.AsyncClient() as http:
            ctx, service = context(tmp_path, http)
            store = Store(tmp_path / "clips.db")
            candidate = cand(tmp_path, created=0)
            store.upsert_candidate(candidate)
            pub = FakePub(ctx.settings)
            scheduler = Scheduler(ctx.settings, store, pubs(ctx.settings, pub))
            scheduler.account_profiles = service
            identity = (await service.create("clips", {"name": "Other"}))["profiles"][-1]["id"]
            await service.activate(ctx, "clips", identity)
            assert await scheduler._pending_for("discord") == []
            result = await scheduler._post_checked("discord", candidate.id)
            assert not result.ok and "another account profile" in result.error
            await scheduler.cleanup()
            assert store.get_candidate(candidate.id) is not None
            assert not pub.calls and store.posts_for_candidate(candidate.id) == []
            store.close()
    asyncio.run(run())


def test_story_autopublishing_and_manual_queue_hold_original_profile(tmp_path, monkeypatch):
    async def run():
        settings, studio, publisher, calls, http, identity = prepare(tmp_path, monkeypatch)
        async with http:
            ctx, service = context(tmp_path / "profiles", http)
            other = (await service.create("stories", {"name": "Other"}))["profiles"][-1]["id"]
            await service.activate(ctx, "stories", other)
            publisher.account_profiles = service
            with pytest.raises(ValueError, match="another account profile"):
                publisher.request_publish(identity, ["youtube"])
            await publisher.tick()
            assert not calls
            assert studio.get(identity)["publishing"] == {}
    asyncio.run(run())


def test_corrupt_registry_preserved_and_all_publishing_held(tmp_path):
    async def run():
        async with httpx.AsyncClient() as http:
            ctx, service = context(tmp_path, http)
            original = b"{broken registry"
            service.path.write_bytes(original)
            broken = AccountProfiles(ctx.pipeline)
            assert broken.error and broken.held_reason("clips", "default")
            with pytest.raises(HTTPException):
                await broken.create("clips", {"name": "Never overwrite"})
            assert service.path.read_bytes() == original
    asyncio.run(run())


def test_failed_activation_restores_previous_profile_and_credentials(tmp_path):
    async def run():
        async with httpx.AsyncClient() as http:
            ctx, service = context(tmp_path, http)
            identity = (await service.create("clips", {"name": "Other"}))["profiles"][-1]["id"]
            commit = ctx.commit_settings
            failures = []
            async def fail_once(settings):
                await commit(settings)
                if not failures:
                    failures.append(True)
                    raise OSError("Simulated apply failure after durable settings write")
            ctx.commit_settings = fail_once
            with pytest.raises(OSError):
                await service.activate(ctx, "clips", identity)
            assert service.active_id("clips") == "default"
            assert ctx.settings.accounts.discord_webhook.endswith("default-secret")
            assert ctx.pipeline.tokens.path == ctx.pipeline.paths.tokens
            assert load_tokens(service.path)["businesses"]["clips"]["active_profile_id"] == "default"
            assert not service.error and not service.switching
    asyncio.run(run())


def test_authenticated_routes_reject_anonymous_stale_profile_and_patch_without_action_header(tmp_path, monkeypatch):
    async def run():
        async with httpx.AsyncClient() as engine_http:
            ctx, service = context(tmp_path, engine_http)
            app = create_app(ctx)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
                assert (await client.get("/api/account-profiles/clips")).status_code == 401
                assert (await client.post("/api/auth/setup", headers={"X-ClipBot": "1"}, json={"name": "Owner", "password": "pass-word-1"})).status_code == 200
                result = await client.post("/api/account-profiles/clips", headers={"X-ClipBot": "1"}, json={"name": "Second"})
                assert result.status_code == 200, result.text
                identity = result.json()["profiles"][-1]["id"]
                assert (await client.patch(f"/api/account-profiles/clips/{identity}", json={"name": "Blocked"})).status_code == 403
                stale = await client.post(f"/api/account-profiles/clips/{identity}/youtube/open", headers={"X-ClipBot": "1"})
                assert stale.status_code == 409
                assert not ctx.pipeline.oauth._states
                wrong_business = await client.patch(f"/api/account-profiles/stories/{identity}", headers={"X-ClipBot": "1"}, json={"name": "No"})
                assert wrong_business.status_code == 404
                assert "developer-secret" not in (await client.get("/api/account-profiles/clips")).text
                refused = await client.put("/api/settings", headers={"X-ClipBot": "1"}, json={"settings": {"accounts": {"discord_webhook": "https://stale-form.test/wrong"}}})
                assert refused.status_code == 409
                assert ctx.settings.accounts.discord_webhook.endswith("default-secret")
                client.cookies.clear()
                assert (await client.get("/api/account-profiles/clips")).status_code == 401
    asyncio.run(run())
