"""YouTube uploads use supported metadata and preserve explicit age and privacy choices."""
import asyncio
import json
import time

import httpx
import pytest

from clipbot.config import Settings, merge_incoming
from clipbot.publishers.base import PostText, PublishError, TokenStore
from clipbot.publishers.oauth import OAuthManager
from clipbot.publishers.youtube import (CHANNELS_URL, DESCRIPTION_MAX, TITLE_MAX, UPLOAD_URL,
                                      YouTubePublisher)


def settings(**posting):
    return merge_incoming(Settings(), {
        "accounts": {"youtube_client_id": "test-client", "youtube_client_secret": "test-secret"},
        "posting": {"youtube": {"enabled": True, **posting}},
    })


def publisher(config, http, tmp_path, connected=True):
    tokens = TokenStore(tmp_path / "tokens.json")
    if connected:
        tokens.set("youtube", {"access_token": "test-access", "refresh_token": "test-refresh",
                               "expires_at": time.time() + 3600})
    return YouTubePublisher(config, http, tokens, OAuthManager(config, http, tokens))


@pytest.mark.parametrize("privacy", ["public", "unlisted", "private"])
@pytest.mark.parametrize("upload_status", [200, 201])
def test_resumable_upload_sends_supported_metadata_and_preserves_privacy(tmp_path, privacy, upload_status):
    config = settings(privacy=privacy)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"local test video")
    post = PostText("T" * (TITLE_MAX + 1), "D" * (DESCRIPTION_MAX + 1), ["gaming", "clip"])
    calls = []
    session_url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test-session"
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert str(request.url).startswith(UPLOAD_URL)
            assert dict(request.url.params) == {"uploadType": "resumable", "part": "snippet,status"}
            assert request.headers["Authorization"] == "Bearer test-access"
            assert request.headers["Content-Type"] == "application/json; charset=UTF-8"
            assert request.headers["X-Upload-Content-Type"] == "video/mp4"
            assert request.headers["X-Upload-Content-Length"] == str(video.stat().st_size)
            meta = json.loads(request.content)
            assert set(meta) == {"snippet", "status"}
            assert meta["status"] == {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
            assert len(meta["snippet"]["title"]) == TITLE_MAX
            assert meta["snippet"]["title"].endswith(config.posting.youtube.shorts_suffix)
            assert meta["snippet"]["description"] == "D" * DESCRIPTION_MAX
            assert meta["snippet"]["tags"] == post.hashtags
            assert meta["snippet"]["categoryId"] == config.posting.youtube.category_id
            return httpx.Response(200, headers={"Location": session_url})
        assert request.method == "PUT" and str(request.url) == session_url
        assert request.content == video.read_bytes()
        assert request.headers["Authorization"] == "Bearer test-access"
        assert request.headers["Content-Type"] == "video/mp4"
        return httpx.Response(upload_status, json={"id": "test-video"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await publisher(config, http, tmp_path).publish(video, post)
    result = asyncio.run(run())
    assert result.ok and result.remote_id == "test-video"
    assert result.url == "https://youtube.com/shorts/test-video" and len(calls) == 2
    assert config.posting.youtube.privacy == privacy


@pytest.mark.parametrize("failure", ["init", "upload", "no_location", "no_id"])
def test_provider_failure_never_reports_a_success(tmp_path, failure):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"local test video")
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            if failure == "init":
                return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
            if failure == "no_location":
                return httpx.Response(200)
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/test-session"})
        if failure == "upload":
            return httpx.Response(500, json={"error": "provider failure"})
        return httpx.Response(200, json={})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await publisher(settings(), http, tmp_path).publish(video, PostText("Title", "Caption"))
    result = asyncio.run(run())
    assert not result.ok and not result.remote_id and not result.url
    assert len(calls) == (1 if failure in ("init", "no_location") else 2)
    expected = {"init": "quotaExceeded", "upload": "HTTP 500",
                "no_location": "no resumable upload URL", "no_id": "no id"}
    assert expected[failure] in result.error


@pytest.mark.parametrize("direct", [False, True])
def test_explicit_age_hold_makes_no_requests_or_file_reads(tmp_path, direct):
    config = settings(age_restrict=True)
    def forbidden(_request):
        raise AssertionError("An explicit manual age hold must not call any remote API")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
            pub = publisher(config, http, tmp_path)
            ready, reason = pub.configured()
            assert not ready and "YouTube Studio" in reason and "held" in reason
            if direct:
                with pytest.raises(PublishError, match="cannot set an 18\\+ age restriction"):
                    await pub._publish(tmp_path / "missing.mp4", PostText("Title", "Caption"))
            else:
                result = await pub.publish(tmp_path / "missing.mp4", PostText("Title", "Caption"))
                assert not result.ok and result.error == reason
            assert config.posting.youtube.age_restrict and config.posting.youtube.privacy == "public"
    asyncio.run(run())


def test_unconnected_account_is_not_ready_and_makes_no_upload_request(tmp_path):
    def forbidden(_request):
        raise AssertionError("A disconnected account must not attempt an upload")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
            pub = publisher(settings(), http, tmp_path, connected=False)
            result = await pub.publish(tmp_path / "missing.mp4", PostText("Title", "Caption"))
            assert not result.ok and "not connected" in result.error
    asyncio.run(run())


def test_connected_account_without_a_youtube_channel_returns_none(tmp_path):
    def handler(request):
        assert request.method == "GET" and str(request.url).startswith(CHANNELS_URL)
        assert dict(request.url.params) == {"part": "statistics", "mine": "true"}
        return httpx.Response(200, json={"items": []})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            assert await publisher(settings(), http, tmp_path).account() is None
    asyncio.run(run())


def test_new_default_permits_ordinary_uploads_and_keeps_saved_age_preferences():
    assert Settings().posting.youtube.age_restrict is False
    assert settings(age_restrict=True).posting.youtube.age_restrict is True
