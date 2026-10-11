"""Original-story publication is independent, durable and bound to its account."""
import asyncio
import copy
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from clipbot import story_publishing as P
from clipbot.config import Settings
from clipbot.publishers.base import PostText, PublishResult
from clipbot.publishers.youtube import upload_metadata
from clipbot.stories import StoryStudio


class Tokens:
    def get(self, name):
        return {"refresh_token": f"refresh-{name}", "open_id": f"account-{name}"}


class OAuth:
    async def access_token(self, name):
        return f"access-{name}"


class FakePublisher:
    def __init__(self, name, settings, oauth, calls, result=None, pause=None):
        self.name, self.settings, self.oauth, self.calls = name, settings, oauth, calls
        self.result = result or PublishResult(True, remote_id="remote-story", url="https://youtube.com/shorts/remote-story")
        self.pause = pause

    def configured(self):
        return True, ""

    async def publish(self, video, post):
        self.calls.append({"name": self.name, "post": copy.deepcopy(post), "settings": self.settings.model_copy(deep=True),
                           "token": await self.oauth.access_token(self.name) if self.name in {"youtube", "tiktok"} else ""})
        if self.pause:
            self.pause.set()
            await asyncio.Event().wait()
        return self.result


def prepare(tmp_path, monkeypatch, *, result=None, pause=None):
    settings = Settings()
    settings.stories.auto_render = False
    settings.stories.publish_gap_min = 0
    settings.posting.youtube.shorts_suffix = " CLIP SUFFIX"
    settings.posting.youtube.category_id = "20"
    settings.posting.youtube.privacy = "private"
    settings.posting.youtube.age_restrict = True
    calls = []

    def factory(s, http, tokens, oauth):
        return {name: FakePublisher(name, s, oauth, calls, result, pause) for name in P.PLATFORMS}

    monkeypatch.setattr(P, "build_publishers", factory)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    studio = StoryStudio(settings, http, SimpleNamespace(data=tmp_path))
    pid = uuid.uuid4().hex
    directory = studio._directory(pid)
    directory.mkdir(parents=True)
    video, audio = directory / "story.mp4", directory / "narration.wav"
    video.write_bytes(b"verified-by-separate-renderer")
    audio.write_bytes(b"narration")
    project = {"id": pid, "title": "The Empty Station", "topic": "An impossible train", "genre": "paranormal",
               "format": "animated", "duration_s": 60, "voice": "", "created_at": 1, "updated_at": 1,
               "status": "ready", "progress": 1, "script": "A train arrived at the locked station. No one stepped out.",
               "scenes": [{"id": uuid.uuid4().hex, "narration": "A train arrived at the locked station. No one stepped out.",
                           "visual_prompt": "A dark station", "visual": {"setting": "station", "subject": "none", "action": "wait"}}],
               "public_copy": {"youtube": {"title": "The train that never stopped", "description": "Original fiction. A station after midnight.",
                                              "tags": ["horror story"], "hashtags": ["horror"]}},
               "review": {"passed": True, "reason": "PRIVATE JURY SHOULD NEVER BE PUBLIC"}, "agents": [],
               "output": {"video_path": str(video), "audio_path": str(audio), "duration_s": 60, "width": 720, "height": 1280},
               "publishing": {}, "revision": 0, "video_url": "", "audio_url": "", "error": ""}
    studio.projects = [project]
    project["review"]["content_hash"] = studio.content_fingerprint(pid)
    studio._save()
    queue = P.StoryPublishing(settings, http, Tokens(), OAuth(), studio, None)
    for name in P.PLATFORMS:
        queue.identities[name] = {"credential_hash": queue._credentials(name), "account_id": f"account-{name}",
                                  "account_label": f"My {name} account", "error": ""}
    return settings, studio, queue, calls, http, pid


