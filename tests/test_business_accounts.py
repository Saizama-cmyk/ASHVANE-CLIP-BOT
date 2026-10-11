"""Destination credentials and public OAuth callbacks stay within their business."""
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from clipbot import config as C, secure
from clipbot.auth import ProfileStore
from clipbot.dashboard.server import create_app
from clipbot.pipeline import Pipeline
from clipbot.publishers.base import PublishError, TokenStore
from clipbot.publishers.oauth import OAuthManager
from clipbot.story_publishing import StoryPublishing


def configured():
    return C.merge_incoming(C.Settings(), {"accounts": {
        "youtube_client_id": "shared-google-app", "youtube_client_secret": "shared-google-secret",
        "tiktok_client_key": "shared-tiktok-app", "tiktok_client_secret": "shared-tiktok-secret",
        "tiktok_redirect_uri": "https://example.com/callback/",
        "instagram_token": "clip-instagram", "instagram_user_id": "clip-ig-user",
        "facebook_page_token": "clip-facebook", "facebook_page_id": "clip-fb-page",
        "discord_webhook": "https://discord.com/api/webhooks/clip/private"}})


def test_legacy_settings_never_copy_destination_credentials(isolated_home):
    legacy = configured().model_dump(mode="json")
    legacy.pop("story_accounts")
    C.settings_path().write_text(json.dumps(legacy), encoding="utf-8")
    settings = C.load_settings()
    assert settings.story_accounts == C.AccountsCfg()
    effective = C.story_account_settings(settings)
    assert effective.youtube_client_id == settings.accounts.youtube_client_id
    assert effective.youtube_client_secret == settings.accounts.youtube_client_secret
    assert effective.tiktok_redirect_uri == settings.accounts.tiktok_redirect_uri
    assert not effective.instagram_token and not effective.instagram_user_id
    assert not effective.facebook_page_token and not effective.facebook_page_id
    assert not effective.discord_webhook
    settings.story_accounts.youtube_client_id = "custom-google-app"
    assert not C.story_account_settings(settings).youtube_client_secret
    assert settings.accounts.youtube_client_secret == "shared-google-secret"


def test_story_settings_secrets_use_existing_encryption_mask_and_export(isolated_home):
    settings = C.merge_incoming(configured(), {"story_accounts": {
        "youtube_client_secret": "story-secret", "instagram_token": "story-instagram",
        "facebook_page_token": "story-facebook", "discord_webhook": "story-webhook"}})
    masked = C.masked_dump(settings)
    for field in ("youtube_client_secret", "instagram_token", "facebook_page_token", "discord_webhook"):
        assert ("story_accounts", field) in C.SECRET_FIELDS
        assert masked["story_accounts"][field] == C.MASK
        assert C.export_settings(settings, False)["story_accounts"][field] == ""
    assert C.merge_incoming(settings, masked) == settings
    C.save_settings(settings)
    assert C.load_settings() == settings
    if secure.available():
        disk = json.loads(C.settings_path().read_text(encoding="utf-8"))
        assert disk["story_accounts"]["instagram_token"].startswith(secure.PREFIX)
        assert "story-instagram" not in C.settings_path().read_text(encoding="utf-8")


