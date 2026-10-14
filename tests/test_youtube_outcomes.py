import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from clipbot.analytics import Analytics, compute_insights
from clipbot.config import Settings, resolve_paths
from clipbot.db import Store
from clipbot.publishers.base import PublishError
from clipbot.publishers.oauth import OAuthManager
from clipbot.youtube_outcomes import ANALYTICS_SCOPE, ANALYTICS_URL, FIELDS, collect_outcomes
from tests.test_growth import cand


def report(rows):
    return {'columnHeaders': [{'name': name} for name in ('video', *FIELDS)], 'rows': rows}


def test_outcomes_request_is_read_only_bounded_and_no_missing_zero():
    async def run():
        requests = []

        def respond(request):
            requests.append(request)
            assert request.method == 'GET' and str(request.url).startswith(ANALYTICS_URL)
            assert request.url.params['ids'] == 'channel==MINE'
            assert request.url.params['filters'] == 'video==one,two'
            assert request.headers['authorization'] == 'Bearer synthetic-access'
            return httpx.Response(200, json=report([['one', 1000, 800, 22.5, 125.2, 3]]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            pub = SimpleNamespace(settings=Settings(), http=http, tokens=SimpleNamespace(get=lambda _: {'scope': ANALYTICS_SCOPE}),
                                  oauth=SimpleNamespace(access_token=AsyncMock(return_value='synthetic-access')))
            result = await collect_outcomes(pub, ['one', 'two'])
            assert result['status'] == 'ready'
            assert result['by_id']['one']['average_view_percentage'] == 125.2
            assert result['by_id']['one']['subscribers_gained'] == 3
            assert 'two' not in result['by_id'] and 'synthetic' not in json.dumps(result)
            assert len(requests) == 1
    asyncio.run(run())


@pytest.mark.parametrize('scope,status', [('https://www.googleapis.com/auth/youtube', 'permission_required'),
                                         (ANALYTICS_SCOPE, 'permission_or_api_access_required')])
def test_missing_or_denied_permission_is_explicit(scope, status):
    async def run():
        calls = []
        def denied(request):
            calls.append(request)
            return httpx.Response(403, json={'error': {'message': 'private detail'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(denied)) as http:
            pub = SimpleNamespace(settings=Settings(), http=http, tokens=SimpleNamespace(get=lambda _: {'scope': scope}),
                                  oauth=SimpleNamespace(access_token=AsyncMock(return_value='synthetic-access')))
            result = await collect_outcomes(pub, ['one'])
            assert result['status'] == status and result['by_id'] == {}
            assert len(calls) == (scope == ANALYTICS_SCOPE)
            assert 'private detail' not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize('payload', [report([['unrequested', 1, 1, 1, 1, 1]]),
    report([['one', -1, 1, 1, 1, 1]]), report([['one', True, 1, 1, 1, 1]]),
    {'columnHeaders': [{'name': 'views'}], 'rows': []}])
def test_malformed_or_foreign_outcomes_rejected(payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as http:
            pub = SimpleNamespace(settings=Settings(), http=http, tokens=SimpleNamespace(get=lambda _: {'scope': ANALYTICS_SCOPE}),
                                  oauth=SimpleNamespace(access_token=AsyncMock(return_value='synthetic-access')))
            with pytest.raises(ValueError):
                await collect_outcomes(pub, ['one'])
    asyncio.run(run())


def test_analytics_scope_added_only_for_surge_and_only_when_enabled():
    settings = Settings()
    settings.accounts.youtube_client_id = 'synthetic-id'
    settings.accounts.youtube_client_secret = 'synthetic-secret'
    tokens = SimpleNamespace(get=lambda _: {})
    async def run():
        async with httpx.AsyncClient() as http:
            surge = OAuthManager(settings, http, tokens)
            hollow = OAuthManager(settings, http, tokens, account_section='story_accounts')
            assert ANALYTICS_SCOPE in parse_qs(urlsplit(surge.start_url('youtube')).query)['scope'][0].split()
            assert ANALYTICS_SCOPE not in parse_qs(urlsplit(hollow.start_url('youtube')).query)['scope'][0].split()
            settings.analytics.youtube_outcomes_enabled = False
            assert ANALYTICS_SCOPE not in parse_qs(urlsplit(surge.start_url('youtube')).query)['scope'][0].split()
    asyncio.run(run())


def test_watch_learning_needs_sample_and_outcomes_store_never_crosses_profiles(tmp_path):
    settings = Settings()
    settings.analytics.min_posts = 2
    posts = [{'post_id': index, 'posted_at': 1, 'platform': 'youtube', 'source': 'twitch',
              'streamer': name, 'category': '', 'kind': '', 'title': name, 'display_name': name, 'url': ''}
             for index, name in enumerate(('a', 'b'), 1)]
    metrics = {index: [{'captured_at': 1 + 25 * 3600, 'views': 1000, 'likes': 10, 'comments': 0, 'shares': 0}]
               for index in (1, 2)}
    outcomes = {index: {'engaged_views': 1000, 'average_view_percentage': watched, 'subscribers_gained': subs}
                for index, watched, subs in ((1, 120, 3), (2, 30, 0))}
    control = compute_insights(posts, metrics, settings)
    assert all(row['score'] == 0 for row in control.groups['streamer'].values())
    sparse = compute_insights(posts, metrics, settings, outcomes={1: outcomes[1]})
    assert sparse.groups == control.groups
    learned = compute_insights(posts, metrics, settings, outcomes=outcomes)
    assert learned.groups['streamer']['twitch:a']['score'] > 0 > learned.groups['streamer']['twitch:b']['score']
    with_store = Store(tmp_path / 'db')
    try:
        with_store.record_outcome(1, 'default', outcomes[1])
        with_store.record_outcome(1, 'a' * 32, outcomes[2])
        assert with_store.outcomes_for([1], 'default')[1]['average_view_percentage'] == 120
        assert with_store.outcomes_for([1], 'a' * 32)[1]['average_view_percentage'] == 30
        assert with_store.outcomes_for([1], 'b' * 32) == {}
    finally:
        with_store.close()


def test_refresh_holds_profile_lease_filters_posts_and_resets_steering(tmp_path):
    async def run():
        settings = Settings()
        paths = SimpleNamespace(data=tmp_path)
        store = Store(tmp_path / 'db')
        held = []

        class Profiles:
            current = 'default'
            def active_id(self, business):
                return self.current
            @asynccontextmanager
            async def upload(self, business):
                held.append(self.current)
                try:
                    yield
                finally:
                    held.pop()

        profiles = Profiles()
        queried = []
        class Publisher:
            def configured(self):
                return True, ''
            async def metrics(self, ids):
                assert held == ['default']
                queried.extend(ids)
                return {value: {'views': 1000, 'likes': 1, 'comments': 0, 'shares': 0, 'saves': 0} for value in ids}
            async def account(self):
                return None
            async def outcomes(self, ids):
                assert held == ['default']
                return {'status': 'permission_required', 'by_id': {}}
        analytics = Analytics(settings, store, {'youtube': Publisher()}, paths)
        analytics.account_profiles = profiles
        try:
            for identity, remote in (('default', 'mine'), ('a' * 32, 'other')):
                candidate = cand(source={'account_profile_id': identity})
                store.upsert_candidate(candidate)
                store.record_post(candidate.id, 'youtube', remote, '', 'ok')
            await analytics.tick(force=True, expected_profile='default')
            assert queried == ['mine'] and held == []
            assert analytics.snapshot()['youtube_outcomes'] == 'permission_required'
            analytics.insights.measured = 100
            analytics.select_profile('a' * 32)
            assert not analytics.active and analytics.insights.measured == 0
            profiles.current = 'a' * 32
            with pytest.raises(PublishError, match='profile changed'):
                await analytics.tick(force=True, expected_profile='default')
            assert queried == ['mine']
        finally:
            store.close()
    asyncio.run(run())


def test_report_respects_provider_batch_and_byte_limits():
    async def run():
        settings = Settings()
        settings.analytics.youtube_library_limit = 500
        calls = []
        def respond(request):
            count = len(request.url.params['filters'].removeprefix('video==').split(','))
            calls.append(count)
            assert count <= 200 and int(request.url.params['maxResults']) == count
            return httpx.Response(200, json=report([]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            pub = SimpleNamespace(settings=settings, http=http, tokens=SimpleNamespace(get=lambda _: {'scope': ANALYTICS_SCOPE}),
                                  oauth=SimpleNamespace(access_token=AsyncMock(return_value='synthetic-access')))
            result = await collect_outcomes(pub, ['v' + str(index) for index in range(501)])
            assert calls == [200, 200, 100] and result['truncated'] and result['status'] == 'no_data'
        settings.analytics.youtube_response_max_bytes = 65536
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'x' * 65537))) as http:
            pub.http = http
            with pytest.raises(ValueError, match='configured limit'):
                await collect_outcomes(pub, ['one'])
    asyncio.run(run())


def test_cancelled_profile_write_drains_before_lease_is_released(tmp_path, monkeypatch):
    import threading

    async def run():
        store = Store(tmp_path / 'db')
        analytics = Analytics(Settings(), store, {}, SimpleNamespace(data=tmp_path))
        entered, release = threading.Event(), threading.Event()
        held = []
        class Profiles:
            def active_id(self, business):
                return 'default'
            @asynccontextmanager
            async def upload(self, business):
                held.append(True)
                try:
                    yield
                finally:
                    held.pop()
        analytics.account_profiles = Profiles()
        def save():
            entered.set()
            assert release.wait(5)
            assert held == [True]
        monkeypatch.setattr(analytics, '_save', save)
        task = asyncio.create_task(analytics.tick(force=True))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and held == [True]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert held == []
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            store.close()
    asyncio.run(run())
