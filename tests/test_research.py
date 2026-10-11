"""Research uses bounded real evidence, survives failures and never publishes drafts."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from clipbot import research as R
from clipbot.auth import ProfileStore
from clipbot.config import Settings
from clipbot.dashboard.server import create_app


FEED = "https://news.example.org/feed"
ARTICLE = "https://news.example.org/articles/captions"
RSS = b'''<rss><channel><item><title>Creator captions update</title>
<link>https://news.example.org/articles/captions</link>
<description>&lt;p&gt;Captions now support three new languages.&lt;/p&gt;</description>
<pubDate>Sat, 03 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'''


def settings():
    s = Settings()
    s.research.enabled = False
    s.research.feeds = []
    s.ai.judge_profile = "custom"
    s.ai.single_model = False
    s.ai.model = "local-model"
    s.ai.retries = 0
    return s


def evidence(s):
    return R.parse_feed(RSS, FEED, s.research, now=1791028800)


def studio(tmp_path, http, s=None, lock=None):
    s = s or settings()
    instance = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path), gpu_lock=lock)
    instance.sources = evidence(s)
    return instance


def replies(s):
    sid = evidence(s)[0]["id"]
    output = [
        {"angle": "Make videos easier to follow", "hook": "A useful caption update", "source_ids": [sid]},
        {"hook": "A useful caption update", "script": "The update says captions now support three new languages.",
         "source_ids": [sid], "claims": [{"text": "Three new languages are supported", "source_ids": [sid],
                                          "evidence": "Captions now support three new languages."}],
         "posts": {"youtube": {"title": "A useful caption update", "description": "Three new languages are supported", "tags": ["captions"]},
                   "tiktok": {"caption": "A useful caption update", "hashtags": ["captions"]},
                   "instagram": {"caption": "A useful caption update", "hashtags": ["captions"]},
                   "facebook": {"title": "A useful caption update", "description": "Three new languages are supported"},
                   "discord": {"message": "A useful caption update"}}},
        {"approved": True, "grounded": True, "reason": "All details are supported by the feed summary.",
         "unsupported_claims": [], "checks": ["The language count matches the source excerpt."]},
    ]
    units = R.ResearchStudio._review_units(output[1])
    output[-1]["sentence_checks"] = [{"id": unit["id"], "kind": "fact", "supported": True,
                                     "source_ids": [sid], "evidence": "Creator captions update Captions now support three new languages.",
                                     "reason": "The source supports the language update."} for unit in units]
    return output


def transport_for(outputs, calls):
    def handler(request):
        calls.append(json.loads(request.content))
        output = outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return httpx.Response(200, json={"message": {"content": json.dumps(output)}})
    return httpx.MockTransport(handler)


def test_feed_parsing_and_plain_text():
    rows = evidence(settings())
    assert len(rows) == 1
    assert rows[0]["url"] == ARTICLE
    assert rows[0]["summary"] == "Captions now support three new languages."
    assert rows[0]["published"] > 0
    assert rows[0]["source"] == "news.example.org"
    assert len(rows[0]["id"]) == 64
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>News</title>
    <link href="https://news.example.org/post"/><summary>Useful update</summary>
    <published>2026-10-03T12:00:00Z</published></entry></feed>'''
    assert R.parse_feed(atom, FEED, settings().research, now=1791028800)[0]["summary"] == "Useful update"


@pytest.mark.parametrize("url", ["http://example.org/feed", "https://127.0.0.1/feed", "https://[::1]/feed",
                                      "https://192.168.1.2/", "https://169.254.169.254/", "https://localhost/",
                                      "https://service.local/", "https://example.org:8000/", "https://user:secret@example.org/",
                                      "https://2130706433/", "https://example.org/ bad"])
def test_public_sources_reject_private_and_unsafe_urls(url):
    with pytest.raises(ValueError):
        R.public_url(url)


@pytest.mark.parametrize("data", [b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>', b'<!ENTITY x "boom"><rss/>',
                                       '<rss/>'.encode("utf-16")])
def test_feed_rejects_entity_and_alternate_encoding_attacks(data):
    with pytest.raises(ValueError):
        R.parse_feed(data, FEED, settings().research)


def test_feed_and_entry_limits():
    cfg = settings().research
    cfg.request_max_bytes = 4096
    with pytest.raises(ValueError, match="size limit"):
        R.parse_feed(b" " * 4097, FEED, cfg)
    cfg.feed_entry_limit = 1
    doubled = RSS.replace(b"</channel>", RSS.split(b"<item>")[1].split(b"</channel>")[0].join([b"<item>", b""]) + b"</channel>")
    assert len(R.parse_feed(doubled, FEED, cfg, now=1791028800)) == 1


def test_dns_rebinding_answers_rejected(monkeypatch):
    async def run():
        async def resolve(*args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        with pytest.raises(ValueError, match="private"):
            await R.public_addresses(FEED, 1)
    asyncio.run(run())


def test_feed_request_pins_public_ip_and_keeps_tls_hostname(monkeypatch):
    async def run():
        real_client = httpx.AsyncClient
        seen = []
        async def resolve(url, timeout):
            return ["93.184.216.34"]
        def handle(request):
            seen.append(request)
            return httpx.Response(200, content=RSS)
        def client(**kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        monkeypatch.setattr(R, "public_addresses", resolve)
        monkeypatch.setattr(R.httpx, "AsyncClient", client)
        result = await R.fetch_feed(FEED, settings().research, 1)
        assert result == RSS
        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["host"] == "news.example.org"
        assert seen[0].extensions["sni_hostname"] == "news.example.org"
    asyncio.run(run())


def test_feed_redirects_are_not_followed(monkeypatch):
    async def run():
        real_client = httpx.AsyncClient
        requests = []
        async def resolve(url, timeout):
            return ["93.184.216.34"]
        def handle(request):
            requests.append(request)
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})
        monkeypatch.setattr(R, "public_addresses", resolve)
        monkeypatch.setattr(R.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
        with pytest.raises(httpx.HTTPStatusError):
            await R.fetch_feed(FEED, settings().research, 1)
        assert len(requests) == 1
    asyncio.run(run())


def test_draft_roles_gpu_lock_and_persistence(tmp_path):
    async def run():
        s, calls = settings(), []
        lock = asyncio.Lock()
        await lock.acquire()
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as http:
            engine = studio(tmp_path, http, s, lock)
            result = engine.request_draft("caption update")
            assert result["ok"] and engine.busy
            await asyncio.sleep(0)
            assert calls == []  # no local GPU work while clip processing owns the lock
            with pytest.raises(R.ResearchBusy):
                engine.request_draft("another topic")
            assert engine.request_refresh()["ok"]  # reuse, never overlap
            with pytest.raises(R.ResearchBusy):
                engine.delete_idea(result["id"])
            lock.release()
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "ready"
            assert set(idea["posts"]) == set(R.PLATFORMS)
            assert all(agent["status"] == "complete" for agent in idea["agents"])
            assert [call["model"] for call in calls] == ["local-model"] * 3
            assert calls[-1]["options"]["temperature"] == 0
            loaded = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path))
            assert loaded.ideas[0]["id"] == result["id"]
            assert loaded.ideas[0]["sources"] == evidence(s)
            assert loaded.ideas[0]["claims"] == replies(s)[1]["claims"]
            assert loaded.delete_idea(result["id"])
            assert not R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path)).ideas
            await engine.stop()
    asyncio.run(run())


def test_separate_role_models_are_used(tmp_path):
    async def run():
        s, calls = settings(), []
        s.research.director_model = "director-local"
        s.research.scriptwriter_model = "writer-local"
        s.research.judge_model = "judge-local"
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert [c["model"] for c in calls] == ["director-local", "writer-local", "judge-local"]
    asyncio.run(run())


@pytest.mark.parametrize("vram,expected", [(16, "vision-local"), (4, "light-local"), (48, "local-model")])
def test_auto_role_models_follow_gpu_profile_and_reuse_context(tmp_path, vram, expected):
    async def run():
        s, calls = settings(), []
        s.ai.judge_profile = "auto"
        s.ai.vision_model = "vision-local"
        s.ai.light_model = "light-local"
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.vram_gb = vram
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
            assert [call["model"] for call in calls] == [expected] * 3
            expected_context = s.ai.num_ctx if expected == "local-model" else s.ai.vision_num_ctx
            assert all(call["options"]["num_ctx"] == expected_context for call in calls)
    asyncio.run(run())


@pytest.mark.parametrize("fault", ["no_claims", "title_only", "ungrounded", "missing_sentence", "rejected_sentence", "invented_sentence_evidence", "unrelated_real_quote", "changed_number"])
def test_evidence_gate_blocks_optimistic_judge(tmp_path, fault):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        if fault == "no_claims":
            output[1].pop("claims")
        elif fault == "ungrounded":
            output[-1]["grounded"] = False
        elif fault == "missing_sentence":
            output[-1]["sentence_checks"].pop()
        elif fault == "rejected_sentence":
            output[-1]["sentence_checks"][0]["supported"] = False
            output[-1]["sentence_checks"][0]["reason"] = "The hook implies an unverified outcome"
        elif fault == "invented_sentence_evidence":
            output[-1]["sentence_checks"][0]["evidence"] = "A fabricated quote"
        elif fault == "unrelated_real_quote":
            output[1]["script"] = "The update made enemies easier to spot and removed all shadows."
        elif fault == "changed_number":
            output[1]["script"] = "The update says captions now support six new languages."
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            if fault == "title_only":
                engine.sources[0]["evidence_kind"] = "title_only"
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "needs_review"
            assert not engine.ideas[0]["judgement"]["approved"]
            assert not engine.ideas[0]["judgement"]["grounded"]
    asyncio.run(run())


def test_draft_save_and_delete_failures_preserve_consistent_shelf(tmp_path, monkeypatch):
    async def run():
        s, calls = settings(), []
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as http:
            engine = studio(tmp_path, http, s)
            original_save = engine._save
            monkeypatch.setattr(engine, "_save", lambda: False)
            with pytest.raises(OSError, match="saved"):
                engine.request_draft("captions")
            assert not engine.ideas and not engine.busy and not calls
            monkeypatch.setattr(engine, "_save", original_save)
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            monkeypatch.setattr(engine, "_save", lambda: False)
            with pytest.raises(OSError, match="deleted"):
                engine.delete_idea(idea["id"])
            assert engine.ideas == [idea]
            assert R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path)).ideas[0]["id"] == idea["id"]
    asyncio.run(run())


def test_bad_citation_fails_before_writing(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[0]["source_ids"] = ["invented-source"]
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "failed" and "source IDs" in idea["error"]
            assert len(calls) == 1
            assert idea["agents"][1]["status"] == "failed"
            assert idea["agents"][-1]["status"] == "skipped"
    asyncio.run(run())


def test_unmatched_evidence_cannot_be_approved(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["claims"][0]["evidence"] = "Invented report says creators earned millions"
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "needs_review"
            assert not idea["judgement"]["approved"]
            assert "not found" in idea["judgement"]["unsupported_claims"][0]
    asyncio.run(run())


def test_judge_rejection_and_failure_keep_script(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[-1]["unsupported_claims"] = ["The hook adds an unsupported detail"]
        output += replies(s)[:-1] + [httpx.ConnectError("Ollama unavailable")]
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "needs_review"
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "failed" and idea["script"]
            assert "Judge failed" in idea["error"]
            assert idea["agents"][-1]["status"] == "failed"
            assert not idea["judgement"]
    asyncio.run(run())


def test_refresh_failure_preserves_evidence_and_timestamp(tmp_path, monkeypatch):
    async def run():
        s = settings()
        s.research.feeds = [FEED]
        async def broken(*args):
            raise httpx.ConnectError("temporarily offline")
        monkeypatch.setattr(R, "fetch_feed", broken)
        async with httpx.AsyncClient() as http:
            engine = studio(tmp_path, http, s)
            previous = list(engine.sources)
            engine.updated = 1234
            engine.request_refresh()
            task = engine._work
            engine.request_refresh()
            assert engine._work is task
            await task
            assert engine.sources == previous and engine.updated == 1234
            assert "offline" in engine.errors[0]
            assert engine.agents[0]["status"] == "failed"
            restored = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path))
            assert restored.sources == previous and restored.updated == 1234
            assert restored.errors == engine.errors and restored.status == engine.status
    asyncio.run(run())


def test_refresh_and_scheduler_persist_real_sources(tmp_path, monkeypatch):
    async def run():
        s = settings()
        s.research.enabled = True
        s.research.feeds = [FEED]
        # Undated sources remain usable, with published=0 so the UI does not imply a date.
        feed = RSS.replace(b"<pubDate>Sat, 03 Oct 2026 12:00:00 GMT</pubDate>", b"")
        calls = []
        async def fetched(*args):
            calls.append(args[0])
            return feed
        monkeypatch.setattr(R, "fetch_feed", fetched)
        async with httpx.AsyncClient() as http:
            engine = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path))
            engine.start()
            await asyncio.sleep(0)
            await engine._work
            assert calls == [FEED] and engine.updated > 0
            assert engine.sources[0]["url"] == ARTICLE
            restored = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path))
            assert restored.sources == engine.sources
            await engine.stop()
            assert not engine.busy and engine._timer is None
    asyncio.run(run())


def test_stop_cancels_draft_and_marks_interrupted(tmp_path):
    async def run():
        s, calls = settings(), []
        lock = asyncio.Lock()
        await lock.acquire()
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as http:
            engine = studio(tmp_path, http, s, lock)
            engine.request_draft("captions")
            await asyncio.sleep(0)
            await engine.stop()
            lock.release()
            assert not engine.busy and calls == []
            assert engine.ideas[0]["status"] == "interrupted"
            restored = R.ResearchStudio(s, http, SimpleNamespace(data=tmp_path))
            assert restored.ideas[0]["status"] == "interrupted"
    asyncio.run(run())


def test_recovers_a_draft_interrupted_before_coroutine_started(tmp_path):
    async def run():
        async with httpx.AsyncClient() as http:
            engine = studio(tmp_path, http)
            engine.request_draft("captions")
            await engine.stop()
            assert engine.ideas[0]["status"] == "interrupted"
            restored = R.ResearchStudio(settings(), http, SimpleNamespace(data=tmp_path))
            assert restored.ideas[0]["status"] == "interrupted"
    asyncio.run(run())


@pytest.mark.parametrize("data", [
    {"sources": [{"url": ARTICLE}]},
    {"ideas": [{"id": "draft", "agents": [None]}]},
    {"updated": float("nan")},
    {"errors": [None]},
])
def test_corrupt_saved_shapes_report_an_error_without_crashing(tmp_path, data):
    async def run():
        (tmp_path / "research.json").write_text(json.dumps(data), encoding="utf-8")
        async with httpx.AsyncClient() as http:
            engine = R.ResearchStudio(settings(), http, SimpleNamespace(data=tmp_path))
            assert not engine.sources and not engine.ideas
            assert "could not be loaded" in engine.errors[0]
    asyncio.run(run())


def test_research_api_guards_validation_and_delete(tmp_path):
    async def run():
        s, calls = settings(), []
        async with httpx.AsyncClient(transport=transport_for(replies(s), calls)) as model_http:
            engine = studio(tmp_path, model_http, s)
            ctx = SimpleNamespace(settings=s, paths=SimpleNamespace(data=tmp_path), pipeline=SimpleNamespace(
                research=engine, business_enabled=lambda business: True, _business_transition=set(),
                _business_requests={"clips": {}, "stories": {}}))
            app = create_app(ctx)
            base = f"http://127.0.0.1:{s.dashboard.port}"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
                assert (await client.get("/api/research")).status_code == 401
                auth = ProfileStore()
                profile = auth.create("Research tester", "safe-password-123", s.app.min_password_len)
                token = auth.create_session(profile["id"], s.app.session_hours)
                client.headers["Authorization"] = f"Bearer {token}"
                assert (await client.get("/api/research")).json()["sources"] == engine.sources
                assert (await client.post("/api/research/refresh")).status_code == 403
                client.headers["X-ClipBot"] = "1"
                for payload in (["not an object"], {"topic": ""}, {"topic": "captions", "source_ids": ["unknown"]},
                                {"topic": "captions", "publish": True}, {"topic": 123}, {"topic": "captions", "source_ids": "wrong-type"}):
                    response = await client.post("/api/research/draft", json=payload)
                    assert response.status_code == 422, response.text
                assert (await client.post("/api/research/draft", content=b"not-json")).status_code == 422
                response = await client.post("/api/research/draft", json={"topic": "caption update"})
                assert response.status_code == 200
                await engine._work
                idea_id = response.json()["id"]
                assert (await client.delete(f"/api/research/ideas/{idea_id}")).json() == {"ok": True}
                assert (await client.delete(f"/api/research/ideas/{idea_id}")).status_code == 404
                assert (await client.get("/api/research", headers={"host": "attacker.example"})).status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("label", ["opinion", "fact"])
def test_lighting_inference_cannot_be_ready_even_with_optimistic_judge(tmp_path, label):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        sid = evidence(s)[0]["id"]
        source = evidence(s)[0]
        source.update(title="Lighting update", summary="Improved lighting in the Warehouse map.")
        output[1]["script"] = "Fewer shadows, better contrast, easier enemy visibility."
        output[1]["claims"] = [{"text": "Improved lighting in the Warehouse map.",
                                 "source_ids": [sid], "evidence": source["summary"]}]
        for check in output[-1]["sentence_checks"]:
            check["evidence"] = source["title"] + " " + source["summary"]
            if check["id"] == "script:0":
                check["kind"] = label
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.sources = [source]
            engine.request_draft("lighting")
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "needs_review"
            assert any("script:0" in issue for issue in idea["judgement"]["unsupported_claims"])
    asyncio.run(run())


@pytest.mark.parametrize("supported", [True, False])
def test_allowed_nonfactual_question_can_pass_without_citation(tmp_path, supported):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["posts"]["discord"]["message"] = s.research.evidence_opinion_questions[0]
        check = next(row for row in output[-1]["sentence_checks"] if row["id"] == "discord:message")
        check.update(kind="opinion", supported=supported, source_ids=[], evidence="", reason="This asks for the viewer's preference.")
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
    asyncio.run(run())


@pytest.mark.parametrize("text", ["Captions now support six new languages.", "This earns millions.",
                                 "Which change matters most to you? It removes shadows."])
def test_opinion_label_does_not_clear_factual_claims(tmp_path, text):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["posts"]["discord"]["message"] = text
        output[-1]["sentence_checks"] = [row for row in output[-1]["sentence_checks"] if row["id"] != "discord:message"]
        for unit in R.ResearchStudio._review_units(output[1]):
            if unit["id"].startswith("discord:message"):
                output[-1]["sentence_checks"].append({"id": unit["id"], "kind": "opinion", "supported": True,
                                                      "source_ids": [], "evidence": "", "reason": "The judge calls this opinion."})
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "needs_review"
            assert any("opinion classification" in issue for issue in engine.ideas[0]["judgement"]["unsupported_claims"])
    asyncio.run(run())


def test_platform_paragraph_and_hook_are_audited_per_sentence():
    idea = {"hook": "Captions changed. They support three languages.", "script": "Read the update.",
            "posts": {"discord": {"message": "Captions changed. What do you think?"}}}
    units = R.ResearchStudio._review_units(idea)
    assert {unit["id"] for unit in units} == {"script:0", "hook:0", "hook:1", "discord:message:0", "discord:message:1"}
    assert next(unit["text"] for unit in units if unit["id"] == "discord:message:1") == "What do you think?"


def test_multisentence_copy_uses_each_sentences_supporting_excerpt(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        sid = evidence(s)[0]["id"]
        output[1]["posts"]["discord"]["message"] = "Creator captions update. Captions now support three new languages."
        output[-1]["sentence_checks"] = [row for row in output[-1]["sentence_checks"] if row["id"] != "discord:message"]
        for index, quote in enumerate(["Creator captions update", "Captions now support three new languages."]):
            output[-1]["sentence_checks"].append({"id": f"discord:message:{index}", "kind": "fact", "supported": True,
                                                  "source_ids": [sid], "evidence": quote, "reason": "This sentence is supported."})
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
    asyncio.run(run())


@pytest.mark.parametrize("script", ["Captions no longer support three new languages.",
                                    "Captions don't support three new languages.",
                                    "Captions don’t support three new languages."])
def test_negation_cannot_reverse_source_claim(tmp_path, script):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["script"] = script
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "needs_review"
            assert any("negation differs" in issue for issue in engine.ideas[0]["judgement"]["unsupported_claims"])
    asyncio.run(run())



def test_plain_text_platform_post_is_preserved_and_audited(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        prose = output[1]["posts"]["discord"]["message"]
        output[1]["posts"]["discord"] = prose
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
            assert engine.ideas[0]["posts"]["discord"] == {"message": prose}
            review = json.loads(calls[-1]["messages"][-1]["content"])["review_units"]
            assert {"id": "discord:message", "text": prose} in review
    asyncio.run(run())


def test_bounded_writer_repair_uses_actionable_feedback(tmp_path):
    async def run():
        s, calls = settings(), []
        s.ai.retries = 1
        output = replies(s)
        malformed = json.loads(json.dumps(output[1]))
        malformed["posts"].pop("discord")
        outputs = [output[0], malformed, output[1], output[2]]
        async with httpx.AsyncClient(transport=transport_for(outputs, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready" and len(calls) == 4
            repair = json.loads(calls[2]["messages"][-1]["content"])
            assert "all five platforms" in repair["repair"]["validation_error"]
            assert repair["repair"]["previous_output"] == malformed
            assert repair["platform_rules"] == s.research.platform_rules
            assert "quote from the clip" not in repair["platform_rules"]
    asyncio.run(run())


def test_writer_repair_limit_keeps_failed_script_and_skips_judge(tmp_path):
    async def run():
        s, calls = settings(), []
        s.ai.retries = 1
        output = replies(s)
        malformed = output[1]
        malformed["posts"].pop("discord")
        outputs = [output[0]] + [malformed] * (s.ai.retries + 1)
        async with httpx.AsyncClient(transport=transport_for(outputs, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            assert idea["status"] == "failed" and idea["script"]
            assert len(calls) == s.ai.retries + 2
            assert idea["agents"][-1]["status"] == "skipped"
    asyncio.run(run())



def test_sentence_array_script_keeps_text_and_full_audit(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        original = output[1]["script"]
        output[1]["script"] = [original, s.research.evidence_opinion_questions[0]]
        output[-1]["sentence_checks"].append({"id": "script:1", "kind": "opinion", "supported": True,
                                              "source_ids": [], "evidence": "", "reason": "This asks for viewer preference."})
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
            assert engine.ideas[0]["script"] == original + " " + s.research.evidence_opinion_questions[0]
    asyncio.run(run())


def test_game_identifier_is_not_a_factual_count(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["script"] = "CS2 captions now support three new languages."
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready"
    asyncio.run(run())


def test_numeric_unit_suffix_still_needs_source_support(tmp_path):
    async def run():
        s, calls = settings(), []
        output = replies(s)
        output[1]["script"] = "Captions now support three new languages at 6px."
        async with httpx.AsyncClient(transport=transport_for(output, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "needs_review"
            assert any("factual number" in issue for issue in engine.ideas[0]["judgement"]["unsupported_claims"])
    asyncio.run(run())



@pytest.mark.parametrize("fault", ["citation", "verdict"])
def test_judge_repairs_incomplete_evidence_once(tmp_path, fault):
    async def run():
        s, calls = settings(), []
        s.ai.retries = 1
        output = replies(s)
        incomplete = json.loads(json.dumps(output[-1]))
        if fault == "citation":
            incomplete["sentence_checks"][0]["source_ids"] = []
        else:
            incomplete.pop("grounded")
        outputs = output[:-1] + [incomplete, output[-1]]
        async with httpx.AsyncClient(transport=transport_for(outputs, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            assert engine.ideas[0]["status"] == "ready" and len(calls) == 4
            feedback = json.loads(calls[-1]["messages"][-1]["content"])["repair"]
            assert feedback["validation_errors"]
            assert feedback["previous_verdict"] == incomplete
    asyncio.run(run())


def test_judge_repair_does_not_weaken_unsupported_inference_gate(tmp_path):
    async def run():
        s, calls = settings(), []
        s.ai.retries = 1
        output = replies(s)
        output[1]["script"] = "Captions remove every shadow and make enemies easier to spot."
        outputs = output + [output[-1]]
        async with httpx.AsyncClient(transport=transport_for(outputs, calls)) as http:
            engine = studio(tmp_path, http, s)
            engine.request_draft("captions")
            await engine._work
            idea = engine.ideas[0]
            assert len(calls) == 4 and idea["status"] == "needs_review"
            assert not idea["judgement"]["approved"]
            assert idea["script"] == output[1]["script"]
    asyncio.run(run())
