"""Original-story drafts, render boundaries and durable publishing eligibility."""
import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from clipbot.config import Settings
from clipbot.stories import StoryBusy, StoryStudio


SCRIPT = (
    "The corridor light came on before I touched the switch. I had locked the station "
    "alone, but a figure waited beside the last door. Its coat was mine. When I raised "
    "my hand, it kept both hands still. I stepped backward. It stepped forward. The "
    "speaker whispered my name, then announced that my shift had ended yesterday. "
    "Behind me, the lock clicked. The figure finally smiled and reached for my old key."
)


def settings():
    s = Settings()
    s.stories.model = "test-story-model"
    s.stories.auto_render = False
    s.stories.auto_publish = False
    s.stories.role_max_attempts = 1
    s.stories.jury_revision_attempts = 0
    return s


def story(script=SCRIPT):
    return {"title": "The Last Shift", "script": script,
            "scenes": [{"narration": script, "visual_prompt": "A lone coat-wearing figure in a shuttered station corridor",
                        "visual": {"setting": "station", "subject": "figure", "action": "approach"}}],
            "public_copy": {"youtube": {"title": "Someone was waiting after the last train",
                                           "description": "One locked station. One extra passenger.",
                                           "tags": ["horror story"], "hashtags": ["horror", "shorts"]}}}


def replies(passed=True):
    return [{"title": "The Last Shift", "premise": "A guard meets an impossible double",
             "ending": "The double claims the guard's shift", "beats": ["Strange light", "Unmoving double", "Locked exit"]},
            story(), {"passed": passed, "reason": "PRIVATE JURY: The ending follows the established clues.",
                      "issues": [] if passed else ["The ending needs a clearer consequence."]}]


def client(outputs, calls=None):
    calls = calls if calls is not None else []

    def handler(request):
        calls.append(json.loads(request.content))
        result = outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def studio(tmp_path, http, s=None, lock=None):
    return StoryStudio(s or settings(), http, SimpleNamespace(data=tmp_path), lock)


async def finish(instance):
    if instance._task:
        await asyncio.gather(instance._task, return_exceptions=True)
    await asyncio.sleep(0)


async def draft(instance):
    project = instance.create("The last guard at an empty station", "paranormal", "animated", 60)
    await finish(instance)
    return instance.get(project["id"])


class Renderer:
    capabilities = {"narrator_available": True, "render_available": True,
                    "still_available": True, "animated_available": True}

    def __init__(self):
        self.calls = []

    async def __call__(self, public, directory, settings):
        self.calls.append(copy.deepcopy(public))
        video, audio = directory / "story.mp4", directory / "narration.wav"
        video.write_bytes(b"test render boundary; production renderer probes actual media")
        audio.write_bytes(b"test narration boundary")
        return {"video_path": str(video), "audio_path": str(audio), "duration_s": 38.5,
                "width": 720, "height": 1280, "visual_mode": "shadow_theatre",
                "review": {"passed": False}, "script": "A renderer cannot replace a story"}


async def ready(instance):
    project = await draft(instance)
    instance.renderer = Renderer()
    instance.render(project["id"])
    await finish(instance)
    return instance.get(project["id"])


def test_local_roles_generate_durable_original_fiction_and_private_review(tmp_path):
    async def run():
        calls = []
        async with client(replies(), calls) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            assert project["status"] == "draft"
            assert project["review"]["passed"] is True
            assert project["estimated_duration_s"] > 0
            assert project["public_copy"]["youtube"]["description"].startswith("Original fiction.")
            assert [row["status"] for row in project["agents"]] == ["complete"] * 3
            assert len(calls) == 3
            assert all(call["model"] == "test-story-model" for call in calls)
            assert all("tools" not in call for call in calls)
            assert calls[-1]["options"]["temperature"] == 0
            assert calls[0]["format"]["properties"]["beats"]["items"]["type"] == "string"
            assert "script" not in calls[1]["format"]["properties"]
            assert "PRIVATE JURY" not in calls[1]["messages"][-1]["content"]
            assert json.loads(calls[0]["messages"][-1]["content"])["target_words"] > 0
            loaded = studio(tmp_path, http)
            assert loaded.get(project["id"])["script"] == SCRIPT
            state = instance.state()
            state["projects"][0]["script"] = "Mutation of a UI snapshot"
            assert instance.get(project["id"])["script"] == SCRIPT
            assert state["job"] is None
    asyncio.run(run())


