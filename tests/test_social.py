"""Social client isolation, durable planning, bounded local AI and owned asset paths."""
import asyncio
import json
import threading
from urllib.parse import quote
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


def test_social_stop_cancels_shared_learning_task_and_reports_busy(ctx):
    from clipbot.creative_tools import CreativeTools
    async def run():
        studio = SocialStudio(ctx)
        ctx.creative_tools = CreativeTools(ctx)
        task = asyncio.create_task(asyncio.Event().wait())
        ctx.creative_tools.tasks["social"].add(task)
        assert studio.state()["busy"]
        await studio.stop()
        assert task.cancelled()
        ctx.creative_tools.tasks["social"].discard(task)
        assert not studio.state()["busy"]
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


def test_legacy_styles_migrate_to_saved_profiles_and_custom_profiles_stay_isolated(ctx):
    async def run():
        studio = SocialStudio(ctx)
        first = await studio.create_client({"name": "First", "style_notes": {"A": "Vertical", "B": "Horizontal", "C": "Short meme captions"}})
        second = await studio.create_client({"name": "Second", "style_notes": {"A": "Second style"}})
        assert {row["id"] for row in studio.style_profiles if row["client_id"] == first["id"]} == {"A", "B", "C"}
        await studio.update_profile(first["id"], "C", {"instructions": "Keep captions synchronized"})
        assert studio._client(first["id"])["style_notes"]["C"] == "Keep captions synchronized"
        assert studio._profile(second["id"], "A")["instructions"] == "Second style"
        profile = await studio.create_profile(first["id"], {"name": "Product graphics", "description": "Custom style", "instructions": "Use calm title reveals"})
        with pytest.raises(KeyError):
            studio._profile(second["id"], profile["id"])
        loaded = SocialStudio(ctx)
        assert loaded._profile(first["id"], profile["id"])["instructions"] == "Use calm title reveals"
        raw = json.loads(studio.path.read_text(encoding="utf-8"))
        raw.pop("style_profiles")
        studio.path.write_text(json.dumps(raw), encoding="utf-8")
        legacy = SocialStudio(ctx)
        assert legacy._profile(first["id"], "C")["instructions"] == "Keep captions synchronized"
    asyncio.run(run())


def test_ideas_allow_empty_brief_and_use_only_client_profile_memory(ctx, monkeypatch):
    async def run():
        from clipbot.creative_memory import creative_memory
        import clipbot.creative_tools as creative_module
        ctx.settings.businesses.social_enabled = True
        studio = ctx.social_studio = SocialStudio(ctx)
        first = await studio.create_client({"name": "First", "platforms": ["youtube"], "style_notes": {"B": "Serious product trailer"}})
        second = await studio.create_client({"name": "Second"})
        await creative_memory(ctx).guidance("social", first["id"], "B", "Keep the opening concise")
        await creative_memory(ctx).guidance("social", second["id"], "", "Private unrelated preference")
        calls = []

        async def chat(business, contract, payload):
            calls.append(payload)
            return {"ideas": [{"title": "Product reveal", "hook": "A clear new opening", "brief": "Introduce the actual product with original feature graphics", "reason": "Fits the saved trailer direction"}]}
        monkeypatch.setattr(creative_module, "creative_tools", lambda ctx: SimpleNamespace(chat=chat))
        result = await studio.ideas(first["id"], {"style_profile_id": "B", "reference_notes": "Study the pacing"})
        assert result["ideas"][0]["brief"]
        assert "not researched" in result["source_basis"]
        assert "Serious product trailer" in json.dumps(calls)
        assert "Keep the opening concise" in json.dumps(calls)
        assert "Private unrelated preference" not in json.dumps(calls)
        assert not studio.items
        ctx.settings.businesses.social_enabled = False
        with pytest.raises(HTTPException) as error:
            await studio.ideas(first["id"], {})
        assert error.value.status_code == 409
    asyncio.run(run())


