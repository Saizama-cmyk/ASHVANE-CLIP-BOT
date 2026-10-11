"""Reference files stay bounded and private; generated music uses saved observations."""
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import FastAPI
import httpx
import pytest

from clipbot.music_api import install_music_routes
from tests.test_music import context

REF = "fd418df9-209d-4712-9772-26f3f1f24118"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def setup(tmp_path):
    ctx = context(tmp_path)
    app = FastAPI()
    install_music_routes(app, ctx)
    return ctx, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


@pytest.mark.anyio
async def test_upload_preserves_binary_and_cleans_spool(tmp_path, monkeypatch):
    ctx, client = setup(tmp_path)
    original = httpx.AsyncClient
    seen = []
    async def upstream(request):
        seen.append((request.url.path, request.headers, await request.aread()))
        return httpx.Response(202, json={"id": REF, "status": "queued", "audio_url": "/references/media/" + REF})
    monkeypatch.setattr("clipbot.music_api.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
    async with client:
        options = (await client.get("/api/music/references/options")).json()
        assert options["max_upload_bytes"] == ctx.settings.music.reference_upload_max_bytes
        response = await client.post("/api/music/references/upload", content=b"RIFF\x00WAVE\xff", headers={"X-File-Name": quote("My reference é.wav")})
    assert response.status_code == 202, response.text
    assert response.json()["audio_url"] == "/api/music/references/media/" + REF
    assert seen[0][0] == "/api/references/upload"
    assert seen[0][1]["x-file-name"] == quote("My reference é.wav", safe="")
    assert seen[0][2] == b"RIFF\x00WAVE\xff"
    assert not list((ctx.paths.work / "music-reference-uploads").iterdir())


@pytest.mark.anyio
@pytest.mark.parametrize("name,body,status", [("../x.wav", b"x", 422), ("x.exe", b"x", 415), ("x%ZZ.wav", b"x", 422), ("x.wav", b"", 422)])
async def test_bad_upload_never_reaches_service(tmp_path, name, body, status):
    ctx, client = setup(tmp_path)
    async with client:
        result = await client.post("/api/music/references/upload", content=body, headers={"X-File-Name": name})
    assert result.status_code == status


@pytest.mark.anyio
async def test_stream_limit_and_stopped_runtime(tmp_path):
    ctx, client = setup(tmp_path)
    ctx.settings.music.reference_upload_max_bytes = 1024
    async def oversized():
        yield b"x" * 1024
        yield b"x"
    async with client:
        result = await client.post("/api/music/references/upload", content=oversized(), headers={"X-File-Name": "x.wav"})
        assert result.status_code == 413
        assert not list((ctx.paths.work / "music-reference-uploads").iterdir())
        ctx.settings.businesses.resonance_enabled = False
        result = await client.post("/api/music/references/upload", content=b"x", headers={"X-File-Name": "x.wav"})
        assert result.status_code == 409


@pytest.mark.anyio
async def test_reference_context_reaches_writer_without_entering_lyrics(tmp_path):
    ctx, client = setup(tmp_path)
    calls, prompts = [], []
    async def call(method, path, data=None):
        calls.append((method, path, data))
        if method == "GET":
            return {"id": REF, "status": "completed", "tempo_bpm": 88, "caption": "Warm sparse drums", "style_hint": "Restrained groove"}
        return {"id": "take"}
    async def lyrics(data, **kw):
        prompts.append((data, kw))
        return {"title": "New original", "style": "Warm drums", "lyrics": "[Chorus]\nMy own words"}
    ctx.music_bridge.call = call
    ctx.creative_tools = SimpleNamespace(lyrics=lyrics)
    async with client:
        data = {"reference_id": REF, "reference_notes": "Borrow the restraint", "style": "", "lyrics_mode": "generated"}
        response = await client.post("/api/music/create", json=data)
        assert response.status_code == 202, response.text
        assert prompts[0][1]["reference"]["description"] == "Warm sparse drums"
        assert prompts[0][1]["reference"]["what_to_borrow"] == "Borrow the restraint"
        assert calls[-1][2]["reference_id"] == REF
        assert calls[-1][2]["lyrics"] == "[Chorus]\nMy own words"
        response = await client.post("/api/music/lyrics", json={"reference_id": REF, "reference_notes": "Keep spacious", "mode": "rap"})
        assert response.status_code == 200
        assert "reference_id" not in prompts[-1][0]
        assert prompts[-1][1]["reference"]["tempo_estimate_bpm"] == 88


@pytest.mark.anyio
async def test_unfinished_or_invalid_reference_blocks_generation(tmp_path):
    ctx, client = setup(tmp_path)
    async def call(*_):
        return {"id": REF, "status": "running"}
    ctx.music_bridge.call = call
    async with client:
        for path in ("create", "lyrics"):
            result = await client.post("/api/music/" + path, json={"reference_id": REF})
            assert result.status_code == 409
            result = await client.post("/api/music/" + path, json={"reference_id": "../outside"})
            assert result.status_code == 422
        assert (await client.post("/api/music/references/delete-all", json={})).status_code == 404


@pytest.mark.anyio
async def test_upstream_rejection_cleans_spool(tmp_path, monkeypatch):
    ctx, client = setup(tmp_path)
    original = httpx.AsyncClient
    async def reject(request):
        await request.aread()
        return httpx.Response(415, json={"error": "Reference content is not supported"})
    monkeypatch.setattr("clipbot.music_api.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reject), **kw))
    async with client:
        response = await client.post("/api/music/references/upload", content=b"invalid", headers={"X-File-Name": "x.wav"})
    assert response.status_code == 415
    assert not list((ctx.paths.work / "music-reference-uploads").iterdir())


def test_reference_routes_require_real_ashvane_auth(tmp_path):
    import asyncio
    from clipbot.dashboard.server import create_app
    from tests.test_account_profiles import context as account_context
    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, _ = account_context(tmp_path, engine)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(ctx)), base_url="http://127.0.0.1:8787") as client:
                assert (await client.get("/api/music/references")).status_code == 401
                assert (await client.get("/api/music/references/media/" + REF)).status_code == 401
                assert (await client.post("/api/music/references/upload", content=b"x", headers={"X-File-Name": "x.wav", "X-ClipBot": "1"})).status_code == 401
    asyncio.run(run())