def test_render_receives_no_jury_and_edits_invalidate_output_and_approval(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await ready(instance)
            public = instance.renderer.calls[0]
            assert not {"review", "agents", "error", "publishing"} & public.keys()
            assert "PRIVATE JURY" not in json.dumps(public)
            assert project["status"] == "ready"
            assert project["video_url"] == f"/api/stories/projects/{project['id']}/video"
            assert project["output"]["duration_s"] == 38.5
            assert "review" not in project["output"]
            old_hash = instance.content_fingerprint(project["id"])
            edited = instance.update(project["id"], script=SCRIPT.replace("smiled", "bowed"))
            assert edited["status"] == "draft"
            assert edited["review"]["passed"] is None
            assert edited["output"] == {}
            assert edited["video_url"] == ""
            assert edited["revision"] == 1
            assert instance.content_fingerprint(project["id"]) != old_hash
            assert edited["scenes"][0]["narration"] == edited["script"]
            with pytest.raises(ValueError, match="passing review"):
                instance.record_publish(project["id"], "youtube", "pending")
    asyncio.run(run())


def test_jury_can_reapprove_edited_story_without_rewriting_it(tmp_path):
    async def run():
        outputs = replies() + [{"passed": True, "reason": "The edited manuscript remains coherent.", "issues": []}]
        async with client(outputs) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            instance.update(project["id"], title="The Empty Platform")
            instance.review(project["id"])
            await finish(instance)
            checked = instance.get(project["id"])
            assert checked["status"] == "draft"
            assert checked["review"]["passed"] is True
            assert checked["script"] == SCRIPT
            assert checked["title"] == "The Empty Platform"
    asyncio.run(run())


def test_rejected_story_cannot_render_until_revised_and_checked(tmp_path):
    async def run():
        async with client(replies(False)) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            assert project["status"] == "needs_review"
            instance.renderer = Renderer()
            with pytest.raises(ValueError, match="complete story draft"):
                instance.render(project["id"])
    asyncio.run(run())


def test_cancellation_and_shutdown_release_shared_gpu_and_preserve_project(tmp_path):
    async def run():
        lock = asyncio.Lock()
        await lock.acquire()
        calls = []
        async with client(replies(), calls) as http:
            instance = studio(tmp_path, http, lock=lock)
            project = instance.create("A locked door knows my name", "psychological", "still", 60)
            await asyncio.sleep(0)
            assert instance.busy
            with pytest.raises(StoryBusy):
                instance.create("Another idea", "paranormal", "still", 60)
            with pytest.raises(StoryBusy):
                instance.delete(project["id"])
            await instance.stop()
            assert instance.get(project["id"])["status"] == "interrupted"
            assert not calls
            lock.release()
            async with lock:
                assert lock.locked()
            instance.start()
            instance.retry(project["id"])
            await finish(instance)
            assert instance.get(project["id"])["status"] == "draft"
            assert len(instance.projects) == 1
    asyncio.run(run())


def test_cancel_before_job_first_runs_is_durable(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = instance.create("The last train", "paranormal", "animated", 60)
            assert instance.cancel(project["id"])
            await finish(instance)
            assert instance.get(project["id"])["status"] == "interrupted"
            assert studio(tmp_path, http).get(project["id"])["status"] == "interrupted"
    asyncio.run(run())


@pytest.mark.parametrize("bad_id", ["../outside", "..\\outside", "C:\\Windows", "f" * 31, "f" * 33, "A" * 32, None])
def test_ids_cannot_escape_library(tmp_path, bad_id):
    async def run():
        async with client([]) as http:
            instance = studio(tmp_path, http)
            for operation in (instance.get, instance.delete, instance.cancel):
                with pytest.raises(ValueError, match="Invalid story ID"):
                    operation(bad_id)
    asyncio.run(run())


def test_scene_continuity_and_external_asset_paths_are_rejected_atomically(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            outside = tmp_path / "outside.png"
            outside.write_bytes(b"not an authorized project asset")
            scenes = copy.deepcopy(project["scenes"])
            scenes[0]["asset_path"] = str(outside)
            with pytest.raises(ValueError, match="inside this project's folder"):
                instance.update(project["id"], scenes=scenes)
            with pytest.raises(ValueError, match="match the full script"):
                instance.update(project["id"], script=SCRIPT, scenes=[{**scenes[0], "asset_path": "", "narration": "A different story."}])
            assert instance.get(project["id"])["script"] == SCRIPT
            assert instance.get(project["id"])["review"]["passed"] is True
    asyncio.run(run())


def test_unsafe_model_story_fails_closed_and_never_reaches_jury(tmp_path):
    async def run():
        outputs = replies()
        outputs[1]["scenes"][0]["narration"] = "An omitted story segment."
        calls = []
        async with client(outputs, calls) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            assert project["status"] == "failed"
            assert "match the full script" in project["error"]
            assert len(calls) == 2
            assert project["agents"][-1]["status"] == "skipped"
    asyncio.run(run())


def test_renderer_cannot_publish_arbitrary_files_or_override_story(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            outside = tmp_path / "outside.mp4"
            outside.write_bytes(b"outside")

            async def bad_renderer(public, directory, settings):
                return {"video_path": str(outside), "audio_path": str(outside), "duration_s": 12}

            instance.renderer = bad_renderer
            instance.capabilities = Renderer.capabilities
            instance.render(project["id"])
            await finish(instance)
            result = instance.get(project["id"])
            assert result["status"] == "failed"
            assert result["output"] == {}
            assert "inside this project's folder" in result["error"]
    asyncio.run(run())


def test_restart_recovers_active_jobs_and_ambiguous_uploads(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await ready(instance)
            instance.record_publish(project["id"], "youtube", "uploading")
            loaded = studio(tmp_path, http)
            recovered = loaded.get(project["id"])
            assert recovered["publishing"]["youtube"]["status"] == "uncertain"
            with pytest.raises(StoryBusy, match="reconciliation"):
                loaded.record_publish(project["id"], "youtube", "uploading")
            loaded.record_publish(project["id"], "youtube", "published", external_id="verified-id")
            assert loaded.get(project["id"])["publishing"]["youtube"]["external_id"] == "verified-id"
            saved = json.loads(loaded.cache_path.read_text())
            saved["projects"][0]["status"] = "writing"
            loaded.cache_path.write_text(json.dumps(saved))
            assert studio(tmp_path, http).get(project["id"])["status"] == "interrupted"
    asyncio.run(run())


def test_publication_snapshots_block_duplicates_stale_results_and_edit_races(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await ready(instance)
            pid = project["id"]
            identity = instance.content_fingerprint(pid)
            instance.record_publish(pid, "youtube", "pending", content_hash=identity)
            instance.record_publish(pid, "youtube", "uploading", content_hash=identity, account_id="channel-one")
            for operation in (lambda: instance.update(pid, title="Changed"), lambda: instance.render(pid), lambda: instance.delete(pid)):
                with pytest.raises(StoryBusy, match="upload"):
                    operation()
            with pytest.raises(ValueError, match="does not match"):
                instance.record_publish(pid, "youtube", "published", content_hash="0" * 64)
            instance.record_publish(pid, "youtube", "published", external_id="video-id", url="https://youtube.com/watch?v=video-id")
            with pytest.raises(StoryBusy, match="already"):
                instance.record_publish(pid, "youtube", "pending")
            edited = instance.update(pid, title="A different title")
            assert edited["publishing"]["youtube"]["content_hash"] == identity
            assert edited["revision"] == 1
            assert instance.content_fingerprint(pid) != identity
    asyncio.run(run())


def test_upload_is_not_authorized_when_durable_write_fails(tmp_path, monkeypatch):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await ready(instance)

            def disk_full():
                raise OSError("No space left")

            monkeypatch.setattr(instance, "_save", disk_full)
            with pytest.raises(OSError, match="No space"):
                instance.record_publish(project["id"], "youtube", "uploading")
            assert instance.get(project["id"])["publishing"] == {}
            assert instance.get(project["id"])["status"] == "ready"
    asyncio.run(run())


def test_publication_requires_review_of_the_exact_current_public_content(tmp_path):
    async def run():
        async with client(replies()) as http:
            instance = studio(tmp_path, http)
            project = await ready(instance)
            # Simulate a stale integration bypassing the public edit method.
            instance.projects[0]["public_copy"]["youtube"]["description"] += " Altered after jury approval."
            with pytest.raises(ValueError, match="current passing review"):
                instance.record_publish(project["id"], "youtube", "uploading")
    asyncio.run(run())


def test_writer_repairs_overlong_story_within_bounded_word_budget(tmp_path):
    async def run():
        s = settings()
        s.stories.role_max_attempts = 2
        answers = replies()
        overlong = story((SCRIPT + " ") * 4)
        fixed = story()
        fixed.pop("script")  # production schema narrates once inside scenes
        outputs = [answers[0], overlong, fixed, answers[-1]]
        calls = []
        async with client(outputs, calls) as http:
            instance = studio(tmp_path, http, s)
            project = await draft(instance)
            assert project["status"] == "draft"
            assert project["script"] == SCRIPT
            assert len(calls) == 4
            repair = json.loads(calls[2]["messages"][-1]["content"])
            assert "ENTIRE narration" in repair["repair_required"]
            assert "repair_required" not in project["script"]
    asyncio.run(run())


@pytest.mark.parametrize("revised_passes", [True, False])
def test_private_jury_feedback_gets_one_revision_and_a_fresh_independent_verdict(tmp_path, revised_passes):
    async def run():
        s = settings()
        s.stories.jury_revision_attempts = 1
        outputs = replies(False) + [story(), {"passed": revised_passes, "reason": "The second independent decision.",
                                              "issues": [] if revised_passes else ["The ending is still incomplete."]}]
        calls = []
        async with client(outputs, calls) as http:
            instance = studio(tmp_path, http, s)
            project = await draft(instance)
            assert project["status"] == ("draft" if revised_passes else "needs_review")
            assert project["review"]["passed"] is revised_passes
            assert len(calls) == 5
            assert len(project["review_history"]) == 1
            revision_input = json.loads(calls[3]["messages"][-1]["content"])
            assert "private_editorial_feedback" in revision_input
            fresh_jury_input = json.loads(calls[4]["messages"][-1]["content"])
            assert "private_editorial_feedback" not in fresh_jury_input
            assert "PRIVATE JURY" not in project["script"]
    asyncio.run(run())


def test_revised_narration_cannot_quote_private_jury_feedback(tmp_path):
    async def run():
        s = settings()
        s.stories.jury_revision_attempts = 1
        outputs = replies(False)
        private = "Velvet red lanterns drifted across the frozen harbor before dawn."
        outputs[-1]["reason"] = private
        outputs.append(story(private + " " + SCRIPT))
        async with client(outputs) as http:
            instance = studio(tmp_path, http, s)
            project = await draft(instance)
            assert project["status"] == "failed"
            assert "private" in project["error"] or "internal" in project["error"]
            assert private not in project["script"]
    asyncio.run(run())


def test_writer_ending_is_appended_once_to_exact_public_narration(tmp_path):
    async def run():
        outputs = replies()
        written = outputs[1]
        written.pop("script")
        words = SCRIPT.split()
        opening = copy.deepcopy(written["scenes"][0])
        ending = copy.deepcopy(opening)
        opening["narration"] = " ".join(words[:len(words) // 2])
        ending["narration"] = " ".join(words[len(words) // 2:])
        written["scenes"] = [opening]
        written["ending"] = ending
        calls = []
        async with client(outputs, calls) as http:
            instance = studio(tmp_path, http)
            project = await draft(instance)
            assert project["status"] == "draft"
            assert len(project["scenes"]) == 2
            assert " ".join(project["script"].split()) == SCRIPT
            assert "ending" in calls[1]["format"]["required"]
            assert "ending" not in project
    asyncio.run(run())


def test_writer_repairs_production_directions_before_independent_jury(tmp_path):
    async def run():
        s = settings()
        s.stories.role_max_attempts = 2
        answers = replies()
        bad = story("The camera pulls back. " + SCRIPT)
        calls = []
        async with client([answers[0], bad, story(), answers[-1]], calls) as http:
            instance = studio(tmp_path, http, s)
            project = await draft(instance)
            assert project["status"] == "draft"
            assert project["script"] == SCRIPT
            repair = json.loads(calls[2]["messages"][-1]["content"])
            assert "Production directions" in repair["repair_required"]
    asyncio.run(run())


def test_ai_visual_direction_does_not_limit_story_to_procedural_stage(tmp_path):
    async def run():
        s = settings()
        s.stories.image_backend = "comfyui"
        calls = []
        async with client(replies(), calls) as http:
            instance = studio(tmp_path, http, s)
            project = await draft(instance)
            assert project["status"] == "draft"
            writer_prompt = calls[1]["messages"][0]["content"]
            assert all(call["keep_alive"] == 0 for call in calls)
            assert "do not limit the locations" in writer_prompt
            assert "ONE visible instant" in writer_prompt
            assert "never reveal the full threat" in writer_prompt
            assert "Match the story to these stageable settings" not in writer_prompt
            assert "preserves recurring appearances" in calls[2]["messages"][0]["content"]
            assert project["script"] == SCRIPT
    asyncio.run(run())
