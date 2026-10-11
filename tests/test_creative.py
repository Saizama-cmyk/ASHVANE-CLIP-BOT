"""Blank generation, manual text preservation, and durable scoped creative memory."""
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from clipbot.config import Settings, resolve_paths
from clipbot.creative_memory import CreativeMemory, creative_memory, install_creative_memory_routes
from clipbot.creative_tools import CreativeTools
from clipbot.music_api import install_music_routes
from clipbot.story_api import install_story_routes


@pytest.fixture
def anyio_backend():
    return "asyncio"


def context(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path)
    settings.businesses.hollow_enabled = True
    settings.businesses.resonance_enabled = True
    return SimpleNamespace(settings=settings, paths=resolve_paths(settings))


@pytest.mark.anyio
async def test_blank_story_ideas_use_real_formats_and_saved_feedback(tmp_path):
    ctx = context(tmp_path)
    memory = creative_memory(ctx)
    await memory.guidance("stories", "", "", "Earn the final reveal")
    await memory.feedback("stories", "", "", {"verdict": "disliked", "notes": "Too many unexplained twists"})
    service = CreativeTools(ctx)
    async def chat(business, contract, payload):
        assert business == "stories"
        assert payload["saved_creative_memory"]["guidance"] == "Earn the final reveal"
        assert payload["saved_creative_memory"]["feedback"][0]["notes"] == "Too many unexplained twists"
        return {"ideas": [{"title": "Last passenger", "premise": "A guard recognizes his missing brother on the last empty train", "reason": "A specific emotional stake"}]}
    service.chat = chat
    assert (await service.story_ideas({"format": "still"}))["ideas"][0]["premise"]
    with pytest.raises(HTTPException):
        await service.story_ideas({"format": "invented"})