def test_story_publishers_use_only_story_meta_accounts_and_separate_token_file(tmp_path):
    async def run():
        settings = configured()
        paths = C.resolve_paths(settings)
        pipeline = Pipeline(settings, paths)
        try:
            pipeline.tokens.set("youtube", {"access_token": "clip-user-token"})
            assert pipeline.tokens.path == paths.tokens
            assert pipeline.story_tokens.path == paths.data / "tokens-stories.json"
            assert pipeline.story_tokens.get("youtube") == {}
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as http:
                oauth = OAuthManager(settings, http, pipeline.story_tokens,
                                     account_section="story_accounts", callback_scope="stories")
                queue = StoryPublishing(settings, http, pipeline.story_tokens, oauth, None, None)
                for name in ("youtube", "tiktok", "instagram", "facebook", "discord"):
                    assert not queue.publishers[name].configured()[0]
                before = queue._credentials("discord")
                settings.story_accounts.discord_webhook = "https://discord.com/api/webhooks/story/private"
                queue.apply(settings)
                snapshot = queue._publisher_settings()
                assert snapshot.accounts.discord_webhook == settings.story_accounts.discord_webhook
                assert settings.accounts.discord_webhook.endswith("clip/private")
                assert queue._credentials("discord") != before
                assert not snapshot.accounts.instagram_token
                assert snapshot.accounts.youtube_client_id == settings.accounts.youtube_client_id
                pipeline.story_tokens.set("youtube", {"access_token": "story-user-token"})
                oauth.disconnect("youtube")
                assert pipeline.tokens.get("youtube")["access_token"] == "clip-user-token"
                if secure.available():
                    assert pipeline.story_tokens.path.read_text().startswith(secure.PREFIX)
        finally:
            pipeline.store.close()
    asyncio.run(run())


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_story_api_and_simultaneous_public_oauth_callbacks_are_isolated(tmp_path, monkeypatch, platform):
    async def run():
        settings, exchanges, opened = configured(), [], []

        def provider(request):
            fields = parse_qs(request.content.decode())
            exchanges.append(fields)
            code = fields["code"][0]
            return httpx.Response(200, json={"access_token": f"access-{code}", "refresh_token": f"refresh-{code}",
                                            "open_id": f"account-{code}", "expires_in": 86400})

        monkeypatch.setattr("clipbot.story_api.webbrowser.open", lambda url: opened.append(url) or False)
        paths = C.resolve_paths(settings)
        pipeline = Pipeline(settings, paths)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
                pipeline.oauth = OAuthManager(settings, http, pipeline.tokens)
                pipeline.story_oauth = OAuthManager(settings, http, pipeline.story_tokens,
                                                    account_section="story_accounts", callback_scope="stories")
                pipeline.story_publishing = StoryPublishing(settings, http, pipeline.story_tokens, pipeline.story_oauth, None, None)
                ctx = SimpleNamespace(settings=settings, pipeline=pipeline, paths=paths)

                async def commit(new):
                    ctx.settings = new
                    pipeline.oauth.apply(new)
                    pipeline.story_oauth.apply(new)
                    pipeline.story_publishing.apply(new)
                    C.save_settings(new)
                ctx.commit_settings = commit
                app = create_app(ctx)
                base = f"http://127.0.0.1:{settings.dashboard.port}"
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
                    assert (await client.get("/api/stories/accounts")).status_code == 401
                    assert (await client.post(f"/api/stories/accounts/{platform}/open", headers={"X-ClipBot": "1"})).status_code == 401
                    auth = ProfileStore()
                    profile = auth.create("Business tester", "safe-password-123", settings.app.min_password_len)
                    session = auth.create_session(profile["id"], settings.app.session_hours)
                    client.headers["Authorization"] = f"Bearer {session}"
                    assert (await client.put("/api/stories/accounts", json={})).status_code == 403
                    client.headers["X-ClipBot"] = "1"
                    state = (await client.get("/api/stories/accounts")).json()
                    assert state["accounts"] == C.AccountsCfg().model_dump(mode="json")
                    assert state["app_credentials"][platform] == {"configured": True, "inherited": True}
                    assert not state["oauth"][platform]
                    assert "shared-google-secret" not in json.dumps(state)
                    assert (await client.put("/api/stories/accounts", json={"accounts": {}})).status_code == 422
                    assert (await client.put("/api/stories/accounts", json={"instagram_token": 123})).status_code == 422
                    saved = await client.put("/api/stories/accounts", json={"instagram_token": "story-ig-secret"})
                    assert saved.json()["accounts"]["instagram_token"] == C.MASK
                    assert ctx.settings.accounts.instagram_token == "clip-instagram"
                    assert (await client.put("/api/stories/accounts", json={"instagram_token": C.MASK})).status_code == 200
                    assert ctx.settings.story_accounts.instagram_token == "story-ig-secret"

                    pipeline.tokens.set(platform, {"access_token": "existing-clip-token", "refresh_token": "existing-clip-refresh"})
                    existing_clip_file = pipeline.tokens.path.read_bytes()

                    clip_url = pipeline.oauth.start_url(platform)
                    clip_state = parse_qs(urlsplit(clip_url).query)["state"][0]
                    started = (await client.post(f"/api/stories/accounts/{platform}/open")).json()
                    assert started["ok"] and not started["opened"] and opened == [started["url"]]
                    story_state = parse_qs(urlsplit(started["url"]).query)["state"][0]
                    assert story_state != clip_state
                    assert pipeline.oauth.local_redirect(platform).endswith(f"/oauth/{platform}/callback")
                    if platform == "youtube":
                        assert pipeline.story_oauth.redirect_uri(platform) == pipeline.oauth.redirect_uri(platform)
                        assert parse_qs(urlsplit(started["url"]).query)["redirect_uri"] == [pipeline.oauth.redirect_uri(platform)]
                    else:
                        assert pipeline.story_oauth.local_redirect(platform).endswith(f"/oauth/stories/{platform}/callback")
                    # A wrong-business paste and a wrong-platform callback never consume
                    # the other pending flow or exchange its authorization code.
                    rejected = await client.post(f"/api/stories/accounts/{platform}/paste",
                                                 json={"url": f"https://example.com/?code=wrong&state={clip_state}"})
                    assert rejected.status_code == 422
                    other = "tiktok" if platform == "youtube" else "youtube"
                    with pytest.raises(PublishError):
                        await pipeline.oauth.callback(other, "wrong", clip_state)
                    assert pipeline.oauth.owns_state(platform, clip_state) and not exchanges

                    # Public callback routing works without a signed-in browser and
                    # honors Stories state even on the legacy TikTok forwarding URL.
                    client.headers.pop("Authorization")
                    refused = await client.get(f"/oauth/stories/{platform}/callback", params={"code": "wrong", "state": clip_state})
                    assert "state mismatch" in refused.text and not exchanges
                    story_route = f"/oauth/stories/{platform}/callback" if platform == "youtube" else f"/oauth/{platform}/callback"
                    response = await client.get(story_route, params={"code": "story", "state": story_state})
                    assert "Hollow can now post" in response.text
                    assert pipeline.story_tokens.get(platform)["access_token"] == "access-story"
                    assert pipeline.tokens.path.read_bytes() == existing_clip_file
                    response = await client.get(f"/oauth/{platform}/callback", params={"code": "clip", "state": clip_state})
                    assert "Surge can now post" in response.text
                    assert pipeline.tokens.get(platform)["access_token"] == "access-clip"
                    replay = await client.get(f"/oauth/{platform}/callback", params={"code": "replay", "state": story_state})
                    assert "state mismatch" in replay.text and len(exchanges) == 2
                    client.headers["Authorization"] = f"Bearer {session}"
                    assert (await client.get("/api/stories/accounts")).json()["oauth"][platform]
                    clip_file = pipeline.tokens.path.read_bytes()
                    assert (await client.post(f"/api/stories/accounts/{platform}/disconnect")).json()["ok"]
                    assert not pipeline.story_tokens.get(platform)
                    assert pipeline.tokens.path.read_bytes() == clip_file
                    assert pipeline.oauth.connected(platform)
                    # Manual recovery also writes only Stories, and disconnecting
                    # invalidates just that business's pending authorizations.
                    paste_url = pipeline.story_oauth.start_url(platform)
                    paste_state = parse_qs(urlsplit(paste_url).query)["state"][0]
                    pasted = await client.post(f"/api/stories/accounts/{platform}/paste",
                                               json={"url": f"https://example.com/?code=story-paste&state={paste_state}"})
                    assert pasted.json()["ok"]
                    assert pipeline.story_tokens.get(platform)["access_token"] == "access-story-paste"
                    assert pipeline.tokens.path.read_bytes() == clip_file
                    pending_url = pipeline.story_oauth.start_url(platform)
                    pending_state = parse_qs(urlsplit(pending_url).query)["state"][0]
                    assert (await client.post(f"/api/stories/accounts/{platform}/disconnect")).json()["ok"]
                    assert not pipeline.story_oauth.owns_state(platform, pending_state)
                    assert pipeline.tokens.path.read_bytes() == clip_file
                    app_key = "client_id" if platform == "youtube" else "client_key"
                    expected_app = "shared-google-app" if platform == "youtube" else "shared-tiktok-app"
                    assert all(item[app_key] == [expected_app] for item in exchanges)
        finally:
            pipeline.store.close()
    asyncio.run(run())
