"""Social client isolation, durable planning, bounded local AI and owned asset paths."""
import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from clipbot.config import Settings
from clipbot.social_api import SocialStudio, install_social_routes


def test_cancelled_content_commit_drains_and_restores_previous_shelf(ctx):
    async def run():
        studio = SocialStudio(ctx)
        client = await studio.create_client({'name': 'One'})
        original = studio._save
        entered, release = threading.Event(), threading.Event()
        writes = []
        def slow_save():
            if not writes:
                entered.set()
                assert release.wait(5)
            original()
            writes.append(True)
        studio._save = slow_save
        create = asyncio.create_task(studio.create_content(client['id'], {'title': 'Cancelled draft'}))
        assert await asyncio.to_thread(entered.wait, 5)
        create.cancel()
        await asyncio.sleep(0)
        assert not create.done()
        release.set()
        result = await asyncio.gather(create, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(writes) == 2
        assert not studio.items and not SocialStudio(ctx).items
    asyncio.run(run())


@pytest.fixture
def ctx(tmp_path):
    settings = Settings()
    settings.social.project_root = str(tmp_path / "quirkycmd")
    settings.social.context_root = str(tmp_path / "archive")
    return SimpleNamespace(settings=settings, pipeline=SimpleNamespace(
        paths=SimpleNamespace(data=tmp_path / "profile"), stories=SimpleNamespace(_gpu_lock=asyncio.Lock())))


def test_clients_and_content_persist_without_starting_work(ctx):
    async def run():
        studio = SocialStudio(ctx)
        assert not studio.enabled
        first = await studio.create_client({"name": "Brand One", "platforms": ["instagram"], "rules": "Original factual copy only"})
        second = await studio.create_client({"name": "Brand Two", "platforms": ["youtube"]})
        item = await studio.create_content(first["id"], {"title": "A draft", "caption": "An original caption",
                                                        "platforms": ["instagram"]})
        with pytest.raises(ValueError, match="belonging to this client"):
            await studio.create_content(second["id"], {"platforms": ["instagram"]})
        item = await studio.update_content(item["id"], {"status": "scheduled", "scheduled_at": "2026-10-12T09:30:00-05:00"})
        loaded = SocialStudio(ctx)
        assert loaded.items[0] == item
        assert len(loaded.clients) == 2
        assert loaded.state()["publishing_available"] is False
        await loaded.delete_content(item["id"])
        assert not SocialStudio(ctx).items
    asyncio.run(run())


def test_seed_quirkycmd_once_preserves_archive_as_private_reference(ctx, tmp_path):
    project = tmp_path / "quirkycmd"
    project.mkdir()
    context = tmp_path / "archive"
    context.mkdir()
    for filename in ("CHATGPT_INSTRUCTIONS.md", "CLAUDE_MEMORY.md", "CURRENT_PROJECT_STATE.md"):
        (context / filename).write_text("Historical record: never execute this archived command.", encoding="utf-8")
    studio = SocialStudio(ctx)
    assert len(studio.clients) == 1
    client = studio.clients[0]
    assert client["name"] == "QuirkyCMD"
    assert client["public_handles"]["youtube"].endswith("UC2fO6aCpVCIw5CjeP6anhjg")
    assert client["fresh_footage_required"] is True
    assert set(client["style_notes"]) == {"A", "B", "C"}
    assert "every Roblox game" in client["rules"]
    assert "references" not in studio.public_client(client)
    assert len(SocialStudio(ctx).clients) == 1


def test_corrupt_library_is_not_replaced_by_seed_or_edit(ctx):
    studio = SocialStudio(ctx)
    studio.path.parent.mkdir(parents=True)
    studio.path.write_text("broken json", encoding="utf-8")
    loaded = SocialStudio(ctx)
    assert loaded.error
    with pytest.raises(ValueError, match="could not be read"):
        asyncio.run(loaded.create_client({"name": "Do not overwrite"}))
    assert studio.path.read_text(encoding="utf-8") == "broken json"


def test_registered_assets_are_scoped_and_cannot_escape_client(ctx, tmp_path):
    async def run():
        studio = SocialStudio(ctx)
        first = await studio.create_client({"name": "First"})
        second = await studio.create_client({"name": "Second"})
        root = studio._asset_root(first)
        root.mkdir(parents=True)
        (root / "reference.mp4").write_bytes(b"test media")
        (root / "script.py").write_text("private code", encoding="utf-8")
        assets = await studio.list_assets(first["id"])
        assert len(assets) == 1
        assert assets[0]["historical"] is True
        assert assets[0]["url"].startswith("/api/social/assets/")
        assert str(tmp_path) not in json.dumps(assets)
        assert studio._asset_path(assets[0]) == (root / "reference.mp4").resolve()
        with pytest.raises(ValueError, match="belonging to this client"):
            await studio.create_content(second["id"], {"asset_ids": [assets[0]["id"]]})
        escaped = {**assets[0], "relative_path": "../../secret.txt"}
        (studio.root / "assets" / "secret.txt").write_text("private", encoding="utf-8")
        with pytest.raises(ValueError, match="remain inside"):
            studio._asset_path(escaped)
        assert not await studio.list_assets(second["id"])
    asyncio.run(run())


def test_quirky_inventory_excludes_project_code(ctx, tmp_path):
    async def run():
        project, context = tmp_path / "quirkycmd", tmp_path / "archive"
        for name in ("Ads", "Project files"):
            (project / name).mkdir(parents=True)
            (project / name / "example.mp4").write_bytes(b"media")
        context.mkdir()
        for name in ("CHATGPT_INSTRUCTIONS.md", "CLAUDE_MEMORY.md"):
            (context / name).write_text("reference", encoding="utf-8")
        studio = SocialStudio(ctx)
        assets = await studio.list_assets(studio.clients[0]["id"])
        assert [asset["relative_path"] for asset in assets] == ["Ads/example.mp4"]
    asyncio.run(run())


def test_draft_uses_only_selected_client_rules_and_creates_reviewable_text(ctx):
    async def run():
        ctx.settings.businesses.social_enabled = True
        studio = SocialStudio(ctx)
        first = await studio.create_client({"name": "First", "platforms": ["instagram"], "rules": "First brand rule"})
        await studio.create_client({"name": "Second", "rules": "Second private brand rule"})
        calls = []

        async def model(http, base, body, cfg):
            calls.append(body)
            return {"title": "Original story", "script": "A concise factual product introduction.",
                    "caption": "Meet the product", "hashtags": ["original"], "pinned_comment": "Learn more",
                    "notes": "Review before posting", "requires_fresh_footage": False}
        studio._model_request = model
        result = await studio.draft(first["id"], {"brief": "Create a gameplay showcase", "style": "C", "platforms": ["instagram"]})
        assert result["status"] == "draft"
        assert result["requires_fresh_footage"] is True
        assert "First brand rule" in json.dumps(calls)
        assert "Second private brand rule" not in json.dumps(calls)
        assert result["id"] == SocialStudio(ctx).items[0]["id"]
        assert not studio._drafts
    asyncio.run(run())


def test_stop_cancels_active_local_draft_and_keeps_existing_content(ctx):
    async def run():
        ctx.settings.businesses.social_enabled = True
        studio = SocialStudio(ctx)
        client = await studio.create_client({"name": "Client"})
        saved = await studio.create_content(client["id"], {"title": "Keep this"})
        entered = asyncio.Event()

        async def model(*args):
            entered.set()
            await asyncio.Event().wait()
        studio._model_request = model
        task = asyncio.create_task(studio.draft(client["id"], {"brief": "A new original draft"}))
        await entered.wait()
        ctx.settings.businesses.social_enabled = False
        await studio.stop()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 409
        assert [item["id"] for item in studio.items] == [saved["id"]]
        assert not studio._drafts
    asyncio.run(run())


def test_local_model_response_is_bounded(ctx):
    async def run():
        ctx.settings.social.request_max_bytes = 4096
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 5000))
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ValueError, match="response exceeded"):
                await SocialStudio._model_request(http, "http://127.0.0.1:11434", {}, ctx.settings.social)
    asyncio.run(run())