@pytest.mark.anyio
async def test_story_create_generates_only_missing_generated_premise(tmp_path):
    ctx = context(tmp_path)
    calls = []
    studio = SimpleNamespace(create=lambda *args: calls.append(args) or {"topic": args[0]})
    ctx.pipeline = SimpleNamespace(stories=studio)
    async def ideas(data):
        return {"ideas": [{"premise": "Generated original premise"}]}
    ctx.creative_tools = SimpleNamespace(story_ideas=ideas)
    app = FastAPI()
    install_story_routes(app, ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/stories/projects", json={"topic_mode": "generated"})
        assert response.status_code == 200 and calls[-1][0] == "Generated original premise"
        await client.post("/api/stories/projects", json={"topic_mode": "given", "topic": "My own idea"})
        assert calls[-1][0] == "My own idea"
        await client.post("/api/stories/projects", json={"topic_mode": "generated", "topic": "Chosen idea"})
        assert calls[-1][0] == "Chosen idea"
        assert (await client.post("/api/stories/projects", json={"topic_mode": "invalid"})).status_code == 422


@pytest.mark.anyio
async def test_music_blank_create_generates_style_and_lyrics_but_preserves_given_words(tmp_path):
    ctx = context(tmp_path)
    app = FastAPI()
    install_music_routes(app, ctx)
    forwarded, generated = [], []
    async def call(method, path, payload=None):
        forwarded.append(payload)
        return {"id": "queued"}
    async def lyrics(data):
        generated.append(data)
        return {"title": "New take", "style": "Sparse warm soul, swung drums, intimate piano", "lyrics": "Original words" if data["mode"] != "instrumental" else ""}
    ctx.music_bridge.call = call
    ctx.creative_tools = SimpleNamespace(lyrics=lyrics)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/music/create", json={"lyrics_mode": "generated", "style": "", "lyrics": ""})
        assert response.status_code == 202
        assert forwarded[-1]["style"] and forwarded[-1]["lyrics"] == "Original words"
        assert "lyrics_mode" not in forwarded[-1]
        await client.post("/api/music/create", json={"lyrics_mode": "given", "style": "", "lyrics": "My unchanged words"})
        assert forwarded[-1]["lyrics"] == "My unchanged words" and generated[-1]["mode"] == "instrumental"
        await client.post("/api/music/create", json={"lyrics_mode": "given", "style": "Original beat", "lyrics": ""})
        assert forwarded[-1]["lyrics"] == "" and len(generated) == 2
        ctx.settings.businesses.resonance_enabled = False
        assert (await client.post("/api/music/lyrics", json={})).status_code == 409


@pytest.mark.anyio
async def test_memory_persists_without_cross_business_leakage_and_preserves_corrupt_file(tmp_path):
    ctx = context(tmp_path)
    memory = CreativeMemory(ctx)
    await memory.guidance("music", "", "", "Less reverb on vocals")
    await memory.feedback("music", "", "", {"verdict": "liked", "notes": "The sparse chorus worked"})
    restored = CreativeMemory(ctx)
    assert restored.context("music")["feedback"]
    assert restored.context("stories")["guidance"] == ""
    with pytest.raises(HTTPException):
        restored.context("music", "another-client")
    memory.path.write_text("{broken", encoding="utf-8")
    damaged = CreativeMemory(ctx)
    with pytest.raises(HTTPException):
        await damaged.guidance("music", "", "", "New direction")
    assert memory.path.read_text(encoding="utf-8") == "{broken"


@pytest.mark.anyio
async def test_pending_reference_does_not_claim_observation_or_overwrite_creator_guidance(tmp_path):
    ctx = context(tmp_path)
    ctx.settings.businesses.resonance_enabled = False
    memory = CreativeMemory(ctx)
    await memory.guidance("music", "", "", "Keep my own production direction")
    result = await memory.learn_reference("music", asset={"id": "owned", "name": "reference.wav", "kind": "audio"}, notes="Warm low end")
    assert result["guidance"] == "Keep my own production direction"
    assert result["reference_guidance"][0]["status"] == "pending"
    assert not result["reference_guidance"][0]["rules"]


@pytest.mark.anyio
async def test_account_profiles_keep_learning_separate_and_allow_bound_feedback_after_switch(tmp_path):
    ctx = context(tmp_path)
    active = {"music": "default"}
    def get(business, identity):
        assert business == "music" and identity in {"default", "artist-two"}
        return {"id": identity}
    ctx.pipeline = SimpleNamespace(account_profiles=SimpleNamespace(active_id=lambda business: active[business], get=get))
    memory = CreativeMemory(ctx)
    await memory.guidance("music", "", "", "Warm acoustic artist")
    active["music"] = "artist-two"
    assert memory.context("music")["guidance"] == ""
    await memory.guidance("music", "", "", "Sparse electronic artist")
    await memory.feedback("music", "", "", {"verdict": "liked", "notes": "Acoustic chorus worked", "account_profile_id": "default"})
    assert not memory.context("music")["feedback"]
    first = memory.context("music", account_profile_id="default")
    assert first["guidance"] == "Warm acoustic artist" and first["feedback"][0]["notes"] == "Acoustic chorus worked"
    assert memory.context("music")["guidance"] == "Sparse electronic artist"


@pytest.mark.anyio
async def test_cancellation_reaches_waiting_creative_request(tmp_path):
    service = CreativeTools(context(tmp_path))
    entered = asyncio.Event()
    async def work():
        service.tasks["music"].add(asyncio.current_task())
        entered.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(work())
    await entered.wait()
    await service.cancel_business("music")
    assert task.cancelled()


@pytest.mark.anyio
async def test_generated_outputs_keep_the_profile_whose_guidance_was_used(tmp_path):
    ctx = context(tmp_path)
    active = {"stories": "default", "music": "default"}
    ctx.pipeline = SimpleNamespace(account_profiles=SimpleNamespace(
        active_id=lambda business: active[business], get=lambda business, identity: {"id": identity}))
    service = CreativeTools(ctx)
    async def chat(business, contract, payload):
        assert payload["saved_creative_memory"]["account_profile_id"] == "default"
        active[business] = "other"
        return ({"ideas": [{"title": "The last stop", "premise": "A night driver keeps finding the same passenger."}]}
                if business == "stories" else {"title": "Homeward", "style": "Warm acoustic soul", "lyrics": "Find the light at home"})
    service.chat = chat
    assert (await service.story_ideas({}))["account_profile_id"] == "default"
    assert (await service.lyrics({}))["account_profile_id"] == "default"
