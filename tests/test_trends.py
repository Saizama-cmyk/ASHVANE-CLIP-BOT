"""Trend failures must not erase useful history or become false freshness signals."""
import asyncio
import time
from types import SimpleNamespace

import httpx

from clipbot.config import Settings, resolve_paths
from clipbot.trends import TrendScout, hot_streamers, parse_feed, rank_items, build_brief
from clipbot.discovery import DiscoveryError


def settings_for(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path)
    settings.trends.youtube_channels = ["channel"]
    settings.trends.twitch_clips = False
    return settings


def test_failed_refresh_preserves_sources_and_success_time_across_restart(tmp_path):
    async def run():
        settings = settings_for(tmp_path)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            saved_at = time.time() - 100
            scout.updated = saved_at
            scout.items = [{"id": "old", "channel": "channel", "published": saved_at,
                            "title": "A good moment", "views": 5000}]
            async def fail(_handle, _since):
                raise httpx.ConnectError("Network unavailable")
            scout._channel = fail
            await scout.refresh()
            assert scout.updated == saved_at and scout.items[0]["id"] == "old"
            assert "failed" in scout.status.lower() and scout.errors
            reloaded = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            assert reloaded.items == scout.items and reloaded.updated == saved_at
            assert reloaded.errors
    asyncio.run(run())


def test_disabled_or_expired_trends_do_not_boost_streams(tmp_path):
    async def run():
        settings = settings_for(tmp_path)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            scout.updated = time.time()
            scout.hot = {"twitch": ["streamer"]}
            assert scout.boosted_streamers("twitch") == ["streamer"]
            settings.trends.enabled = False
            assert not scout.boosted_streamers("twitch")
            settings.trends.enabled = True
            settings.trends.boost_streamers = False
            assert not scout.boosted_streamers("twitch")
            settings.trends.boost_streamers = True
            scout.updated = 0
            assert not scout.boosted_streamers("twitch")
    asyncio.run(run())


def test_temporary_short_url_failure_is_not_cached_as_regular_video(tmp_path):
    responses = iter([503, 200])
    async def run():
        settings = settings_for(tmp_path)
        transport = httpx.MockTransport(lambda _request: httpx.Response(next(responses)))
        async with httpx.AsyncClient(transport=transport) as http:
            scout = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            try:
                await scout._is_short("sample")
            except httpx.HTTPStatusError:
                pass
            else:
                raise AssertionError("Temporary upstream failure should remain retryable")
            assert "sample" not in scout._shorts
            assert await scout._is_short("sample")
    asyncio.run(run())


def test_display_names_cannot_poison_discovery_logins():
    clips = [{"broadcaster_name": "国际主播", "view_count": 50000},
             {"broadcaster_name": "Fancy Display Name", "broadcaster_login": "actual_login", "view_count": 100},
             {"broadcaster_login": "invalid name", "view_count": 99999}]
    assert hot_streamers(clips, 5) == ["actual_login"]


def test_twitch_clip_broadcaster_ids_resolve_to_logins_and_survive_restart(tmp_path):
    async def run():
        settings = settings_for(tmp_path)
        settings.trends.youtube_channels = []
        settings.trends.twitch_clips = True
        async def clips(**_kwargs):
            return [{"id": "clip1", "broadcaster_id": "123", "broadcaster_name": "国际主播", "view_count": 5000}]
        async def users(ids):
            assert ids == ["123"]
            return [{"id": "123", "login": "actual_login"}]
        discovery = SimpleNamespace(top_game_ids=["1"], twitch_clips=clips, twitch_users=users)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, discovery, resolve_paths(settings))
            await scout.refresh()
            assert scout.hot["twitch"] == ["actual_login"] and not scout.errors
            reloaded = TrendScout(settings, http, discovery, resolve_paths(settings))
            assert reloaded.hot["twitch"] == ["actual_login"]
    asyncio.run(run())


def test_twitch_api_error_is_a_source_error_and_preserves_saved_clips(tmp_path):
    async def run():
        settings = settings_for(tmp_path)
        settings.trends.youtube_channels = []
        settings.trends.twitch_clips = True
        async def clips(**_kwargs):
            raise DiscoveryError("Twitch rate limited")
        discovery = SimpleNamespace(top_game_ids=["1"], twitch_clips=clips)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, discovery, resolve_paths(settings))
            scout.clips = [{"id": "saved", "broadcaster_login": "actual_login", "view_count": 5000}]
            scout.updated = time.time() - 30
            saved_at = scout.updated
            await scout.refresh()
            assert scout.clips[0]["id"] == "saved" and scout.updated == saved_at
            assert "rate limited" in scout.errors[0] and "retained" in scout.status
    asyncio.run(run())


def test_feed_retains_linked_public_description_and_skips_bad_entries():
    xml = """<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:yt="http://www.youtube.com/xml/schemas/2015"
        xmlns:media="http://search.yahoo.com/mrss/">
        <entry><yt:videoId>good_id</yt:videoId><title>A moment</title>
        <published>2026-10-02T12:00:00Z</published><media:group>
        <media:description>Streamer context &amp; #gaming</media:description>
        <media:community><media:statistics views="50000"/></media:community>
        </media:group></entry>
        <entry><yt:videoId>bad</yt:videoId><title>Bad</title>
        <published>invalid</published></entry></feed>"""
    item, = parse_feed(xml, "channel")
    assert item["description"] == "Streamer context & #gaming"
    assert item["url"] == "https://www.youtube.com/shorts/good_id"


