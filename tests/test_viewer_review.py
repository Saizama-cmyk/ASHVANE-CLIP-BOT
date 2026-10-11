"""Quality gates must fail when a high score conceals a weak or unverified cut."""
import asyncio
import json

import httpx
import pytest

from clipbot.clipability import (BadModelOutput, Clipability, enforce_viewer_review,
                                parse_verdict)
from clipbot.config import Settings, merge_incoming
from clipbot.review import FINAL_CHECKS, parse_final_review
from clipbot.vision import sequence_times
from tests.test_clipability import GOOD, cand


def viewer(**changes):
    return {"hook": 8, "context": 8, "payoff": 9, "pacing": 8, "confidence": 0.9,
            "why_watch": "The unexpected miss lands at 20s and the reaction completes the joke.",
            "why_skip": "None observed", "evidence": [{"at": 20, "detail": "Miss followed by disbelief"}],
            "flags": [], **changes}


@pytest.mark.parametrize("change", [{"payoff": 2}, {"confidence": 0.3},
                                    {"evidence": []}, {"flags": ["missing_payoff"]}])
def test_high_score_does_not_override_viewer_defects(change):
    settings = Settings()
    raw = parse_verdict(json.dumps({**GOOD, "score": 10, "viewer_review": viewer(**change)}), 37, settings)
    assert not enforce_viewer_review(raw, settings)["passed"]


def test_concrete_self_contained_clip_passes():
    settings = Settings()
    result = parse_verdict(json.dumps({**GOOD, "viewer_review": viewer()}), 37, settings)
    assert enforce_viewer_review(result, settings)["passed"]


def test_old_model_output_is_held_when_review_required():
    assert not enforce_viewer_review(parse_verdict(json.dumps(GOOD), 37, Settings()), Settings())["passed"]


@pytest.mark.parametrize("field,value", [("score", float("nan")), ("trim_start", float("inf")),
                                          ("trim_end", float("nan")), ("peak_at", float("nan"))])
def test_nonfinite_judge_numbers_rejected(field, value):
    with pytest.raises(BadModelOutput):
        parse_verdict(json.dumps({**GOOD, field: value}), 37, Settings())


def test_null_title_cannot_become_a_passing_literal_none_title():
    with pytest.raises(BadModelOutput):
        parse_verdict(json.dumps({**GOOD, "title": None}), 37, Settings())


def test_evidence_outside_the_trim_cannot_earn_a_pass():
    with pytest.raises(BadModelOutput):
        parse_verdict(json.dumps({**GOOD, "viewer_review": viewer(evidence=[{"at": 36, "detail": "outside cut"}])}), 37, Settings())


def test_actual_frames_reach_the_judge_in_order():
    calls = []
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": json.dumps({**GOOD, "viewer_review": viewer()})}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            c = cand()
            c.frame_times = [0, 20, 36]
            return await Clipability(Settings(), http).judge(c, 37, images=["a", "b", "c"], require_review=True)
    assert asyncio.run(run())["passed"]
    msg = calls[0]["messages"][-1]
    assert msg["images"] == ["a", "b", "c"] and "frame 2 = 20.00s" in msg["content"]
    assert calls[0]["options"]["num_predict"] == Settings().review.max_tokens


def test_omitted_viewer_object_gets_bounded_format_repair_without_dropping_frames():
    calls = []
    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        response = GOOD if len(calls) == 1 else {**GOOD, "viewer_review": viewer()}
        return httpx.Response(200, json={"message": {"content": json.dumps(response)}})
    async def run():
        settings = Settings()
        settings.ai.retries = 1
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            candidate = cand()
            candidate.frame_times = [0, 20, 36]
            return await Clipability(settings, http).judge(candidate, 37, images=["a", "b", "c"], require_review=True)
    assert asyncio.run(run())["passed"] and len(calls) == 2
    assert "viewer_review" in calls[-1]["messages"][-1]["content"]
    assert calls[-1]["messages"][1]["images"] == ["a", "b", "c"]


def test_genuine_viewer_defect_does_not_retry_until_it_gets_an_approval():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"message": {"content": json.dumps({**GOOD, "viewer_review": viewer(payoff=1)})}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await Clipability(Settings(), http).judge(cand(), 37, require_review=True)
    assert not asyncio.run(run())["passed"] and len(calls) == 1


