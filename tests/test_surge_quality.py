"""Regressions from the real rejected-clip audit; weak clips must still be held."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from clipbot.clipability import enforce_viewer_review, parse_verdict
from clipbot.config import EditCfg, Settings, resolve_paths, upgrade_prompts
from clipbot.editor import render, tighten_spans, probe_media
from clipbot.models import Stage, Word
from clipbot.pipeline import Pipeline
from clipbot.review import final_evidence, review_final
from tests.test_clipability import GOOD, cand
from tests.test_viewer_review import viewer, final


@pytest.mark.parametrize("flag", ["no_joke", "instructional_only", "low_stakes", "uncertain"])
def test_genre_preference_is_not_a_quality_veto(flag):
    settings = Settings()
    verdict = parse_verdict(json.dumps({**GOOD, "viewer_review": viewer(flags=[flag])}), 37, settings)
    assert enforce_viewer_review(verdict, settings)["passed"]
    verdict["viewer_review"]["confidence"] = 0.2
    assert not enforce_viewer_review(verdict, settings)["passed"]


def test_quiet_gameplay_payoff_survives_pause_removal():
    words = [Word(0, 1, "watch"), Word(18, 19, "wow")]
    edit = EditCfg()
    assert not any(a <= 10 <= b for a, b in tighten_spans(words, 0, 20, edit))
    keeps = tighten_spans(words, 0, 20, edit, spike_at=10)
    assert any(a <= 10 - edit.moment_keep_s and b >= 10 + edit.moment_keep_s for a, b in keeps)
    assert sum(b - a for a, b in keeps) < 20


def test_renderer_records_the_actual_shortened_duration(lavfi_clip, tmp_path):
    settings = Settings()
    settings.edit.width, settings.edit.height = 360, 640
    settings.edit.font_size = 18
    timeline = {}
    words = [Word(0, 0.7, "setup"), Word(6, 6.7, "payoff")]
    out = asyncio.run(render(lavfi_clip, tmp_path / "cut.mp4", 0, 8, words, "test", settings,
                             tmp_path / "work", "", timeline=timeline))
    info = asyncio.run(probe_media(out, settings))
    assert timeline["expected_duration_s"] < 4
    assert abs(info.duration - timeline["expected_duration_s"]) < 0.2
    assert len(timeline["keeps"]) == 2


def test_final_review_uses_cut_duration_and_maps_speech_and_evidence(tmp_path, monkeypatch):
    import clipbot.review as module
    settings = Settings()
    candidate = cand()
    candidate.final_path = str(tmp_path / "final.mp4")
    timeline = {"source_start": 10, "keeps": [(0, 2), (10, 13)], "intro_s": 1,
                "outro_s": 0, "expected_duration_s": 6}
    candidate.verdict = {"trim_start": 10, "trim_end": 30, "render_timeline": timeline,
                         "viewer_review": viewer(evidence=[{"at": 21, "detail": "payoff"},
                                                          {"at": 16, "detail": "removed"}])}
    candidate.words = [Word(11, 11.5, "setup"), Word(16, 17, "removed"), Word(21, 22, "payoff")]
    speech, source = final_evidence(candidate, timeline)
    assert speech == "[2.00-2.50] setup\n[4.00-5.00] payoff"
    assert source["evidence"] == [{"at": 4, "detail": "payoff"}]
    checked = []
    async def probe(*_args):
        return SimpleNamespace(duration=6, width=settings.edit.width, height=settings.edit.height)
    async def quality(_path, expected, _settings):
        checked.append(expected)
        return SimpleNamespace(ok=expected == 6, black_frac=0, reason="wrong duration")
    async def frames(*_args):
        return [b"image"]
    async def look(prompt, _images):
        data = json.loads(prompt.split("CUT DATA:\n", 1)[1])
        assert data["speech_in_cut"] == speech and data["source_review"] == source
        return json.dumps(final())
    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", quality)
    monkeypatch.setattr(module, "extract_frames", frames)
    assert asyncio.run(review_final(candidate, settings, SimpleNamespace(look=look)))["passed"]
    assert checked == [6]


def test_invalid_model_response_is_a_failure_not_a_rejection(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    settings.ai.vision_enabled = False
    settings.review.require_vision = False
    pipeline = Pipeline(settings, resolve_paths(settings))
    candidate = cand()
    async def judge(*_args, **_kwargs):
        return {"passed": False, "category": "model_error", "score": 0, "reason": "no JSON object"}
    pipeline.clipability = SimpleNamespace(judge=judge, one_model=lambda: False)
    try:
        asyncio.run(pipeline._think(candidate, 37))
        assert candidate.stage is Stage.FAILED
        assert "no JSON object" in candidate.error and not candidate.post_copy
    finally:
        pipeline.store.close()


@pytest.mark.parametrize("second_score,passed", [(8, True), (4, False)])
def test_second_look_uses_import_threshold_and_accepts_negative_evidence(tmp_path, second_score, passed):
    settings = Settings()
    settings.app.data_dir = str(tmp_path / "data")
    settings.ai.second_look = True
    settings.ai.min_score = 9
    settings.clip_import.min_score = 6
    pipeline = Pipeline(settings, resolve_paths(settings))
    candidate = cand()
    candidate.source = {"type": "twitch_clip"}
    first = {"passed": False, "category": "moment", "score": 5, "reason": "unclear"}
    calls = []
    async def prepare(*_args, **kwargs):
        calls.append("frames")
        assert kwargs["frames"] == settings.ai.second_look_frames
        return SimpleNamespace(text="", times=[0, 10, 20])
    async def judge(_candidate, _duration, threshold, **kwargs):
        calls.append("judge")
        assert threshold == 6 and kwargs["require_review"]
        return {"passed": passed, "category": "moment", "score": second_score, "reason": "denser evidence"}
    async def images(*_args):
        return ["a", "b", "c"]
    pipeline.vision = SimpleNamespace(prepare=prepare)
    pipeline.clipability = SimpleNamespace(one_model=lambda: True, plan=lambda: SimpleNamespace(score_bonus=0), judge=judge)
    pipeline._judge_images = images
    try:
        result = asyncio.run(pipeline._second_look(candidate, first, 37))
        assert calls == ["frames", "judge"] and result["passed"] is passed
        assert result["score"] == second_score and result["second_look"]["frames"] == 3
    finally:
        pipeline.store.close()


def test_custom_review_prompts_are_preserved():
    data = {"review": {"viewer_prompt": "my own judge", "final_prompt": "my own final checker"}}
    assert not upgrade_prompts(data)
    assert data["review"]["viewer_prompt"] == "my own judge"


def test_legacy_export_without_edit_map_is_held_for_rerender_not_rejected(monkeypatch):
    import clipbot.review as module
    settings = Settings()
    candidate = cand()
    candidate.final_path = "legacy.mp4"
    candidate.verdict = {"trim_start": 0, "trim_end": 20}
    async def probe(*_args):
        return SimpleNamespace(duration=10, width=settings.edit.width, height=settings.edit.height)
    monkeypatch.setattr(module, "probe_media", probe)
    result = asyncio.run(review_final(candidate, settings, object()))
    assert not result["passed"] and result["status"] == "unavailable"
    assert "Re-render" in result["reason"]