def test_uploaded_reference_is_owned_bounded_and_persists_as_shared_pending_evidence(ctx):
    async def run():
        from clipbot.creative_memory import creative_memory
        app = FastAPI()
        install_social_routes(app, ctx)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as http:
            client = (await http.post("/api/social/clients", json={"name": "First", "style_notes": {"A": "Vertical product edits"}})).json()["client"]
            path = f"/api/social/clients/{client['id']}/references"
            result = await http.post(path, content=b"Original example with deliberate caption rhythm.", headers={
                "X-Filename": quote("Example style.txt"), "Content-Type": "text/plain", "X-Style-Profile": "A", "X-Reference-Notes": quote("Keep this pacing")})
            assert result.status_code == 200, result.text
            payload = result.json()
            assert payload["asset"]["reference"] and not payload["asset"]["historical"]
            assert payload["analysis"]["status"] == "complete"
            assert payload["asset"]["sha256"]
            saved = (await http.get(f"/api/social/clients/{client['id']}/assets")).json()["assets"]
            assert any(asset["id"] == payload["asset"]["id"] for asset in saved)
            response = await http.get(payload["asset"]["url"])
            assert response.content.startswith(b"Original example")
            assert response.headers["x-content-type-options"] == "nosniff"
            memory = creative_memory(ctx).context("social", client["id"], "A")
            assert memory["reference_guidance"][0]["asset_id"] == payload["asset"]["id"]
            assert memory["reference_guidance"][0]["status"] == "pending"
            assert (await http.post(path, content=b"bad", headers={"X-Filename": "..%2Fsecret.txt"})).status_code == 422
            assert (await http.post(path, content=b"<script>bad</script>", headers={"X-Filename": "fake.png", "Content-Type": "image/png"})).status_code == 415
            assert (await http.post(path, content=b"unsupported", headers={"X-Filename": "payload.html"})).status_code == 415
    asyncio.run(run())


def test_streaming_reference_limit_and_cancel_remove_partial_files(ctx):
    async def run():
        studio = SocialStudio(ctx)
        client = await studio.create_client({"name": "Client"})
        ctx.settings.social.max_asset_bytes = 1048576

        async def excessive():
            yield b"x" * 1048576
            yield b"x"
        request = SimpleNamespace(headers={"x-filename": "too-large.txt"}, stream=excessive)
        with pytest.raises(HTTPException) as error:
            await studio.upload_reference(client["id"], request)
        assert error.value.status_code == 413
        root = studio.root / "references" / client["id"]
        assert not list(root.iterdir())
        entered = asyncio.Event()

        async def interrupted():
            yield b"partial reference"
            entered.set()
            await asyncio.Event().wait()
        request = SimpleNamespace(headers={"x-filename": "interrupted.txt"}, stream=interrupted)
        task = asyncio.create_task(studio.upload_reference(client["id"], request))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list(root.iterdir())
        assert not studio.assets
    asyncio.run(run())


def test_reference_analysis_records_actual_sampled_evidence_and_learns_profile(ctx, monkeypatch, tmp_path):
    async def run():
        import clipbot.editor as editor
        import clipbot.vision as vision
        from clipbot.creative_memory import creative_memory
        import clipbot.creative_tools as creative_module
        ctx.settings.businesses.social_enabled = True
        studio = ctx.social_studio = SocialStudio(ctx)
        client = await studio.create_client({"name": "Client", "style_notes": {"C": "Short original showcase"}})
        observed = []

        async def probe(*args):
            return SimpleNamespace(duration=8, width=1920, height=1080)
        async def frames(*args):
            return [b"actual sampled JPEG"]
        async def look(prompt, images):
            observed.append(images)
            return "Large centered captions; dark background; changing framing in sampled frames."
        async def chat(business, contract, payload):
            assert payload["actual_analysis"]["audio_analyzed"] is False
            return {"summary": "Use deliberate large captions", "rules": ["Keep captions readable over the dark framing"]}
        monkeypatch.setattr(editor, "probe_media", probe)
        monkeypatch.setattr(vision, "extract_frames", frames)
        monkeypatch.setattr(creative_module, "creative_tools", lambda ctx: SimpleNamespace(chat=chat))
        ctx.pipeline.vision = SimpleNamespace(look=look)
        ctx.creative_tools = SimpleNamespace(chat=chat)
        async def stream():
            yield b"....ftypmp42 media reference"
        request = SimpleNamespace(headers={"x-filename": "example.mp4", "content-type": "video/mp4", "x-style-profile": "C"}, stream=stream)
        result = await studio.upload_reference(client["id"], request)
        assert result["analysis"]["status"] == "partial"
        assert result["analysis"]["audio_analyzed"] is False
        assert observed
        memory = creative_memory(ctx).context("social", client["id"], "C")
        assert memory["reference_guidance"][0]["status"] == "learned"
        assert "readable" in memory["reference_guidance"][0]["rules"][0]
        other = await studio.create_client({"name": "Other"})
        assert not creative_memory(ctx).context("social", other["id"], "")["reference_guidance"]
        with pytest.raises(KeyError):
            await studio.analyze_reference(other["id"], result["asset"]["id"], {})
    asyncio.run(run())


