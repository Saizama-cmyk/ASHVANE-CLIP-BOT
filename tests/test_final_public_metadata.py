"""Finished-media approval must cover public claims and all of its actual inputs."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipbot.config import Settings, resolve_paths
from clipbot.models import Word
from clipbot.pipeline import Pipeline
from clipbot.review import FINAL_CHECKS, final_public_metadata, review_final
from clipbot.scheduler import compose_post, public_snapshot
from tests.test_scheduler import cand


@pytest.fixture
def gate(tmp_path, monkeypatch):
    import clipbot.pipeline as module
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    pipeline = Pipeline(settings, resolve_paths(settings))
    pipeline.vision = object()
    clip = cand(tmp_path)
    pipeline.store.upsert_candidate(clip)
    calls = []

    async def review(candidate, _settings, _vision):
        calls.append(final_public_metadata(candidate, _settings))
        return {"passed": True, "status": "complete", "reason": "Reviewed"}

    monkeypatch.setattr(module, "review_final", review)
    yield pipeline, clip, calls
    pipeline.store.close()


def test_public_context_uses_composed_templates_suffix_tags_and_all_drafts(tmp_path):
    settings = Settings()
    settings.posting.youtube.enabled = True
    settings.posting.title_template = "{title} | {brand}"
    settings.posting.caption_template = "{caption}\n{hashtags}\n{credit}"
    settings.posting.youtube.shorts_suffix = " #Example"
    clip = cand(tmp_path)
    context = final_public_metadata(clip, settings)
    assert context["destinations"]["youtube"] == public_snapshot(compose_post(clip, settings, "youtube"), settings, "youtube")
    assert context["destinations"]["youtube"]["title"].endswith("#Example")
    assert context["destinations"]["youtube"]["tags"] == ["xqc", "clips"]
    assert context["public_copy"]["discord"]["message"] == "Big W"
    assert "_source" not in context["public_copy"]


def test_every_existing_public_field_is_guarded_even_when_disabled(gate):
    pipeline, clip, calls = gate
    pipeline.settings.review.final_review = False
    clip.post_copy["youtube"]["description"] = "Judge confidence: 0.7"
    assert not asyncio.run(pipeline._review_final(clip))
    assert "editorial" in clip.error and not calls


@pytest.mark.parametrize("change", [
    lambda p, c: c.post_copy["youtube"].update(title="Another public title"),
    lambda p, c: c.post_copy["youtube"].update(description="Another description"),
    lambda p, c: c.post_copy["youtube"].update(tags=["another"]),
    lambda p, c: setattr(p.settings.posting, "caption_template", "{caption} A new promise"),
    lambda p, c: setattr(p.settings.posting.youtube, "shorts_suffix", " #New"),
    lambda p, c: setattr(p.settings.posting.youtube, "enabled", True),
    lambda p, c: c.verdict.update(render_timeline={"source_start": 0, "keeps": [[0, 1]], "intro_s": 0, "outro_s": 0, "expected_duration_s": 1}),
    lambda p, c: setattr(c, "transcript", "Different words"),
    lambda p, c: c.words.append(Word(0, 1, "different")),
    lambda p, c: setattr(p.settings.clip, "qc_min_mean_db", -40),
    lambda p, c: setattr(p.settings.edit, "captions", False),
    lambda p, c: setattr(p.settings.safety, "bleep", False),
])
def test_review_cache_invalidates_changed_inputs(gate, change):
    pipeline, clip, calls = gate
    # Composed templates and suffixes are public only for enabled destinations.
    pipeline.settings.posting.youtube.enabled = True
    if "enabled" in change.__code__.co_consts:
        pipeline.settings.posting.youtube.enabled = False

    async def run():
        assert await pipeline._review_final(clip)
        assert await pipeline._review_final(clip)
        assert len(calls) == 1
        change(pipeline, clip)
        assert await pipeline._review_final(clip)
        assert len(calls) == 2

    asyncio.run(run())


def test_review_cache_hashes_bytes_even_with_unchanged_size_and_mtime(gate):
    pipeline, clip, calls = gate
    path = Path(clip.final_path)

    async def run():
        assert await pipeline._review_final(clip)
        stat = path.stat()
        path.write_bytes(b"x" * stat.st_size)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert await pipeline._review_final(clip)
        assert len(calls) == 2

    asyncio.run(run())


def test_policy_version_invalidates_cache_and_account_secrets_do_not(gate, monkeypatch):
    import clipbot.review as module
    pipeline, clip, calls = gate

    async def run():
        assert await pipeline._review_final(clip)
        pipeline.settings.accounts.discord_webhook = "https://example.invalid/private-token"
        assert await pipeline._review_final(clip)
        assert len(calls) == 1
        assert "private-token" not in json.dumps(calls + [clip.verdict["final_review"]])
        monkeypatch.setattr(module, "FINAL_PUBLICATION_POLICY", "test-policy-upgrade")
        assert await pipeline._review_final(clip)
        assert len(calls) == 2

    asyncio.run(run())


def test_custom_prompt_keeps_cut_data_json_and_requires_all_public_claims(tmp_path, monkeypatch):
    import clipbot.review as module
    settings = Settings()
    settings.review.final_prompt = "My custom final-cut instructions."
    clip = cand(tmp_path)
    clip.verdict.update(trim_start=0, trim_end=20)
    clip.post_copy["youtube"]["title"] = "A promise unsupported by the cut"
    captured = {}

    async def probe(*_args):
        return SimpleNamespace(duration=20, width=settings.edit.width, height=settings.edit.height)

    async def quality(*_args):
        return SimpleNamespace(ok=True, black_frac=0)

    async def frames(*_args):
        return [b"frame"]

    async def look(prompt, _images):
        assert prompt.startswith(settings.review.final_prompt)
        assert "honest_hook covers ALL viewer-facing claims" in prompt
        captured.update(json.loads(prompt.split("CUT DATA:\n", 1)[1]))
        return json.dumps({"passed": True, "reason": "Unsupported title claim", "issues": [],
                           "checks": {**dict.fromkeys(FINAL_CHECKS, True), "honest_hook": False},
                           "evidence": [{"at": 1, "detail": "The promised event is absent."}]})

    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", quality)
    monkeypatch.setattr(module, "extract_frames", frames)
    result = asyncio.run(review_final(clip, settings, SimpleNamespace(look=look)))
    assert not result["passed"]
    assert captured["public_metadata"]["public_copy"]["youtube"]["title"].startswith("A promise")
    assert "verdict" not in captured["public_metadata"]


@pytest.mark.parametrize("actual", [18, 22])
def test_saved_timeline_rejects_truncated_or_overlong_exports_before_model(tmp_path, monkeypatch, actual):
    import clipbot.review as module
    settings = Settings()
    clip = cand(tmp_path)
    clip.verdict["render_timeline"] = {"source_start": 0, "keeps": [[0, 20]], "intro_s": 0,
                                        "outro_s": 0, "expected_duration_s": 20}

    async def probe(*_args):
        return SimpleNamespace(duration=actual, width=settings.edit.width, height=settings.edit.height)

    async def never(*_args):
        pytest.fail("Mismatched final duration must hold before technical/model work")

    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", never)
    result = asyncio.run(review_final(clip, settings, SimpleNamespace(look=never)))
    assert not result["passed"] and result["status"] == "complete"
    assert "saved edit timeline" in result["reason"]
