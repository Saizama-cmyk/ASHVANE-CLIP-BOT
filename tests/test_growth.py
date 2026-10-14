"""Copywriter, analytics steering and the popular-clip importer."""
import asyncio
import json
import time

import httpx
import pytest

from clipbot.analytics import Analytics, compute_insights
from clipbot.clip_import import candidate_from_clip, pick_clips
from clipbot.config import Settings, merge_incoming, resolve_paths
from clipbot.copywriter import Copywriter, normalize_copy
from clipbot.db import Store
from clipbot.models import Candidate, Platform, SpikeEvent, Stage, StreamTarget
from clipbot.scheduler import compose_post
from clipbot.public_copy import UnsafePublicCopy


def cand(login="xqc", category="GTA V", kind="chat", post_copy=None, source=None):
    t = StreamTarget(Platform.TWITCH, login, login.title(), category, 1)
    ev = SpikeEvent(target=t, t_wall=1.0, kind=kind, score=1, chat_rate=1, baseline=1)
    return Candidate(id=ev.id, event=ev, raw_path="", start_wall=0, end_wall=20,
                     stage=Stage.SCHEDULED, verdict={"title": "T", "caption": "C", "hashtags": ["a"],
                                                     "score": 7},
                     post_copy=post_copy or {}, source=source or {})


COPY = {"hook": "He did NOT expect that", "youtube": {"title": "xQc loses it", "description": "Story.",
        "tags": ["#xqc", "gta", "GTA", "clips"]},
        "tiktok": {"caption": "wait for it", "hashtags": ["fyp", "#xqc", "gta"]},
        "instagram": {"caption": "Line one.\n\nFollow for daily clips", "hashtags": ["xqc"]},
        "facebook": {"title": "xQc GTA moment", "description": "Setup and payoff."},
        "discord": {"message": "new clip just dropped"}}


def test_normalize_copy_limits():
    out = normalize_copy(COPY, merge_incoming(Settings(), {"copywriter": {"hashtags_max": 2}}))
    assert out["youtube"]["tags"] == ["xqc", "gta", "clips"]           # deduped, # stripped
    assert out["tiktok"]["hashtags"] == ["fyp", "xqc"]                  # capped
    assert out["hook"].startswith("He did")


def test_copywriter_calls_model_with_rules():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(COPY)}})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await Copywriter(Settings(), http).write(cand(), "Streamers doing best: xqc")
    out = asyncio.run(go())
    system, user = seen["messages"][0]["content"], seen["messages"][1]["content"]
    assert "Youtube:" in system and "{platform_rules}" not in system
    assert "Streamers doing best: xqc" in user
    assert out["discord"]["message"] == "new clip just dropped"


def test_compose_uses_platform_copy():
    s = Settings()
    c = cand(post_copy={**normalize_copy(COPY, s), '_source':'video'})
    yt = compose_post(c, s, "youtube")
    assert yt.title == "xQc loses it" and yt.caption.startswith("Story.") and "gta" in yt.hashtags
    tt = compose_post(c, s, "tiktok")
    assert tt.title == "wait for it" and "#fyp" in tt.caption
    with pytest.raises(UnsafePublicCopy):
        compose_post(cand(), s, "youtube")  # no private verdict fallback


def test_import_credit_names_clipper():
    c = cand(source={"type": "twitch_clip", "clipper": "viewer42"},
             post_copy={'_source':'video', 'youtube':{'title':'A surprise in GTA'}})
    assert "clip by viewer42" in compose_post(c, Settings(), "youtube").caption


def _seed(store, n=6):
    now = time.time()
    for i in range(n):
        login = "winner" if i % 2 == 0 else "loser"
        c = cand(login=login, category="Slots" if login == "winner" else "IRL")
        c.created_at = now - 3 * 86400
        store.upsert_candidate(c)
        store.record_post(c.id, "youtube", f"v{i}", "", "ok", when=now - 2 * 86400)
    for p in store.measurable_posts(0):
        views = 10000 if p["streamer"] == "winner" else 500
        store.record_metrics(p["post_id"], views, 10, 1, 0, 0, when=p["posted_at"] + 25 * 3600)