def test_pending_reference_can_be_reanalyzed_without_reupload_and_guides_next_draft(ctx):
    async def run():
        from clipbot.creative_memory import creative_memory
        studio = ctx.social_studio = SocialStudio(ctx)
        client = await studio.create_client({"name": "Client", "style_notes": {"A": "Original informative video"}})
        async def stream():
            yield b"Example reference describes a quiet opening and spaced readable captions."
        request = SimpleNamespace(headers={"x-filename": "pacing.txt", "x-style-profile": "A", "x-reference-notes": "Keep%20the%20quiet%20opening"}, stream=stream)
        uploaded = await studio.upload_reference(client["id"], request)
        identifier = uploaded["asset"]["id"]
        assert creative_memory(ctx).context("social", client["id"], "A")["reference_guidance"][0]["status"] == "pending"
        ctx.settings.businesses.social_enabled = True
        async def chat(business, contract, payload):
            assert "quiet opening" in payload["reference_text"]
            assert payload["creator_notes"] == "Keep the quiet opening"
            return {"summary": "Favor a quiet opening", "rules": ["Use spaced, readable captions"]}
        ctx.creative_tools = SimpleNamespace(chat=chat)
        retried = await studio.analyze_reference(client["id"], identifier, {})
        assert retried["asset"]["id"] == identifier
        assert len(studio.assets) == 1
        context = creative_memory(ctx).context("social", client["id"], "A")
        assert context["reference_guidance"][0]["status"] == "learned"
        calls = []
        async def model(http, base, body, cfg):
            calls.append(body)
            return {"title": "Original draft", "script": "A complete original product explanation.", "caption": "Original caption",
                    "hashtags": [], "pinned_comment": "Read more", "notes": "Ready to review", "requires_fresh_footage": False}
        studio._model_request = model
        draft = await studio.draft(client["id"], {"brief": "Create original feature graphics", "style_profile_id": "A",
                                                "reference_notes": "Emphasize clarity", "asset_ids": [identifier]})
        assert "spaced, readable captions" in json.dumps(calls)
        assert "Emphasize clarity" in json.dumps(calls)
        assert draft["asset_ids"] == [identifier]
        assert draft["style"] == "A"
        assert draft["style_profile_id"] == "A"
        assert SocialStudio(ctx)._item(draft["id"])["style_profile_id"] == "A"
    asyncio.run(run())


def test_content_keeps_custom_style_id_after_rename_and_rejects_another_client_profile(ctx):
    async def run():
        studio = SocialStudio(ctx)
        first = await studio.create_client({"name": "First"})
        second = await studio.create_client({"name": "Second"})
        profile = await studio.create_profile(first["id"], {"name": "Slow cinematic", "instructions": "Measured timing"})
        item = await studio.create_content(first["id"], {"title": "Saved idea", "style_profile_id": profile["id"]})
        await studio.update_profile(first["id"], profile["id"], {"name": "New style name"})
        assert SocialStudio(ctx)._item(item["id"])["style_profile_id"] == profile["id"]
        with pytest.raises(KeyError):
            await studio.create_content(second["id"], {"title": "Wrong scope", "style_profile_id": profile["id"]})
    asyncio.run(run())