def test_auto_publish_uses_story_settings_and_public_metadata_only(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            await queue.tick()
            assert len(calls) == 1
            outgoing = calls[0]
            assert outgoing["name"] == "youtube"
            assert outgoing["token"] == "access-youtube"
            metadata = upload_metadata(outgoing["post"], outgoing["settings"].posting.youtube)
            assert metadata["snippet"]["title"] == "The train that never stopped"
            assert metadata["snippet"]["categoryId"] == settings.stories.youtube_category_id
            assert metadata["status"]["privacyStatus"] == "public"
            assert metadata["status"]["containsSyntheticMedia"] is True
            assert "PRIVATE JURY" not in json.dumps(metadata)
            assert "#horror" in metadata["snippet"]["description"]
            assert settings.posting.youtube.shorts_suffix == " CLIP SUFFIX"
            assert settings.posting.youtube.category_id == "20"
            assert settings.posting.youtube.age_restrict is True
            publication = studio.get(pid)["publishing"]["youtube"]
            assert publication["status"] == "published"
            assert publication["account_id"] == "account-youtube"
            manifest = json.loads((studio._directory(pid) / "publish-youtube.json").read_text())
            assert manifest["file_sha256"] == P._digest_file(studio._directory(pid) / "story.mp4")
            assert manifest["metadata"] == metadata
            await queue.tick()
            assert len(calls) == 1
    asyncio.run(run())


def test_manual_queue_works_when_auto_posting_is_off(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            settings.stories.auto_publish = False
            await queue.tick()
            assert calls == []
            queued = queue.request_publish(pid, ["youtube", "discord"])
            assert all(row["status"] == "pending" for row in queued["publishing"].values())
            await queue.tick()
            assert {row["name"] for row in calls} == {"youtube", "discord"}
            assert all(row["status"] == "published" for row in studio.get(pid)["publishing"].values())
    asyncio.run(run())


def test_ambiguous_failure_never_retries_automatically(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch, result=PublishResult(False, error="timeout"))
        async with http:
            await queue.tick()
            assert studio.get(pid)["publishing"]["youtube"]["status"] == "uncertain"
            await queue.tick()
            assert len(calls) == 1
            with pytest.raises(RuntimeError, match="reconciliation"):
                queue.request_publish(pid)
    asyncio.run(run())


def test_cancelled_upload_is_durable_and_uncertain(tmp_path, monkeypatch):
    async def run():
        started = asyncio.Event()
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch, pause=started)
        async with http:
            queue.start()
            await asyncio.wait_for(started.wait(), timeout=3)
            assert studio.get(pid)["publishing"]["youtube"]["status"] == "uploading"
            await queue.stop()
            assert studio.get(pid)["publishing"]["youtube"]["status"] == "uncertain"
            assert queue.state()["busy"] is False
    asyncio.run(run())


def test_landscape_holds_reel_targets_and_youtube_gets_watch_url(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            studio.projects[0]["output"].update(width=1280, height=720)
            settings.stories.publish_destinations = ["youtube", "instagram"]
            with pytest.raises(ValueError, match="Landscape"):
                queue.request_publish(pid, ["instagram"])
            await queue.tick()
            assert [row["name"] for row in calls] == ["youtube"]
            assert studio.get(pid)["publishing"]["youtube"]["url"] == "https://youtube.com/watch?v=remote-story"
            assert "Landscape" in queue.errors["instagram"]
    asyncio.run(run())


def test_cap_zero_and_missing_account_identity_make_no_uploads(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            settings.stories.publish_daily_cap = 0
            await queue.tick()
            assert not calls
            assert "cap" in queue.errors["youtube"]
            queue.identities["youtube"]["error"] = "Reconnect YouTube"
            with pytest.raises(ValueError, match="Reconnect"):
                queue.request_publish(pid)
            assert queue.state()["destinations"][0]["ready"] is False
    asyncio.run(run())


def test_post_caption_preflight_failure_is_failed_and_not_looped(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            settings.stories.publish_destinations = ["instagram"]
            studio.projects[0]["public_copy"]["youtube"]["description"] = "Original fiction. " + "word " * 500
            studio.projects[0]["review"]["content_hash"] = studio.content_fingerprint(pid)
            await queue.tick()
            assert studio.get(pid)["publishing"]["instagram"]["status"] == "failed"
            assert not calls
            await queue.tick()
            assert not calls
    asyncio.run(run())


def test_account_switch_requires_explicit_requeue(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        async with http:
            queue.request_publish(pid)
            queue.identities["youtube"]["account_id"] = "new-channel"
            await queue.tick()
            assert not calls
            assert "account changed" in queue.errors["youtube"]
            queue.request_publish(pid)
            await queue.tick()
            assert studio.get(pid)["publishing"]["youtube"]["account_id"] == "new-channel"
    asyncio.run(run())


def test_legacy_clip_metadata_omits_synthetic_field():
    settings = Settings()
    old = upload_metadata(PostText("A clip", "A caption"), settings.posting.youtube)
    assert "containsSyntheticMedia" not in old["status"]
    new = upload_metadata(PostText("A story", "Original fiction.", contains_synthetic_media=False), settings.posting.youtube)
    assert new["status"]["containsSyntheticMedia"] is False


def test_requeue_preserves_attempt_history_for_daily_cap(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch, result=PublishResult(False, error="timeout"))
        async with http:
            settings.stories.publish_daily_cap = 2
            await queue.tick()
            studio.record_publish(pid, "youtube", "failed", error="User verified no post was created")
            queue.request_publish(pid)
            await queue.tick()
            assert len(calls) == 2
            assert len(studio.get(pid)["publication_history"]) == 2
            studio.record_publish(pid, "youtube", "failed", error="User verified no post was created")
            queue.request_publish(pid)
            await queue.tick()
            assert len(calls) == 2
            assert "cap" in queue.errors["youtube"]
    asyncio.run(run())


def test_verified_account_is_cached_until_credentials_change(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"items": [{"id": f"channel-{len(requests)}", "snippet": {"title": "My Story Channel"}}]})

        async with http, httpx.AsyncClient(transport=httpx.MockTransport(handler)) as identity_http:
            queue.http = identity_http
            queue.identities.pop("youtube")
            await queue._identity("youtube")
            await queue._identity("youtube")
            assert len(requests) == 1
            youtube = queue.state()["destinations"][0]
            assert youtube["ready"] is True
            assert youtube["account_id"] == "channel-1"
            assert youtube["account_label"] == "My Story Channel"
            assert "refresh-youtube" not in json.dumps(queue.state())
            monkeypatch.setattr(queue.tokens, "get", lambda name: {"refresh_token": "new-connection"})
            assert queue.state()["destinations"][0]["ready"] is False
            await queue._identity("youtube")
            assert len(requests) == 2
            assert queue.state()["destinations"][0]["account_id"] == "channel-2"
    asyncio.run(run())


def test_account_failure_is_visible_redacted_and_not_retried_each_tick(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(401, text="SECRET-TOKEN details")

        async with http, httpx.AsyncClient(transport=httpx.MockTransport(handler)) as identity_http:
            queue.http = identity_http
            queue.identities.pop("youtube")
            await queue._identity("youtube")
            await queue._identity("youtube")
            assert len(requests) == 1
            destination = queue.state()["destinations"][0]
            assert destination["ready"] is False
            assert "Reconnect" in destination["reason"]
            assert "SECRET-TOKEN" not in json.dumps(queue.state())
    asyncio.run(run())


@pytest.mark.parametrize("change_settings", [True, False])
def test_inflight_account_response_cannot_bind_to_changed_credentials_or_settings(tmp_path, monkeypatch, change_settings):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        started, release = asyncio.Event(), asyncio.Event()
        requests = []

        async def handler(request):
            requests.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json={"items": [{"id": "old-account", "snippet": {"title": "Old account"}}]})

        async with http, httpx.AsyncClient(transport=httpx.MockTransport(handler)) as identity_http:
            queue.http = identity_http
            queue.identities.pop("youtube")
            checking = asyncio.create_task(queue._identity("youtube"))
            await started.wait()
            if change_settings:
                changed = settings.model_copy(deep=True)
                changed.stories.publish_privacy = "private"
                queue.apply(changed)
            else:
                monkeypatch.setattr(queue.tokens, "get", lambda name: {"refresh_token": "a-new-account-connection"})
            release.set()
            await checking
            assert queue.state()["destinations"][0]["ready"] is False
            assert queue.state()["destinations"][0]["account_id"] == ""
            assert "youtube" not in queue.identities
    asyncio.run(run())


def test_transient_account_error_recovers_after_backoff_without_reconnecting(tmp_path, monkeypatch):
    async def run():
        settings, studio, queue, calls, http, pid = prepare(tmp_path, monkeypatch)
        requests = []
        clock = [1000.0]
        monkeypatch.setattr(P.time, "time", lambda: clock[0])

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"items": [{"id": "recovered-channel", "snippet": {"title": "Stories"}}]})

        async with http, httpx.AsyncClient(transport=httpx.MockTransport(handler)) as identity_http:
            queue.http = identity_http
            queue.identities.pop("youtube")
            await queue._identity("youtube")
            await queue._identity("youtube")
            assert len(requests) == 1
            clock[0] += settings.stories.account_retry_s
            await queue._identity("youtube")
            assert len(requests) == 2
            assert queue.state()["destinations"][0]["ready"] is True
            assert "youtube" not in queue.errors
    asyncio.run(run())