def test_insights_and_steering(tmp_path):
    s = merge_incoming(Settings(), {"analytics": {"min_posts": 4, "steer_strength": 1,
                                                  "explore_share": 0}})
    store = Store(tmp_path / "db")
    _seed(store)
    posts = store.measurable_posts(0)
    ins = compute_insights(posts, store.metrics_for([p["post_id"] for p in posts]), s)
    assert ins.measured == 6
    streamers = ins.groups["streamer"]
    assert streamers["twitch:winner"]["score"] > 0 > streamers["twitch:loser"]["score"]
    an = Analytics(s, store, {}, resolve_paths(s))
    an.insights = ins
    assert an.active
    assert an.bias(cand(login="winner", category="Slots")) > an.bias(cand(login="loser", category="IRL"))
    assert an.boosted_streamers("twitch") == ["winner"]
    assert "winner" in an.notes()
    store.close()


def test_flood_caps_and_exploration(tmp_path):
    s = merge_incoming(Settings(), {"analytics": {"max_share_per_streamer": 0.5,
                                                  "max_share_per_category": 1, "explore_share": 0.5}})
    an = Analytics(s, Store(tmp_path / "db"), {}, resolve_paths(s))
    today = [{"streamer": "xqc", "category": "GTA V"}, {"streamer": "xqc", "category": "GTA V"}]
    assert not an.within_caps(cand("xqc"), today)                       # 3 of 3 would be xqc
    assert an.within_caps(cand("other"), today)
    assert an.within_caps(cand("xqc"), [])                              # first post always ok
    picks = [an.explore_now("youtube") for _ in range(10)]
    assert sum(picks) == 5                                               # exactly half explore


def test_due_logic(tmp_path):
    s = Settings()
    an = Analytics(s, Store(tmp_path / "db"), {}, resolve_paths(s))
    now = time.time()
    assert an.due(now, [], {}) == "periodic"                            # never ran
    an.last_run = now - 2 * 3600
    old_post = {"post_id": 1, "platform": "youtube", "posted_at": now - 30 * 3600}
    assert an.due(now, [old_post], {}) == "next-day"
    assert an.due(now, [dict(old_post, platform="discord")], {}) in ("", "end-of-day")
    an.last_run = now - 60                                              # min gap blocks
    assert an.due(now, [old_post], {}) == ""


def test_pick_clips_filters():
    s = merge_incoming(Settings(), {"clip_import": {"min_views": 1000, "max_per_run": 2},
                                    "twitch": {"languages": ["en"]}})
    clips = [{"id": "a", "view_count": 5000, "duration": 30, "language": "en"},
             {"id": "b", "view_count": 900, "duration": 30, "language": "en"},    # too few views
             {"id": "c", "view_count": 9000, "duration": 90, "language": "en"},   # too long
             {"id": "d", "view_count": 8000, "duration": 20, "language": "es"},   # language
             {"id": "e", "view_count": 7000, "duration": 20, "language": "en"},
             {"id": "f", "view_count": 6000, "duration": 20, "language": "en"}]
    got = pick_clips(clips, s, lambda cid: cid == "e")                   # e already imported
    assert [c["id"] for c in got] == ["f", "a"]


def test_candidate_from_clip(tmp_path):
    c = candidate_from_clip({"id": "Slug-1", "broadcaster_name": "xQc", "broadcaster_id": "71092938",
                             "game_name": "GTA V", "view_count": 12345, "creator_name": "viewer42",
                             "title": "LOL", "duration": 26.5, "url": "https://clips.twitch.tv/x"},
                            tmp_path / "clip.mp4")
    assert c.event.kind == "popular_clip" and c.event.target.login == "xqc"
    assert c.source["clipper"] == "viewer42" and abs((c.end_wall - c.start_wall) - 26.5) < 0.01
    assert "12,345 views" in c.event.chat_sample[0]