def test_text_only_judge_is_not_sent_images():
    calls = []
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)}})
    async def run():
        s = merge_incoming(Settings(), {"ai": {"judge_profile": "custom", "single_model": False}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await Clipability(s, http).judge(cand(), 37, images=["a"])
    asyncio.run(run())
    assert "images" not in calls[0]["messages"][-1]


def final(**changes):
    return {"passed": True, "reason": "The cut keeps the action visible and ends after the payoff.",
            "checks": dict.fromkeys(FINAL_CHECKS, True), "issues": [],
            "evidence": [{"at": 2, "detail": "Readable captions and visible main subject"}], **changes}


def test_final_review_aligns_speech_to_the_rendered_cut(tmp_path, monkeypatch):
    import clipbot.review as module
    from clipbot.models import Word
    from types import SimpleNamespace
    settings = Settings()
    candidate = cand()
    candidate.final_path = str(tmp_path / "final.mp4")
    candidate.verdict = {"trim_start": 9, "trim_end": 34}
    candidate.words = [Word(8.8, 9.3, "hello"), Word(12, 12.5, "there"), Word(35, 36, "outside")]
    captured = {}
    async def probe(*_args):
        return SimpleNamespace(duration=25, width=settings.edit.width, height=settings.edit.height)
    async def quality(*_args):
        return SimpleNamespace(ok=True, black_frac=0)
    async def frames(*_args):
        return [b"image"]
    async def look(prompt, images):
        captured.update(json.loads(prompt.split("CUT DATA:\n", 1)[1]))
        assert "subtitle fragment" in prompt and images
        return json.dumps(final())
    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", quality)
    monkeypatch.setattr(module, "extract_frames", frames)
    result = asyncio.run(module.review_final(candidate, settings, SimpleNamespace(look=look)))
    assert result["passed"]
    assert captured["speech_in_cut"] == "[0.00-0.30] hello\n[3.00-3.50] there"
    assert captured["hook"] == ""


@pytest.mark.parametrize("change", [{"checks": {**dict.fromkeys(FINAL_CHECKS, True), "crop": False}},
                                    {"issues": ["Caption hides the subject"]}, {"evidence": []}])
def test_final_review_cannot_rubber_stamp(change):
    assert not parse_final_review(json.dumps(final(**change)), 20)["passed"]


def test_optimistic_final_note_cannot_hide_missing_evidence():
    result = parse_final_review(json.dumps(final(evidence=[], reason="All checks passed")), 20)
    assert not result["passed"] and "no timestamped evidence" in result["reason"]


@pytest.mark.parametrize("correct_on_retry", [True, False])
def test_finished_review_repairs_missing_evidence_within_retry_budget(monkeypatch, correct_on_retry):
    import clipbot.review as module
    from types import SimpleNamespace
    settings = Settings()
    settings.ai.retries = 1
    candidate = cand()
    candidate.final_path = "isolated-test.mp4"
    candidate.verdict = {"trim_start": 0, "trim_end": 20}
    calls = []
    async def probe(*_args):
        return SimpleNamespace(duration=20, width=settings.edit.width, height=settings.edit.height)
    async def quality(*_args):
        return SimpleNamespace(ok=True, black_frac=0)
    async def frames(*_args):
        return [b"image"]
    async def look(prompt, _images):
        calls.append(prompt)
        return json.dumps(final() if len(calls) == 2 and correct_on_retry else final(evidence=[]))
    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", quality)
    monkeypatch.setattr(module, "extract_frames", frames)
    result = asyncio.run(module.review_final(candidate, settings, SimpleNamespace(look=look)))
    assert len(calls) == 2 and "Validation failed" in calls[-1]
    assert all(prompt.count(settings.review.final_prompt) == 1 for prompt in calls)
    assert calls[-1].startswith(calls[0]) and "Preserve your actual quality assessment" in calls[-1]
    assert result["passed"] is correct_on_retry
    if not correct_on_retry:
        assert "no timestamped evidence" in result["reason"]


def test_final_review_requires_real_booleans_and_all_checks():
    with pytest.raises(BadModelOutput):
        parse_final_review(json.dumps(final(passed="true")), 20)
    with pytest.raises(BadModelOutput):
        parse_final_review(json.dumps(final(checks={"crop": True})), 20)


@pytest.mark.parametrize("at", [True, False])
def test_boolean_final_evidence_timestamp_is_not_an_observation(at):
    with pytest.raises(BadModelOutput, match="invalid final-cut observation"):
        parse_final_review(json.dumps(final(evidence=[{"at": at, "detail": "Readable captions"}])), 20)


@pytest.mark.parametrize("defect", [
    {"checks": {**dict.fromkeys(FINAL_CHECKS, True), "crop": False}},
    {"issues": ["Caption hides the subject"]},
    {"passed": False, "reason": "No payoff is visible", "evidence": []},
])
def test_final_quality_defect_is_held_without_retrying_for_approval(monkeypatch, caplog, defect):
    import clipbot.review as module
    from types import SimpleNamespace
    settings = Settings()
    settings.ai.retries = 2
    candidate = cand()
    candidate.final_path = "isolated-test.mp4"
    candidate.verdict = {"trim_start": 0, "trim_end": 20}
    calls = []
    async def probe(*_args):
        return SimpleNamespace(duration=20, width=settings.edit.width, height=settings.edit.height)
    async def quality(*_args):
        return SimpleNamespace(ok=True, black_frac=0)
    async def frames(*_args):
        return [b"image"]
    async def look(prompt, images):
        calls.append((prompt, images))
        return json.dumps(final(**defect))
    monkeypatch.setattr(module, "probe_media", probe)
    monkeypatch.setattr(module, "quality_check", quality)
    monkeypatch.setattr(module, "extract_frames", frames)
    with caplog.at_level("INFO", logger="clipbot.review"):
        result = asyncio.run(module.review_final(candidate, settings, SimpleNamespace(look=look)))
    assert not result["passed"] and result["status"] == "complete" and len(calls) == 1
    assert all(stage in caplog.text for stage in ("media probe", "technical checks", "frame extraction", "model attempt 1"))
    assert settings.review.final_prompt not in caplog.text and "CUT DATA" not in caplog.text


@pytest.mark.parametrize("value", [None, True, 42, {"claim": "good"}])
def test_null_or_structured_explanation_cannot_become_fake_evidence(value):
    with pytest.raises(BadModelOutput):
        parse_final_review(json.dumps(final(reason=value)), 20)
    with pytest.raises(BadModelOutput):
        parse_final_review(json.dumps(final(evidence=[{"at": 2, "detail": value}])), 20)
    with pytest.raises(BadModelOutput):
        parse_verdict(json.dumps({**GOOD, "viewer_review": viewer(why_watch=value)}), 37, Settings())
    with pytest.raises(BadModelOutput):
        parse_verdict(json.dumps({**GOOD, "viewer_review": viewer(evidence=[{"at": 20, "detail": value}])}), 37, Settings())


def test_sequence_samples_the_opening_peak_and_ending():
    times = sequence_times(30, 6, 18)
    assert times[0] == 0 and 18 in times and 29 < times[-1] < 30 and times == sorted(times)
