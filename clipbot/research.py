"""Persistent, evidence-linked original content drafts made by a small local team.

Only public feeds are fetched. Local AI has no tools, credentials or publishing access.
One background job runs at a time; each AI role shares the pipeline's GPU lock.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import html
import ipaddress
import json
import logging
import math
import re
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .aiplan import plan
from .clipability import BadModelOutput, _extract_json
from .config import AppPaths, ResearchCfg, Settings
from .copywriter import PLATFORMS, normalize_copy
from .util import ERR_SNIPPET

logger = logging.getLogger("clipbot.research")
ROLES = ("researcher", "director", "scriptwriter", "judge")
ACTIVE = {"queued", "directing", "writing", "judging"}
_TAGS = re.compile(r"<[^>]*>")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ResearchBusy(RuntimeError):
    """A background job already owns the desk."""


def public_url(value: str) -> str:
    """Validate an HTTPS link without following it; the fetcher also checks/pins DNS."""
    if not isinstance(value, str) or any(c.isspace() or ord(c) < ord(" ") for c in value):
        raise ValueError("Use a public HTTPS URL without spaces")
    try:
        p = urlsplit(value)
        host = (p.hostname or "").rstrip(".").lower()
        if (p.scheme != "https" or not host or p.username is not None or p.password is not None
                or p.port not in (None, httpx.URL("https://example.org").port)):
            raise ValueError("Only public HTTPS URLs on the standard port are supported")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal", ".test")):
                raise ValueError("Private-network and local hostnames are not allowed")
        else:
            if not address.is_global:
                raise ValueError("Private-network addresses are not allowed")
    except (ValueError, UnicodeError) as exc:
        raise ValueError(str(exc)) from exc
    return urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))


async def public_addresses(url: str, timeout: float) -> list[str]:
    """Reject mixed public/private DNS answers and return IPs to pin the request to."""
    parsed = httpx.URL(public_url(url))
    answers = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(parsed.host, parsed.port, type=socket.SOCK_STREAM),
        timeout=timeout)
    addresses = list(dict.fromkeys(row[-1][0] for row in answers))
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError("Feed DNS resolved to a private or non-public address")
    return addresses


async def fetch_feed(url: str, cfg: ResearchCfg, timeout: float) -> bytes:
    """Bounded decoded response; no redirects, ambient proxies or second DNS lookup.

    The connection targets the validated IP while Host and TLS SNI keep the original
    hostname. Certificate verification stays on, preventing DNS rebinding between checks.
    """
    canonical = public_url(url)
    addresses = await public_addresses(canonical, timeout)
    original = httpx.URL(canonical)
    target = original.copy_with(host=addresses[0])
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout) as client:
        async with client.stream("GET", target,
                                 headers={"Host": original.host, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
                                 extensions={"sni_hostname": original.host}) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > cfg.request_max_bytes:
                    raise ValueError("Feed exceeds the configured response size limit")
            return bytes(content)


def _plain(value: str, limit: int) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split())[:limit]


def _date(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def _source(title: str, url: str, summary: str, published: float, source: str,
            cfg: ResearchCfg, **extra) -> dict:
    url = public_url(url)
    title = _plain(title, cfg.source_text_chars)
    if not title:
        raise ValueError("Source has no title")
    return {"id": hashlib.sha256(url.encode()).hexdigest(), "title": title, "url": url,
            "summary": _plain(summary, cfg.source_text_chars), "published": published,
            "source": source, **extra}


def parse_feed(data: bytes, url: str, cfg: ResearchCfg, now: float | None = None) -> list[dict]:
    """Read RSS/Atom summaries, never execute markup or expand document entities."""
    if len(data) > cfg.request_max_bytes:
        raise ValueError("Feed exceeds the configured response size limit")
    # NUL rejection also excludes UTF-16/32 encodings which could disguise declarations.
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Feed document declarations and entities are not supported")
    root = ET.fromstring(data)
    now = time.time() if now is None else now
    since = now - cfg.source_max_age_days * 86400
    host = urlsplit(url).hostname or "feed"
    out: list[dict] = []
    entries = (e for e in root.iter() if e.tag.rsplit("}", 1)[-1] in ("item", "entry"))
    for index, entry in enumerate(entries):
        if index >= cfg.feed_entry_limit:
            break
        fields: dict[str, str] = {}
        link = ""
        for child in entry:
            tag = child.tag.rsplit("}", 1)[-1]
            fields.setdefault(tag, "".join(child.itertext()).strip())
            if tag == "link" and child.get("rel", "alternate") == "alternate":
                link = child.get("href", "") or fields[tag]
        published = _date(fields.get("published") or fields.get("pubDate") or fields.get("updated") or "")
        if published and published < since:
            continue
        try:
            out.append(_source(fields.get("title", ""), link,
                               fields.get("summary") or fields.get("description") or fields.get("encoded") or fields.get("content") or "",
                               published, host, cfg, feed_url=url))
        except ValueError as exc:
            logger.debug("research skipped invalid feed entry from %s: %s", host, exc)
    return out


class ResearchStudio:
    vram_gb: float | None = None

    def __init__(self, settings: Settings, http: httpx.AsyncClient, paths: AppPaths,
                 trends=None, gpu_lock: asyncio.Lock | None = None) -> None:
        self.settings, self.http, self.trends = settings, http, trends
        self._gpu_lock = gpu_lock or asyncio.Lock()
        self.cache_path = Path(paths.data) / "research.json"
        self.sources: list[dict] = []
        self.ideas: list[dict] = []
        self.errors: list[str] = []
        self.updated = 0.0
        self.status = "Add sources or refresh to begin"
        self.agents = [{"role": role, "status": "idle", "model": "", "detail": ""} for role in ROLES]
        self._work: asyncio.Task | None = None
        self._timer: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._closed = False
        self._last_attempt = 0.0
        self._active_id = ""
        self._load()

    @property
    def busy(self) -> bool:
        return self._work is not None and not self._work.done()

    def _load(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("sources", []), list) or not isinstance(data.get("ideas", []), list):
                raise ValueError("Invalid research data")
            cfg = self.settings.research
            for source in data.get("sources", [])[:cfg.source_limit]:
                if (not isinstance(source, dict)
                        or any(not isinstance(source.get(field), str) for field in ("id", "title", "url", "summary", "source"))
                        or not isinstance(source.get("published"), (int, float))
                        or not math.isfinite(source["published"])):
                    raise ValueError("Invalid saved source")
                public_url(source["url"])
                self.sources.append(source)
            self.ideas = data.get("ideas", [])[:cfg.idea_limit]
            recovered = False
            for idea in self.ideas:
                if (not isinstance(idea, dict) or not isinstance(idea.get("id"), str)
                        or not isinstance(idea.get("agents"), list)
                        or any(not isinstance(agent, dict) for agent in idea.get("agents", []))):
                    raise ValueError("Invalid saved draft")
                if idea.get("status") in ACTIVE:
                    recovered = True
                    idea["status"] = "interrupted"
                    idea["error"] = "App stopped during this draft. Start a new draft to retry."
                    for agent in idea.get("agents", []):
                        if agent.get("status") == "running":
                            agent.update(status="failed", detail=idea["error"])
            self.updated = float(data.get("updated", 0))
            if not math.isfinite(self.updated):
                raise ValueError("Invalid saved refresh time")
            errors = data.get("errors", [])
            if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
                raise ValueError("Invalid saved research errors")
            self.errors = errors
            self.status = data.get("status") or ("Saved research loaded" if self.sources or self.ideas else self.status)
            if not isinstance(self.status, str):
                raise ValueError("Invalid saved research status")
            if recovered:
                self.status = "A saved draft was interrupted; start a new draft to retry"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.sources, self.ideas = [], []
            self.updated = 0.0
            self.status = "Saved research could not be loaded"
            self.errors.append(f"Saved research could not be loaded: {exc}")
            logger.error("research load failed: %s", exc)

    def _save(self) -> bool:
        temporary = self.cache_path.with_suffix(".tmp")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"updated": self.updated, "sources": self.sources,
                                             "ideas": self.ideas, "errors": self.errors,
                                             "status": self.status}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.cache_path)
            return True
        except OSError as exc:
            error = f"Research could not be saved: {exc}"
            if error not in self.errors:
                self.errors.append(error)
            logger.error(error)
            return False

    def apply(self, settings: Settings) -> None:
        self.settings = settings
        self._wake.set()

    def start(self) -> None:
        self._closed = False
        if self._timer is None or self._timer.done():
            self._timer = asyncio.create_task(self._schedule(), name="research-schedule")

    async def stop(self) -> None:
        self._closed = True
        tasks = [task for task in (self._timer, self._work) if task and not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._timer = None
        # A task can be cancelled before its coroutine starts, so its finally block
        # never runs. Persist that queued draft as interrupted here as well.
        interrupted = False
        for idea in self.ideas:
            if idea.get("status") in ACTIVE:
                idea["status"] = "interrupted"
                idea["error"] = "Draft interrupted when the app stopped"
                for agent in idea["agents"]:
                    if agent["status"] in ("idle", "running"):
                        agent.update(status="skipped", detail=idea["error"])
                interrupted = True
        if interrupted:
            self.status = "Draft interrupted when the app stopped"
            self._save()
        self._active_id = ""

    async def _schedule(self) -> None:
        while not self._closed:
            cfg = self.settings.research
            interval = cfg.refresh_h * 3600
            if cfg.enabled and not self.busy and time.time() - self._last_attempt >= interval:
                self.request_refresh()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
                self._wake.clear()
            except TimeoutError:
                continue

    def snapshot(self) -> dict:
        return copy.deepcopy({"status": self.status, "busy": self.busy, "updated": self.updated,
                              "errors": self.errors, "sources": self.sources, "ideas": self.ideas,
                              "agents": self.agents, "settings": self.settings.research.model_dump(mode="json")})

    def _agent(self, role: str, status: str, detail: str, model: str = "", idea: dict | None = None) -> None:
        row = {"role": role, "status": status, "model": model, "detail": detail}
        self.agents[ROLES.index(role)] = row
        if idea is not None:
            idea["agents"][ROLES.index(role)] = dict(row)
        self.status = detail

    def request_refresh(self) -> dict:
        if self._closed:
            raise ResearchBusy("Research is shutting down")
        if self.busy:
            return {"ok": True, "status": self.status}
        self.errors = []
        self._agent("researcher", "running", "Collecting linked evidence")
        self._last_attempt = time.time()
        self._work = asyncio.create_task(self._refresh(), name="research-refresh")
        return {"ok": True, "status": self.status}

    def _trend_sources(self, cfg: ResearchCfg) -> list[dict]:
        out = []
        if not cfg.include_trends or self.trends is None:
            return out
        for item in getattr(self.trends, "items", [])[:cfg.source_limit]:
            vid = str(item.get("id", ""))
            if not _VIDEO_ID.fullmatch(vid):
                continue
            try:
                out.append(_source(str(item.get("title", "")), f"https://www.youtube.com/shorts/{vid}",
                                   "Trend lead only: title and view count; video contents have not been verified.",
                                   float(item.get("published", 0)), "YouTube · " + str(item.get("channel", "")),
                                   cfg, views=int(item.get("views", 0)), evidence_kind="title_only"))
            except (ValueError, TypeError) as exc:
                logger.debug("research skipped invalid YouTube lead: %s", exc)
        for item in getattr(self.trends, "clips", [])[:cfg.source_limit]:
            try:
                out.append(_source(str(item.get("title", "")), str(item.get("url", "")),
                                   "Trend lead only: viewer-created clip title; video contents have not been verified.",
                                   _date(str(item.get("created_at", ""))), "Twitch · " + str(item.get("broadcaster_name", "")),
                                   cfg, views=int(item.get("view_count", 0)), evidence_kind="title_only"))
            except (ValueError, TypeError) as exc:
                logger.debug("research skipped invalid Twitch lead: %s", exc)
        return out

    async def _refresh(self) -> None:
        cfg = self.settings.research.model_copy(deep=True)
        timeout = self.settings.discovery.http_timeout_s
        fresh = []
        try:
            for feed in dict.fromkeys(cfg.feeds):
                try:
                    data = await asyncio.wait_for(fetch_feed(feed, cfg, timeout), timeout=timeout)
                    entries = parse_feed(data, feed, cfg)
                    fresh.extend(entries)
                    if not entries:
                        self.errors.append(f"{feed}: no usable recent entries")
                except (httpx.HTTPError, OSError, ValueError, ET.ParseError, TimeoutError) as exc:
                    error = f"{feed}: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}"
                    self.errors.append(error)
                    logger.warning("research feed failed: %s", error)
            fresh.extend(self._trend_sources(cfg))
            if fresh:
                # Keep useful older evidence when an individual feed fails. Fresh entries win.
                merged = {source["id"]: source for source in self.sources}
                merged.update({source["id"]: source for source in fresh})
                self.sources = sorted(merged.values(), key=lambda source: source.get("published", 0), reverse=True)[:cfg.source_limit]
                self.updated = time.time()
                self._agent("researcher", "complete", f"{len(self.sources)} linked sources ready" + ("; some feeds need attention" if self.errors else ""))
            else:
                detail = "No new sources; saved evidence is unchanged" if self.sources else "Add a public RSS feed or refresh the trend scout to collect evidence"
                self._agent("researcher", "failed" if self.errors else "idle", detail)
        except asyncio.CancelledError:
            self._agent("researcher", "failed", "Research refresh interrupted")
            raise
        except Exception as exc:
            logger.exception("research refresh failed")
            self.errors.append(f"Research failed: {exc}")
            self._agent("researcher", "failed", f"Research failed: {exc}")
        finally:
            self._save()

    def _select_sources(self, topic: str, source_ids: list[str] | None, cfg: ResearchCfg) -> list[dict]:
        indexed = {s["id"]: s for s in self.sources}
        if source_ids is not None:
            if (not isinstance(source_ids, list) or not source_ids or
                    any(not isinstance(sid, str) or sid not in indexed for sid in source_ids)):
                raise ValueError("Choose valid source IDs from the research desk")
            ids = list(dict.fromkeys(source_ids))
            if len(ids) > cfg.evidence_limit:
                raise ValueError(f"Choose at most {cfg.evidence_limit} sources")
            return [copy.deepcopy(indexed[sid]) for sid in ids]
        words = set(re.findall(r"\w+", topic.casefold()))
        ranked = sorted(self.sources, key=lambda source: (
            len(words.intersection(re.findall(r"\w+", (source["title"] + " " + source["summary"]).casefold()))),
            source.get("published", 0)), reverse=True)
        if not ranked:
            raise ValueError("Refresh research and collect at least one source before drafting")
        return copy.deepcopy(ranked[:cfg.evidence_limit])

    def request_draft(self, topic: str, source_ids: list[str] | None = None) -> dict:
        cfg = self.settings.research
        if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > cfg.topic_max_chars:
            raise ValueError(f"Enter a topic of 1 to {cfg.topic_max_chars} characters")
        if self.busy or self._closed:
            raise ResearchBusy("The local team is busy; wait for the current job to finish")
        if len(self.ideas) >= cfg.idea_limit:
            raise ResearchBusy("The draft shelf is full. Delete an old draft before creating another")
        sources = self._select_sources(topic, source_ids, cfg)
        self.errors = []
        self.agents = [{"role": role, "status": "idle", "model": "", "detail": ""} for role in ROLES]
        idea = {"id": uuid.uuid4().hex, "topic": topic.strip(), "angle": "", "hook": "", "script": "",
                "posts": {}, "source_ids": [s["id"] for s in sources], "sources": sources,
                "judgement": {}, "status": "queued", "created_at": time.time(),
                "agents": copy.deepcopy(self.agents), "error": ""}
        self._agent("researcher", "complete", f"{len(sources)} evidence sources selected", idea=idea)
        self.ideas.insert(0, idea)
        if not self._save():
            self.ideas.remove(idea)
            raise OSError("The research draft could not be saved")
        self._active_id = idea["id"]
        self._work = asyncio.create_task(self._draft(idea, self.settings.model_copy(deep=True)), name="research-draft")
        return {"ok": True, "id": idea["id"], "status": idea["status"]}

    def delete_idea(self, idea_id: str) -> bool:
        if self.busy and self._active_id == idea_id:
            raise ResearchBusy("Wait for this draft to finish before deleting it")
        idea = next((row for row in self.ideas if row["id"] == idea_id), None)
        if idea is None:
            return False
        index = self.ideas.index(idea)
        self.ideas.remove(idea)
        if not self._save():
            self.ideas.insert(index, idea)
            raise OSError("The research draft could not be deleted from disk")
        return True

    def _model(self, role: str, settings: Settings) -> str:
        configured = {"director": settings.research.director_model,
                      "scriptwriter": settings.research.scriptwriter_model,
                      "judge": settings.research.judge_model}[role]
        current = plan(settings, self.vram_gb)
        return configured.strip() or (current.judge_model if current.one_model else settings.ai.model)

    async def _chat(self, role: str, payload: dict, settings: Settings, idea: dict) -> dict:
        cfg, ai = settings.research, settings.ai
        prompt = {"director": cfg.director_prompt, "scriptwriter": cfg.scriptwriter_prompt,
                  "judge": cfg.judge_prompt}[role]
        model = self._model(role, settings)
        self._agent(role, "running", f"{role.title()} waiting for the local model", model, idea)
        self._save()
        async with self._gpu_lock:
            self._agent(role, "running", f"{role.title()} working", model, idea)
            current = plan(settings, self.vram_gb)
            vision_model = current.judge_model if current.one_model else ai.vision_model
            body = {"model": model, "stream": False, "keep_alive": ai.keep_alive,
                    "messages": [{"role": "system", "content": prompt},
                                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                    "options": {"temperature": 0 if role == "judge" else cfg.temperature,
                                "num_ctx": ai.vision_num_ctx if model == vision_model else ai.num_ctx,
                                "num_predict": cfg.max_tokens}}
            if ai.vision_disable_thinking:
                body["think"] = False
            url = ai.ollama_url.rstrip("/") + "/api/chat"
            response = await self.http.post(url, json=body, timeout=ai.timeout_s)
            if response.status_code == 400 and "think" in body:
                body.pop("think")
                response = await self.http.post(url, json=body, timeout=ai.timeout_s)
            response.raise_for_status()
            raw = response.json().get("message", {}).get("content", "")
            if not isinstance(raw, str):
                raise BadModelOutput("Local model returned no text")
            result = _extract_json(raw)
            if not isinstance(result, dict):
                raise BadModelOutput("Local model must return a JSON object")
            return result

    @staticmethod
    def _citations(value, allowed: set[str]) -> list[str]:
        if not isinstance(value, list) or not value or any(not isinstance(sid, str) or sid not in allowed for sid in value):
            raise BadModelOutput("Model returned missing or unknown source IDs")
        return list(dict.fromkeys(value))

    @staticmethod
    def _text(value, name: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise BadModelOutput(f"Model returned an invalid {name}")
        return value.strip()

    @staticmethod
    def _normalize_posts(raw_posts, settings: Settings) -> dict:
        if not isinstance(raw_posts, dict):
            raise BadModelOutput("Scriptwriter returned no platform posts")
        raw_posts = copy.deepcopy(raw_posts)
        # A short post is sometimes returned as a string. Preserve its prose verbatim;
        # the same evidence audit still runs on every sentence after normalization.
        text_fields = {"youtube": "title", "tiktok": "caption", "instagram": "caption",
                       "facebook": "description", "discord": "message"}
        for platform, field in text_fields.items():
            if isinstance(raw_posts.get(platform), str):
                raw_posts[platform] = {field: raw_posts[platform]}
        posts = normalize_copy(raw_posts, settings)
        if any(platform not in posts for platform in PLATFORMS):
            raise BadModelOutput("Scriptwriter must supply copy for all five platforms")
        return {platform: posts[platform] for platform in PLATFORMS}

    def _claim_checks(self, claims, sources: list[dict], cfg: ResearchCfg) -> list[str]:
        indexed = {source["id"]: source for source in sources}
        issues = []
        if not isinstance(claims, list) or not claims:
            return ["The writer did not provide an evidence ledger for factual claims"]
        for claim in claims:
            if not isinstance(claim, dict):
                issues.append("A claim has no usable evidence record")
                continue
            try:
                text = self._text(claim.get("text"), "claim", cfg.script_max_chars)
                ids = self._citations(claim.get("source_ids"), set(indexed))
                quote = self._text(claim.get("evidence"), "evidence quote", cfg.source_text_chars)
            except BadModelOutput as exc:
                issues.append(str(exc))
                continue
            if all(indexed[sid].get("evidence_kind") == "title_only" for sid in ids):
                issues.append(f"A trend title alone cannot verify a factual claim: {text}")
            if not any(quote.casefold() in (indexed[sid]["title"] + " " + indexed[sid]["summary"]).casefold() for sid in ids):
                issues.append(f"Evidence quote was not found in the cited source: {text}")
        return list(dict.fromkeys(issues))

    @staticmethod
    def _review_units(idea: dict) -> list[dict]:
        """Have the judge audit actual prose, including sentences omitted from the ledger."""
        fields = {"hook": idea["hook"]}
        for platform, post in idea["posts"].items():
            for field, value in post.items():
                if isinstance(value, str) and value.strip():
                    fields[f"{platform}:{field}"] = value
        units = []
        for field, text in {"script": idea["script"], **fields}.items():
            sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
            for index, sentence in enumerate(sentences):
                uid = f"{field}:{index}" if field == "script" or len(sentences) > 1 else field
                units.append({"id": uid, "text": sentence})
        return units

    def _sentence_checks(self, checks, units: list[dict], sources: list[dict], cfg: ResearchCfg) -> list[str]:
        expected = {unit["id"] for unit in units}
        if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
            return ["The evidence judge did not audit every draft sentence"]
        ids = [check.get("id") for check in checks]
        if any(not isinstance(uid, str) for uid in ids) or set(ids) != expected or len(ids) != len(expected):
            return ["The evidence judge omitted or duplicated draft sentences"]
        issues = []
        for check in checks:
            if (check.get("kind") not in ("fact", "opinion") or not isinstance(check.get("supported"), bool)
                    or not isinstance(check.get("reason"), str) or not check["reason"].strip()):
                issues.append(f"The evidence judge returned an incomplete sentence check: {check['id']}")
            elif check["kind"] == "opinion":
                text = next(unit["text"] for unit in units if unit["id"] == check["id"])
                # A model calling a factual inference "opinion" must not bypass evidence checks.
                # Only configured nonfactual audience questions are automatically accepted.
                allowed_questions = {question.strip().casefold() for question in cfg.evidence_opinion_questions}
                if text.casefold() not in allowed_questions:
                    issues.append(f"{check['id']}: opinion classification needs human review; it cannot establish a factual benefit")
            elif not check["supported"]:
                issues.append(f"{check['id']}: {check['reason']}")
            elif check["kind"] == "fact":
                text = next(unit["text"] for unit in units if unit["id"] == check["id"])
                factual_issues = self._claim_checks([{"text": text,
                                                  "source_ids": check.get("source_ids"), "evidence": check.get("evidence")}], sources, cfg)
                issues.extend(f"{check['id']}: {issue}" for issue in factual_issues)
                if not factual_issues:
                    negations = set(cfg.evidence_negation_terms.casefold().split())
                    def has_negation(value):
                        tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", value.casefold().replace("’", "'"))
                        return bool(set(tokens) & negations)
                    if has_negation(text) != has_negation(check["evidence"]):
                        issues.append(f"{check['id']}: factual negation differs from its cited excerpt")
                    ignored = set(cfg.evidence_stop_words.casefold().split())
                    def words(value):
                        return {re.sub(r"(?:ing|ed|s)$", "", word) for word in re.findall(r"\w+", value.casefold()) if word not in ignored}
                    claim_words, evidence_words = words(text), words(check["evidence"])
                    if claim_words and len(claim_words & evidence_words) / len(claim_words) < cfg.evidence_min_overlap:
                        issues.append(f"{check['id']}: the factual wording goes beyond its cited excerpt; review the paraphrase")
                    number_words = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(),
                                            "0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20".split()))
                    def numbers(value):
                        tokens = re.findall(r"(?<!\w)\d+(?:\.\d+)?|[a-z]+", value.casefold())
                        return {float(number_words.get(token, token)) for token in tokens if token in number_words or token[0].isdigit()}
                    if not numbers(text).issubset(numbers(check["evidence"])):
                        issues.append(f"{check['id']}: a factual number is absent from its cited excerpt")
        return list(dict.fromkeys(issues))

    async def _draft(self, idea: dict, settings: Settings) -> None:
        cfg = settings.research
        role = "director"
        try:
            evidence = idea["sources"]
            allowed = {source["id"] for source in evidence}
            shared = {"topic": idea["topic"], "audience": cfg.niche, "target_seconds": cfg.target_seconds,
                      "evidence": evidence, "nonfactual_audience_questions": cfg.evidence_opinion_questions}
            idea["status"] = "directing"
            direction = await self._chat(role, shared, settings, idea)
            idea["angle"] = self._text(direction.get("angle"), "angle", cfg.script_max_chars)
            idea["hook"] = self._text(direction.get("hook"), "hook", cfg.source_text_chars)
            directed_ids = self._citations(direction.get("source_ids"), allowed)
            self._agent(role, "complete", "Original angle selected", self._model(role, settings), idea)
            role = "scriptwriter"
            idea["status"] = "writing"
            directed = [source for source in evidence if source["id"] in directed_ids]
            writer_payload = {**shared, "evidence": directed,
                              "direction": {"angle": idea["angle"], "hook": idea["hook"]},
                              "platform_rules": cfg.platform_rules}
            for attempt in range(settings.ai.retries + 1):
                written = await self._chat(role, writer_payload, settings, idea)
                try:
                    idea["hook"] = self._text(written.get("hook"), "hook", cfg.source_text_chars)
                    raw_script = written.get("script")
                    if isinstance(raw_script, list) and raw_script and all(isinstance(sentence, str) and sentence.strip() for sentence in raw_script):
                        raw_script = " ".join(sentence.strip() for sentence in raw_script)
                    idea["script"] = self._text(raw_script, "script", cfg.script_max_chars)
                    idea["source_ids"] = self._citations(written.get("source_ids"), set(directed_ids))
                    idea["sources"] = [source for source in directed if source["id"] in idea["source_ids"]]
                    idea["posts"] = self._normalize_posts(written.get("posts"), settings)
                except BadModelOutput as exc:
                    if attempt >= settings.ai.retries:
                        raise
                    writer_payload["repair"] = {"validation_error": str(exc), "previous_output": written}
                    logger.warning("research writer structure needs repair: %s", exc)
                else:
                    break
            claims = written.get("claims")
            idea["claims"] = copy.deepcopy(claims) if isinstance(claims, list) else []
            issues = self._claim_checks(claims, idea["sources"], cfg)
            self._agent(role, "complete", "Script and five platform drafts written", self._model(role, settings), idea)
            role = "judge"
            idea["status"] = "judging"
            units = self._review_units(idea)
            judge_payload = {**shared, "evidence": idea["sources"],
                             "draft": {key: idea[key] for key in ("angle", "hook", "script", "posts", "source_ids")},
                             "claims": claims, "review_units": units, "mechanical_evidence_checks": issues}
            for attempt in range(settings.ai.retries + 1):
                verdict = await self._chat(role, judge_payload, settings, idea)
                try:
                    if (not isinstance(verdict.get("approved"), bool) or not isinstance(verdict.get("grounded"), bool)
                            or not isinstance(verdict.get("unsupported_claims"), list)
                            or any(not isinstance(item, str) for item in verdict["unsupported_claims"])
                            or not isinstance(verdict.get("checks"), list) or not verdict["checks"]
                            or any(not isinstance(item, str) or not item.strip() for item in verdict["checks"])):
                        raise BadModelOutput("Evidence judge returned an incomplete verdict")
                    reason = self._text(verdict.get("reason"), "judge reason", cfg.script_max_chars)
                except BadModelOutput as exc:
                    if attempt >= settings.ai.retries:
                        raise
                    judge_payload["repair"] = {"validation_errors": [str(exc)], "previous_verdict": verdict}
                    continue
                sentence_issues = self._sentence_checks(verdict.get("sentence_checks"), units, idea["sources"], cfg)
                # Give an optimistic judge one bounded chance to complete/fix its evidence
                # audit. The final mechanical checks still decide readiness; rejected drafts
                # are kept for the user instead of being repeatedly rewritten until approved.
                if (sentence_issues and verdict["approved"] and verdict["grounded"]
                        and not verdict["unsupported_claims"] and attempt < settings.ai.retries):
                    judge_payload["repair"] = {"validation_errors": sentence_issues, "previous_verdict": verdict}
                    logger.warning("research judge evidence audit needs repair: %s", sentence_issues)
                    continue
                unsupported = list(dict.fromkeys([*issues, *sentence_issues, *verdict["unsupported_claims"]]))
                break
            grounded = verdict["grounded"] and not unsupported
            approved = verdict["approved"] and grounded
            idea["judgement"] = {"approved": approved, "grounded": grounded, "reason": reason,
                                 "unsupported_claims": unsupported, "checks": verdict["checks"]}
            idea["judgement"]["sentence_checks"] = verdict.get("sentence_checks", [])
            idea["status"] = "ready" if approved else "needs_review"
            self._agent(role, "complete", "Draft ready for your review" if approved else "Evidence or quality needs your review", self._model(role, settings), idea)
        except asyncio.CancelledError:
            idea["status"] = "interrupted"
            idea["error"] = "Draft interrupted when the app stopped"
            self._agent(role, "failed", idea["error"], self._model(role, settings), idea)
            raise
        except Exception as exc:
            logger.exception("research %s failed for %s", role, idea["id"])
            error = f"{role.title()} failed: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}"
            idea["status"], idea["error"] = "failed", error
            self.errors.append(error)
            self._agent(role, "failed", error, self._model(role, settings), idea)
        finally:
            for agent in idea["agents"]:
                if agent["status"] == "idle":
                    self._agent(agent["role"], "skipped", "An earlier stage did not complete", idea=idea)
            self.status = idea.get("error") or ("Draft ready for your review" if idea["status"] == "ready" else "Draft needs your review")
            self._active_id = ""
            self._save()