def test_copy_keeps_first_comments():
    from clipbot.config import Settings as _S
    from clipbot.copywriter import normalize_copy
    out = normalize_copy({"youtube": {"title": "T", "description": "D", "tags": ["a"], "comment": "who wins this?\nline2"},
                          "tiktok": {"caption": "C", "comment": "rate it 1-10"}, "discord": {"message": "m", "comment": "x"}}, _S())
    assert out["youtube"]["comment"] == "who wins this? line2" and out["tiktok"]["comment"] == "rate it 1-10"
    assert "comment" not in out["discord"]

# Growth dashboard reads and profile-bound YouTube library synchronization.
from contextlib import asynccontextmanager
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from clipbot.growth import Growth, close_growth, growth, install_growth_routes


class GrowthProfiles:
    def __init__(self):
        self.current = "default"
        self.holders = 0
        self.expected = []
    def active_id(self, business):
        assert business == "clips"
        return self.current
    def require_current(self, business, expected=""):
        assert business == "clips"
        self.expected.append(expected)
        if expected != self.current:
            raise HTTPException(409, "Profile changed")
    @asynccontextmanager
    async def upload(self, business):
        assert business == "clips"
        self.holders += 1
        try:
            yield
        finally:
            self.holders -= 1
    def switch(self, identity):
        if self.holders:
            raise HTTPException(409, "A read is in progress")
        self.current = identity


class GrowthStore:
    def __init__(self):
        self.reads = []
        self.writes = []
        self.posts = []
        self.metrics = {}
        self.history = [{"platform": "youtube", "captured_at": time.time(), "followers": 100}]
    def measurable_posts(self, since):
        self.reads.append(("posts", since))
        return [row for row in self.posts if row["posted_at"] >= since]
    def metrics_for(self, ids):
        self.reads.append(("metrics", ids))
        return {key: value for key, value in self.metrics.items() if key in ids}
    def outcomes_for(self, ids, profile_id):
        self.reads.append(("outcomes", ids, profile_id))
        return {}
    def account_history(self, since):
        self.reads.append(("history", since))
        return self.history


def growth_context(tmp_path, client):
    settings = Settings()
    profiles = GrowthProfiles()
    store = GrowthStore()
    class OAuth:
        ready = True
        def __init__(self):
            self.calls = []
        def connected(self, platform):
            assert platform == "youtube"
            return self.ready
        async def access_token(self, platform):
            assert profiles.holders and platform == "youtube"
            self.calls.append(profiles.current)
            return "owner-token-" + profiles.current
    async def snapshot():
        assert profiles.holders
        return {"status": "idle", "backlog": {"in_flight": 0}, "latency": {}, "scheduler": {},
                "ai": {"busy": False}, "copywriter": {"busy": False}, "ignored": "private"}
    pipeline = SimpleNamespace(account_profiles=profiles, store=store, http=client, oauth=OAuth(),
        analytics=SimpleNamespace(snapshot=lambda: {"enabled": True, "steering": False, "last_run": 1,
            "accounts": {"youtube": {"followers": 99999}}, "groups": {"streamer": {"other": {}}}}),
        snapshot=snapshot)
    supervisor = SimpleNamespace(snapshot=lambda: {"enabled": True, "state": "idle", "agents": [
        {"id": "researcher", "name": "Researcher", "status": "waiting", "instructions": "private"}]})
    return SimpleNamespace(settings=settings, paths=SimpleNamespace(data=tmp_path), pipeline=pipeline, supervisor=supervisor)


def owned_post(identity, post_id, age_days=2):
    return {"post_id": post_id, "candidate_id": "candidate-" + str(post_id), "platform": "youtube",
        "remote_id": "video" + str(post_id), "url": "https://youtube.com/watch?v=video" + str(post_id),
        "posted_at": time.time() - age_days * 86400, "streamer": "owner" + str(post_id),
        "display_name": "Owner", "source": "twitch", "category": "Games", "kind": "chat", "title": "Original",
        "score": 5, "account_profile_id": identity}