def short(vid, channel, views, published, **extra):
    return dict(id=vid, channel=channel, views=views, published=published, title=vid, **extra)


def test_rank_recent_popularity_and_channel_outlier_not_total_views():
    now = 1_000_000.0
    ranked = rank_items([short("old", "channel", 500000, now - 6 * 86400),
                         short("recent", "channel", 100000, now - 2 * 3600),
                         short("normal", "channel", 10000, now - 2 * 3600)], [], now, 1, 3)
    assert ranked[0]["id"] == "recent"
    assert ranked[0]["estimated_views_per_hour"] == 50000
    assert "measured_views_per_hour" not in ranked[0]
    assert ranked[0]["channel_outlier_ratio"] == 10
    singleton = rank_items([short("only", "other", 100, now)], [], now, 1, 3)[0]
    assert singleton["estimated_views_per_hour"] == 100  # minimum age prevents inflated rates
    assert "channel_outlier_ratio" not in singleton


def test_rank_measures_delta_only_from_earlier_real_observation():
    now = 1_000_000.0
    old = short("measured", "channel", 10000, now - 86400, observed_at=now - 7200)
    current = short("measured", "channel", 13000, now - 86400)
    ranked = rank_items([current, current], [old], now, 1, 3)
    assert len(ranked) == 1
    assert ranked[0]["view_delta"] == 3000
    assert ranked[0]["measurement_hours"] == 2
    assert ranked[0]["measured_views_per_hour"] == ranked[0]["rank_score"] == 1500
    adjusted = rank_items([dict(current, views=9000, measured_views_per_hour=99999)], [old], now, 1, 3)[0]
    assert "measured_views_per_hour" not in adjusted
    assert "measured_views_per_hour" not in rank_items([current], [dict(old, observed_at=now)], now, 1, 3)[0]


def test_partial_failure_keeps_channel_observation_and_deduplicates_cache(tmp_path, monkeypatch):
    async def run():
        settings = settings_for(tmp_path)
        settings.trends.youtube_channels = ["Good", "@good", "failed"]
        settings.trends.min_views = 0
        now = 1_000_000.0
        monkeypatch.setattr("clipbot.trends.time.time", lambda: now)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            scout.updated = now - 7200
            scout.channel_updated = {"failed": now - 7200}
            scout.items = [short("saved", "failed", 10000, now - 86400, observed_at=now - 7200)]
            calls = []
            async def channel(handle, _since):
                calls.append(handle)
                if handle == "failed":
                    raise httpx.ConnectError("Channel offline")
                item = short("new", handle, 50000, now - 3600,
                             description="<b>Actual context</b>\n&amp; details")
                return [item, item]
            scout._channel = channel
            await scout.refresh()
            assert len(calls) == 2
            assert len(scout.items) == 2
            saved = next(it for it in scout.items if it["id"] == "saved")
            fresh = next(it for it in scout.items if it["id"] == "new")
            assert saved["observed_at"] == now - 7200 and saved["retained"]
            assert scout.channel_updated["failed"] == now - 7200
            assert fresh["observed_at"] == now and fresh["description"] == "Actual context & details"
            reloaded = TrendScout(settings, http, scout.discovery, resolve_paths(settings))
            assert reloaded.channel_updated == scout.channel_updated
            assert reloaded.items == scout.items
            assert "retained after failed refresh" in scout.brief("", "")
    asyncio.run(run())


def test_brief_relevant_description_measured_estimated_and_untrusted_data():
    now = 1_000_000.0
    items = rank_items([short("unrelated", "other", 9000000, now - 3600, description="Other game"),
                        short("relevant", "channel", 10000, now - 3600,
                              description="<b>Alice</b> plays Rust\n#rust")], [], now, 1, 3)
    brief = build_brief(items, [], "Rust", "Alice", 1, now, 100)
    assert '"relevant"' in brief and '"unrelated"' not in brief
    assert "Alice plays Rust #rust" in brief and "<b>" not in brief
    assert "https://www.youtube.com/shorts/relevant" in brief
    assert "untrusted style data" in brief and "not measured growth" in brief
    assert "not a global trending chart" in brief and "boilerplate" in brief
    assert "one CAPS word" not in brief and "an emoji or two" not in brief
    items[1].update(measured_views_per_hour=2000, view_delta=4000, measurement_hours=2)
    assert "measured +4,000 views over 2.0h" in build_brief(items, [], "Rust", "Alice", 1, now, 100)
    assert not build_brief(items, [], "Rust", "Alice", 0, now, 100)


def test_partial_refresh_cannot_make_expired_channel_examples_fresh(tmp_path, monkeypatch):
    async def run():
        settings = settings_for(tmp_path)
        settings.trends.youtube_channels = ["good", "failed"]
        settings.trends.min_views = 0
        now = 1_000_000.0
        monkeypatch.setattr("clipbot.trends.time.time", lambda: now)
        async with httpx.AsyncClient() as http:
            scout = TrendScout(settings, http, SimpleNamespace(top_game_ids=[]), resolve_paths(settings))
            scout.updated = now - 8 * 86400
            # Timestamp is stale even if retained publication metadata lies in the window.
            scout.items = [short("expired", "failed", 10000, now - 86400,
                                 observed_at=scout.updated)]
            async def channel(handle, _since):
                if handle == "failed":
                    raise httpx.ConnectError("offline")
                return [short("fresh", handle, 10000, now - 3600)]
            scout._channel = channel
            await scout.refresh()
            assert scout.updated == now
            assert '"expired"' not in scout.brief("", "")
            assert '"fresh"' in scout.brief("", "")
    asyncio.run(run())