@pytest.mark.anyio
async def test_phone_binary_upload_through_real_auth_guard(tmp_path, monkeypatch):
    from clipbot.dashboard.server import create_app
    from tests.test_account_profiles import context as account_context
    original = httpx.AsyncClient
    async with original() as engine:
        ctx, _ = account_context(tmp_path, engine)
        ctx.settings.businesses.resonance_enabled = True
        ctx.paths.work = tmp_path / "work"
        app = create_app(ctx)
        async with original(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8787") as client:
            setup = await client.post("/api/auth/setup", headers={"X-ClipBot": "1"}, json={"name": "Owner", "password": "reference-test-password"})
            assert setup.status_code == 200, setup.text
            login = await client.post("/api/auth/login", headers={"X-ClipBot": "1"}, json={"profile_id": setup.json()["profile"]["id"], "password": "reference-test-password", "device": "phone"})
            token = login.json()["token"]
            client.cookies.clear()
            async def upstream(request):
                assert await request.aread() == b"RIFF-test"
                return httpx.Response(202, json={"id": REF, "status": "queued"})
            monkeypatch.setattr("clipbot.music_api.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
            result = await client.post("/api/music/references/upload", content=b"RIFF-test", headers={"X-ClipBot": "1", "Authorization": "Bearer " + token, "X-File-Name": "phone.wav", "Content-Type": "application/octet-stream"})
            assert result.status_code == 202, result.text