def youtube_handler(count=2, error=None, incomplete=False):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "www.googleapis.com"
        assert request.headers["authorization"].startswith("Bearer owner-token-")
        if error is not None:
            return httpx.Response(error, json={"error": "PRIVATE-RAW-TOKEN-DETAIL"})
        path, query = request.url.path, request.url.params
        if path.endswith("/channels"):
            assert query["mine"] == "true" and "contentDetails" in query["part"]
            return httpx.Response(200, json={"items": [{"id": "UCowner", "snippet": {"title": "My channel"},
                "statistics": {"subscriberCount": "100", "viewCount": "2000", "videoCount": str(count)},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUowner"}}}]})
        if path.endswith("/playlistItems"):
            assert query["playlistId"] == "UUowner"
            offset = int(query.get("pageToken", "0"))
            stop = min(count, offset + int(query["maxResults"]))
            page = {"items": [{"contentDetails": {"videoId": "video" + str(index)}, "snippet": {
                "title": "Playlist " + str(index), "publishedAt": "2026-10-01T00:00:00Z",
                "videoOwnerChannelId": "UCowner", "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/v/default.jpg"}}}}
                for index in range(offset, stop)]}
            if stop < count:
                page["nextPageToken"] = str(stop)
            return httpx.Response(200, json=page)
        assert path.endswith("/videos")
        ids = query["id"].split(",")
        assert len(ids) <= 50 and query["part"] == "snippet,statistics"
        return httpx.Response(200, json={"items": [{"id": identity,
            "snippet": {"channelId": "UCowner", "title": "Detailed " + identity, "publishedAt": "2026-10-01T00:00:00Z"},
            "statistics": {"viewCount": "0", **({} if incomplete else {"likeCount": "3", "commentCount": "1"})}}
            for identity in ids]})
    return handler, calls


def test_growth_snapshot_has_no_external_calls_and_filters_owned_posts(tmp_path):
    async def run():
        async def forbidden(request):
            raise AssertionError("GET Growth must not contact a platform")
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            ctx = growth_context(tmp_path, client)
            profile = "a" * 32
            ctx.pipeline.account_profiles.switch(profile)
            ctx.pipeline.store.posts = [owned_post("default", 1), owned_post(profile, 2)]
            ctx.pipeline.store.metrics = {1: [{"captured_at": time.time(), "views": 99999, "likes": 1, "comments": 1, "shares": 0}],
                2: [{"captured_at": time.time(), "views": 10, "likes": 1, "comments": 1, "shares": 0}]}
            result = await Growth(ctx).snapshot()
            assert result["account_profile_id"] == profile and result["poll_s"] == ctx.settings.analytics.growth_poll_s
            assert [row["post_id"] for row in result["posts"]] == [2]
            assert result["posts"][0]["metrics"][0]["views"] == 10
            assert result["analytics"]["history"] == [] and result["analytics"]["accounts"] == {}
            assert result["analytics"]["measured"] == 1 and result["analytics"]["medians"] == {"youtube": 10}
            assert "other" not in result["analytics"]["groups"]["streamer"]
            assert result["supervisor"]["agents"] == [{"id": "researcher", "name": "Researcher", "status": "waiting"}]
            assert "ignored" not in result["local"] and not ctx.pipeline.oauth.calls
            assert not ctx.pipeline.store.writes and ctx.pipeline.account_profiles.holders == 0
    asyncio.run(run())


def test_growth_sync_paginates_and_chunks_without_creating_candidates(tmp_path):
    async def run():
        handler, calls = youtube_handler(75)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            service = Growth(ctx)
            result = await service.sync("default")
            assert result["status"] == "ready" and len(result["videos"]) == 75
            assert result["channel"]["subscribers"] == 100 and result["channel"]["video_count"] == 75
            assert result["videos"][0]["title"] == "Detailed video0" and result["videos"][0]["views"] == 0
            assert [request.url.path.rsplit("/", 1)[-1] for request in calls] == [
                "channels", "playlistItems", "playlistItems", "videos", "videos"]
            assert calls[2].url.params["pageToken"] == "50"
            assert not ctx.pipeline.store.reads and not ctx.pipeline.store.writes
            assert ctx.pipeline.account_profiles.holders == 0
            loaded = service._load("default")
            assert loaded["videos"] == result["videos"]
            assert "owner-token" not in service._cache_path("default").read_text()
    asyncio.run(run())


def test_growth_sync_unknown_statistics_stay_none(tmp_path):
    async def run():
        handler, _ = youtube_handler(incomplete=True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Growth(growth_context(tmp_path, client)).sync("default")
            assert result["videos"][0]["views"] == 0
            assert result["videos"][0]["likes"] is None and result["videos"][0]["comments"] is None
    asyncio.run(run())


def test_growth_cache_is_namespaced_and_embedded_owner_must_match(tmp_path):
    async def run():
        handler, _ = youtube_handler()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            service = Growth(ctx)
            await service.sync("default")
            identity = "a" * 32
            ctx.pipeline.account_profiles.switch(identity)
            result = await service.snapshot()
            assert result["youtube_library"]["videos"] == [] and result["youtube_library"]["channel"] is None
            await service.sync(identity)
            assert service._cache_path("default") != service._cache_path(identity)
            bad = json.loads(service._cache_path(identity).read_text())
            bad["account_profile_id"] = "default"
            service._cache_path(identity).write_text(json.dumps(bad))
            isolated = await service.snapshot()
            assert isolated["youtube_library"]["videos"] == [] and isolated["youtube_library"]["status"] == "error"
    asyncio.run(run())


def test_growth_cooldown_survives_service_recreation_and_wrong_profile_is_409(tmp_path):
    async def run():
        handler, calls = youtube_handler()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            await Growth(ctx).sync("default")
            count = len(calls)
            with pytest.raises(HTTPException) as limited:
                await Growth(ctx).sync("default")
            assert limited.value.status_code == 429 and len(calls) == count
            with pytest.raises(HTTPException) as conflict:
                await Growth(ctx).sync("a" * 32)
            assert conflict.value.status_code == 409 and len(calls) == count
    asyncio.run(run())


def test_growth_api_failure_never_returns_or_persists_raw_credentials(tmp_path):
    async def run():
        handler, _ = youtube_handler(error=403)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            service = Growth(ctx)
            with pytest.raises(HTTPException) as failed:
                await service.sync("default")
            assert failed.value.status_code == 502 and "PRIVATE" not in failed.value.detail
            assert "PRIVATE" not in service._cache_path("default").read_text()
            assert service._load("default")["status"] == "error"
    asyncio.run(run())


def test_growth_busy_switch_lease_and_shutdown_cancel_owned_request(tmp_path):
    async def run():
        started = asyncio.Event()
        async def handler(request):
            started.set()
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            service = Growth(ctx)
            task = asyncio.create_task(service.sync("default"))
            await started.wait()
            with pytest.raises(HTTPException) as busy:
                await service.sync("default")
            assert busy.value.status_code == 409
            with pytest.raises(HTTPException):
                ctx.pipeline.account_profiles.switch("a" * 32)
            await service.close()
            assert task.cancelled() and not service._tasks and ctx.pipeline.account_profiles.holders == 0
            with pytest.raises(HTTPException) as closed:
                await service.sync("default")
            assert closed.value.status_code == 503
    asyncio.run(run())


def test_growth_routes_are_lazy_and_forward_profile_header(tmp_path):
    async def run():
        handler, calls = youtube_handler()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as platform:
            ctx = growth_context(tmp_path, platform)
            app = FastAPI()
            install_growth_routes(app, ctx)
            assert not hasattr(ctx, "growth")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as local:
                response = await local.get("/api/growth")
                assert response.status_code == 200 and not calls
                wrong = await local.post("/api/growth/youtube/sync", headers={"X-Account-Profile": "wrong"})
                assert wrong.status_code == 409 and not calls
                synced = await local.post("/api/growth/youtube/sync", headers={"X-Account-Profile": "default"})
                assert synced.status_code == 200 and synced.json()["status"] == "ready"
            assert growth(ctx) is ctx.growth
            await close_growth(ctx)
            assert ctx.growth._closed
    asyncio.run(run())


def test_growth_sync_limit_and_hidden_subscriber_stats(tmp_path):
    async def run():
        base, calls = youtube_handler(100)
        def handler(request):
            response = base(request)
            if request.url.path.endswith("/channels"):
                data = response.json()
                data["items"][0]["statistics"]["hiddenSubscriberCount"] = True
                return httpx.Response(200, json=data)
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            ctx.settings.analytics.youtube_library_limit = 53
            result = await Growth(ctx).sync("default")
            assert len(result["videos"]) == 53 and result["truncated"]
            assert result["channel"]["subscribers"] is None
            pages = [request for request in calls if request.url.path.endswith("/playlistItems")]
            assert [request.url.params["maxResults"] for request in pages] == ["50", "3"]
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["oversized", "invalid", "foreign", "redirect"])
def test_growth_api_negative_controls_are_bounded_and_private_errors_sanitized(tmp_path, mode):
    async def run():
        calls = []
        base, _ = youtube_handler()
        def handler(request):
            calls.append(request)
            assert request.url.host == "www.googleapis.com"
            if mode == "redirect":
                return httpx.Response(302, headers={"location": "https://attacker.invalid/private"})
            if mode == "oversized":
                return httpx.Response(200, content=b'{"items":[],"secret":"' + b"x" * 131072 + b'"}')
            if mode == "invalid":
                return httpx.Response(200, json={"items": "PRIVATE-TOKEN-SHOULD-NOT-LEAK"})
            response = base(request)
            if request.url.path.endswith("/playlistItems"):
                data = response.json()
                data["items"][0]["snippet"]["videoOwnerChannelId"] = "UCdifferent"
                return httpx.Response(200, json=data)
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            ctx = growth_context(tmp_path, client)
            ctx.settings.analytics.youtube_response_max_bytes = 65536
            service = Growth(ctx)
            with pytest.raises(HTTPException) as failed:
                await service.sync("default")
            assert failed.value.status_code == 502 and "PRIVATE" not in failed.value.detail
            assert "PRIVATE" not in service._cache_path("default").read_text()
            assert not service._load("default")["videos"]
            assert len(calls) == (2 if mode == "foreign" else 1)
    asyncio.run(run())


def test_growth_total_read_deadline_cancels_platform_request(tmp_path):
    async def run():
        finished = asyncio.Event()
        async def handler(request):
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            ctx.settings.analytics = ctx.settings.analytics.model_copy(update={"youtube_sync_timeout_s": 0.01})
            service = Growth(ctx)
            with pytest.raises(HTTPException) as failed:
                await service.sync("default")
            assert failed.value.status_code == 502 and finished.is_set()
            assert not service._tasks and ctx.pipeline.account_profiles.holders == 0
    asyncio.run(run())


@pytest.mark.parametrize("change", [{"access_token": "PRIVATE"}, {"status": []}, {"last_attempt": float("nan")},
    {"videos": [{"id": "other", "token": "PRIVATE"}]}, {"channel": {"id": "other", "token": "PRIVATE"}}])
def test_growth_cache_rejects_unknown_sensitive_fields_and_malformed_data(tmp_path, change):
    async def run():
        handler, _ = youtube_handler()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = Growth(growth_context(tmp_path, client))
            await service.sync("default")
            path = service._cache_path("default")
            data = json.loads(path.read_text())
            data.update(change)
            path.write_text(json.dumps(data))
            result = service._load("default")
            assert result["status"] == "error" and not result["videos"] and result["channel"] is None
            assert "PRIVATE" not in json.dumps(result)
    asyncio.run(run())


def test_growth_cancelled_cache_write_finishes_before_profile_lease_released(tmp_path, monkeypatch):
    import threading
    async def run():
        handler, _ = youtube_handler()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = growth_context(tmp_path, client)
            service = Growth(ctx)
            entered, release = threading.Event(), threading.Event()
            original = service._save
            def blocked_save(*args):
                entered.set()
                release.wait()
                original(*args)
            monkeypatch.setattr(service, "_save", blocked_save)
            task = asyncio.create_task(service.sync("default"))
            await asyncio.to_thread(entered.wait)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and ctx.pipeline.account_profiles.holders == 1
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert ctx.pipeline.account_profiles.holders == 0 and not service._tasks
    asyncio.run(run())
