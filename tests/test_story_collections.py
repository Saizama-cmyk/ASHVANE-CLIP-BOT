"""Compilation orchestration boundaries; the compiler suite exercises real AV files."""
import asyncio
import copy
import shutil
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from clipbot.stories import StoryBusy, StoryStudio
from tests.test_stories import client, finish, ready, replies, studio


class Compiler:
    calls = []

    def __init__(self, settings):
        pass

    async def compile(self, inputs, directory, **options):
        self.calls.append(copy.deepcopy(inputs))
        directory.mkdir(parents=True)
        snapshots = []
        for index, row in enumerate(inputs):
            target = directory / f"source-{index}.mp4"
            shutil.copyfile(row["path"], target)
            snapshots.append({"project_id": row["project_id"], "title": row["title"], "file": str(target)})
        video, audio = directory / "story.mp4", directory / "narration.m4a"
        video.write_bytes(b"orchestration fixture; actual AV tested in test_story_compilation")
        audio.write_bytes(b"fixture audio")
        return {"video_path": str(video), "audio_path": str(audio), "duration_s": 80,
            "width": 1280, "height": 720, "source_snapshots": snapshots,
            "chapters": [{"title": options["title"], "start_s": 0, "end_s": 3},
                         {"title": inputs[0]["title"], "start_s": 3, "end_s": 42},
                         {"title": inputs[1]["title"], "start_s": 42, "end_s": 80}]}


def test_collection_is_self_contained_and_uses_existing_publishing_identity(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr("clipbot.story_compilation.StoryCompiler", Compiler)
        Compiler.calls = []
        calls = []
        async with client(replies() + replies(), calls) as http:
            instance = studio(tmp_path, http)
            first, second = await ready(instance), await ready(instance)
            originals = [instance._inside(row["id"], row["output"]["video_path"]) for row in (first, second)]
            instance.renderer = None  # Compilation must not require TTS/image generation.
            created = instance.create_compilation("A collection after midnight", [second["id"], first["id"]])
            assert instance.busy and created["kind"] == "compilation"
            with pytest.raises(StoryBusy):
                instance.create_compilation("Concurrent collection", [first["id"], second["id"]])
            await finish(instance)
            result = instance.get(created["id"])
            assert result["status"] == "ready" and len(calls) == 6
            assert [row["project_id"] for row in Compiler.calls[0]] == [second["id"], first["id"]]
            assert all(path.is_file() for path in originals)
            assert result["review"]["content_hash"] == instance.content_fingerprint(result["id"])
            assert result["review"]["scope"] == "source_approvals_and_assembly"
            description = result["public_copy"]["youtube"]["description"]
            assert "00:00 A collection after midnight" in description and "00:42" in description
            assert "technical checks" not in description and "PRIVATE JURY" not in description
            assert result["account_profile_id"] == "default" and result["publishing"] == {}
            for pid in (first["id"], second["id"]):
                instance.delete(pid)
            copy_text = "Original fiction.\n\nA quiet collection for after midnight."
            changed = instance.update(result["id"], public_copy={"youtube": {"title": result["title"], "description": copy_text, "tags": [], "hashtags": []}})
            assert changed["status"] == "draft" and changed["review"]["passed"] is None
            instance.render(result["id"])
            await finish(instance)
            rebuilt = instance.get(result["id"])
            assert rebuilt["status"] == "ready"
            assert copy_text in rebuilt["public_copy"]["youtube"]["description"]
            assert len(calls) == 6
            loaded = StoryStudio(instance.settings, http, type("Paths", (), {"data": tmp_path})())
            assert loaded.get(result["id"])["status"] == "ready"
            with pytest.raises(ValueError, match="individual stories"):
                instance.update(result["id"], script="A different narration")
    asyncio.run(run())


def test_compilation_api_rejects_stale_profile_before_creating_work(tmp_path, monkeypatch):
    async def run():
        from clipbot.story_api import install_story_routes
        monkeypatch.setattr("clipbot.story_compilation.StoryCompiler", Compiler)
        async with client(replies() + replies()) as model:
            instance = studio(tmp_path, model)
            first, second = await ready(instance), await ready(instance)
            app = FastAPI()
            ctx = SimpleNamespace(settings=instance.settings, pipeline=SimpleNamespace(stories=instance))
            install_story_routes(app, ctx)
            payload = {"title": "API collection", "project_ids": [first["id"], second["id"]], "account_profile_id": "stale"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
                response = await api.post("/api/stories/compilations", json=payload)
                assert response.status_code == 409 and len(instance.projects) == 2
                payload["account_profile_id"] = "default"
                response = await api.post("/api/stories/compilations", json={**payload, "unexpected": True})
                assert response.status_code == 422 and len(instance.projects) == 2
                response = await api.post("/api/stories/compilations", json=payload)
                assert response.status_code == 200 and response.json()["kind"] == "compilation"
                await finish(instance)
                assert instance.get(response.json()["id"])["status"] == "ready"
    asyncio.run(run())


def test_compilation_rechecks_source_titles_against_current_public_guards(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr("clipbot.story_compilation.StoryCompiler", Compiler)
        async with client(replies() + replies()) as http:
            instance = studio(tmp_path, http)
            first, second = await ready(instance), await ready(instance)
            source = instance._find(first["id"])
            source["title"] = "Hook score is high"
            source["review"]["content_hash"] = instance.content_fingerprint(source["id"])
            with pytest.raises(ValueError, match="diagnostic"):
                instance.create_compilation("A harmless collection", [first["id"], second["id"]])
            assert len(instance.projects) == 2 and not instance.busy
    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["duplicate", "profile", "approval", "stale", "stopped"])
def test_collection_admission_preserves_sources_and_rejects_invalid_selection(tmp_path, monkeypatch, invalid):
    async def run():
        monkeypatch.setattr("clipbot.story_compilation.StoryCompiler", Compiler)
        async with client(replies() + replies()) as http:
            instance = studio(tmp_path, http)
            first, second = await ready(instance), await ready(instance)
            ids = [first["id"], second["id"]]
            if invalid == "duplicate":
                ids = [first["id"], first["id"]]
            elif invalid == "profile":
                instance._find(first["id"])["account_profile_id"] = "other"
            elif invalid == "approval":
                instance._find(first["id"])["review"]["passed"] = False
            elif invalid == "stale":
                instance._find(first["id"])["title"] = "Changed after review"
            else:
                instance.settings.businesses.hollow_enabled = False
            with pytest.raises((ValueError, StoryBusy)):
                instance.create_compilation("Collection", ids)
            assert len(instance.projects) == 2
            assert all(row["output"] for row in instance.projects)
    asyncio.run(run())