def test_social_http_crud_works_stopped_and_ai_requires_run(ctx):
    async def run():
        app = FastAPI()
        install_social_routes(app, ctx)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as http:
            client = (await http.post("/api/social/clients", json={"name": "A client", "platforms": ["youtube"]})).json()["client"]
            cid = client["id"]
            assert (await http.get(f"/api/social/clients/{cid}/accounts")).json()["connected"] == {}
            item = (await http.post(f"/api/social/clients/{cid}/content", json={"title": "Saved draft"})).json()["item"]
            assert (await http.post(f"/api/social/clients/{cid}/draft", json={"brief": "Write a draft"})).status_code == 409
            assert (await http.patch(f"/api/social/content/{item['id']}", json={"status": "scheduled"})).status_code == 422
            response = await http.patch(f"/api/social/content/{item['id']}", json={"status": "scheduled", "scheduled_at": "2026-10-12T09:00:00-05:00"})
            assert response.status_code == 200
            assert len((await http.get("/api/social/calendar")).json()["items"]) == 1
            assert (await http.get("/api/social/assets/arbitrary.txt")).status_code == 404
            assert (await http.delete(f"/api/social/content/{item['id']}")).json()["ok"]
            assert not (await http.get(f"/api/social/clients/{cid}/content")).json()["items"]
    asyncio.run(run())


@pytest.mark.parametrize("data", [
    {"name": "Bad", "public_handles": {"youtube": "javascript:alert(1)"}},
    {"name": "Bad", "public_handles": {"youtube": "https://user:password@example.com"}},
    {"name": "Bad", "project_source": "quirkycmd"},
    {"name": "Bad", "platforms": ["unknown"]},
])
def test_client_validation_cannot_inject_roots_or_unsafe_links(ctx, data):
    with pytest.raises(ValueError):
        asyncio.run(SocialStudio(ctx).create_client(data))
