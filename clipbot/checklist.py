"""First-run setup checklist: what's missing and which Settings field fixes it."""
from __future__ import annotations

import logging
import sys
import asyncio

import httpx

from .config import Settings, ffmpeg_exe, ffprobe_exe, is_frozen, streamlink_cmd
from .util import CmdTimeout, run_cmd

logger = logging.getLogger("clipbot.checklist")


def _item(id_: str, label: str, ok: bool, detail: str, field: str, required: bool) -> dict:
    return {"id": id_, "label": label, "ok": ok, "detail": detail, "field": field,
            "required": required}


async def _runs(args: list[str], timeout_s: float) -> tuple[bool, str]:
    try:
        res = await run_cmd(args, timeout_s)
    except (OSError, CmdTimeout) as exc:
        return False, str(exc)
    first = (res.out_text or res.err_text).strip().splitlines()
    return res.returncode == 0, first[0] if first else f"exit code {res.returncode}"


async def run_checklist(settings: Settings, http: httpx.AsyncClient, ctx=None) -> dict:
    s = settings
    timeout = s.capture.probe_timeout_s
    items: list[dict] = []

    ff = ffmpeg_exe(s)
    ok, detail = await _runs([ff, "-version"], timeout) if ff else (False, "not found on PATH")
    items.append(_item("ffmpeg", "ffmpeg installed", ok, detail if ok else
                       f"{detail} — install with: winget install Gyan.FFmpeg", "paths.ffmpeg", True))
    fp = ffprobe_exe(s)
    ok, detail = await _runs([fp, "-version"], timeout) if fp else (False, "not found on PATH")
    items.append(_item("ffprobe", "ffprobe installed", ok, detail, "paths.ffprobe", True))

    sl = streamlink_cmd(s)
    if is_frozen() and not s.paths.streamlink:
        ok, detail = True, "bundled with Ashvane"
    else:
        ok, detail = await _runs([*sl, "--version"], timeout)
    items.append(_item("streamlink", "streamlink available", ok, detail, "paths.streamlink", True))

    base = s.ai.ollama_url.rstrip("/")
    models = []
    try:
        r = await http.get(f"{base}/api/tags", timeout=s.discovery.http_timeout_s)
        r.raise_for_status()
        inventory = r.json()
        if not isinstance(inventory, dict) or not isinstance(inventory.get("models"), list):
            raise ValueError("Invalid local model inventory")
        models = [m["name"] for m in inventory["models"] if isinstance(m, dict) and isinstance(m.get("name"), str)]
        items.append(_item("ollama", "Ollama reachable", True, f"{len(models)} model(s) at {base}",
                           "ai.ollama_url", True))
        has = s.ai.model in models
        items.append(_item("model", f"Model {s.ai.model} installed", has,
                           "ready" if has else f"run: ollama pull {s.ai.model}", "ai.model", True))
        if s.ai.vision_enabled:
            vis = s.ai.vision_model in models
            items.append(_item("vision", f"Vision model {s.ai.vision_model} installed", vis,
                               "ready — the judge can see the video" if vis else
                               f"optional: run  ollama pull {s.ai.vision_model}  so the judge can "
                               "see the video (clips are judged on audio + chat until then)",
                               "ai.vision_model", False))
    except (httpx.HTTPError, ValueError) as exc:
        items.append(_item("ollama", "Ollama reachable", False,
                           f"cannot reach {base} ({type(exc).__name__}) — start Ollama",
                           "ai.ollama_url", True))

    tw = bool(s.twitch.client_id and s.twitch.client_secret) and s.twitch.enabled
    kk = bool(s.kick.client_id and s.kick.client_secret) and s.kick.enabled
    items.append(_item("twitch", "Twitch developer app keys", tw,
                       "set" if tw else "needed to discover Twitch streams", "twitch.client_id",
                       not kk))
    items.append(_item("kick", "Kick developer app keys", kk,
                       "set" if kk else "needed to discover Kick streams", "kick.client_id",
                       not tw))

    posting = {"youtube": ("accounts.youtube_client_id", s.accounts.youtube_client_id),
               "tiktok": ("accounts.tiktok_client_key", s.accounts.tiktok_client_key),
               "instagram": ("accounts.instagram_token", s.accounts.instagram_token),
               "facebook": ("accounts.facebook_page_token", s.accounts.facebook_page_token),
               "discord": ("accounts.discord_webhook", s.accounts.discord_webhook)}
    any_post = any(v for _, v in posting.values())
    items.append(_item("posting", "At least one posting account", any_post,
                       "set" if any_post else "optional: clips are still saved to the clips folder",
                       "accounts.discord_webhook", False))

    groups, shared = await business_checks(s, items, models, ctx)
    # Retain every legacy item ID for existing desktop/phone consumers. A stopped
    # business contributes diagnostics, never a required failure.
    for item in items:
        item["business_id"] = "clips"
        item["required"] = item["required"] and s.businesses.surge_enabled and item["id"] != "model"
        if item["id"] in {"ffmpeg", "ffprobe"}:
            item["business_id"] = "shared"
            item["required"] = s.businesses.surge_enabled or s.businesses.hollow_enabled
    known = {item["id"] for item in items}
    items.extend(item for group in groups for item in group["items"] if item["id"] not in known)
    missing_required = [i for i in items if i["required"] and not i["ok"]]
    return {"ok": not missing_required, "items": items, "businesses": groups, "shared": shared,
            "python": sys.version.split()[0], "frozen": is_frozen()}


async def business_checks(s, legacy, models, ctx=None):
    """Read evidence only: never start a business, load a model or render audio."""
    from .aiplan import plan, vram_gb
    pipeline = getattr(ctx, "pipeline", None)
    current = plan(s, vram_gb(getattr(pipeline, "gpu", None)))
    creative_model = s.creative.model.strip() or plan(s, None).judge_model or s.ai.model
    lookup = {item["id"]: item for item in legacy}
    model_names = set(name for name in models if isinstance(name, str))
    lock = getattr(getattr(pipeline, "stories", None), "_gpu_lock", None)
    gpu_busy = bool(lock and lock.locked())
    shared = {"gpu_busy": gpu_busy,
              "message": "Shared local AI resource is in use. Enabled businesses may wait for it." if gpu_busy else
                         "Installed-model checks do not measure simultaneous GPU capacity or guarantee generation quality."}
    groups = []

    def row(business, name, enabled, checks, runtime=None, detail=""):
        runtime = runtime or {}
        creative = getattr(ctx, "creative_tools", None)
        busy = bool(runtime.get("busy")) or bool(creative and creative.tasks.get(business))
        blocked = any(item["required"] and not item["ok"] for item in checks)
        state = "stopped" if not enabled else "blocked" if blocked else "busy" if busy or gpu_busy else "ready"
        if enabled and runtime.get("running") is False and not busy and not blocked:
            state = "unverified"
        for item in checks:
            item["business_id"] = business
            item["required"] = bool(enabled and item["required"])
        message = ("Stopping; current work is draining. Saved work remains available." if busy else
                   "Stopped by choice. Saved work remains available; use Run when needed.") if not enabled else (
                       runtime.get("message") if state in {"busy", "unverified"} else detail)
        groups.append({"id": business, "name": name, "enabled": enabled, "busy": busy or (enabled and gpu_busy),
                       "ready": state == "ready", "status": state, "message": message or detail,
                       "items": checks})

    def model_item(id_, label, model, field):
        found = model in model_names or model + ":latest" in model_names
        return _item(id_, label, found, f"Installed: {model}" if found else
                     f"Configured model is not in the local Ollama inventory: {model}", field, True)

    clips = [dict(item) for item in legacy if item["id"] not in {"model", "vision"}]
    clips.append(model_item("clips_model", "Active Surge judge model", current.judge_model, "ai.judge_profile"))
    if s.ai.vision_enabled and not current.one_model:
        vision = model_item("clips_vision", "Surge vision model", s.ai.vision_model, "ai.vision_model")
        vision["required"] = False
        clips.append(vision)
    runtime = pipeline.business_state("clips") if pipeline and hasattr(pipeline, "business_state") else {}
    if getattr(pipeline, "blocked", ""):
        clips.append(_item("clips_runtime", "Capture and processing runtime", False, str(pipeline.blocked), "", True))
    transcriber = getattr(pipeline, "transcriber", None)
    if transcriber:
        verified = bool(getattr(transcriber, "_verified", False))
        clips.append(_item("clips_transcriber", "Speech transcription", verified,
                           str(transcriber.status) + (" · first inference verified" if verified else
                           " · inference has not been verified in this session"), "whisper.model", False))
    row("clips", "Surge", s.businesses.surge_enabled, clips, runtime,
        "Capture dependencies and the active judge inventory are checked. First-use transcription is reported separately.")

    story_studio = getattr(pipeline, "stories", None)
    caps = story_studio._capabilities() if story_studio and hasattr(story_studio, "_capabilities") else {}
    story_model = story_studio._model(s) if story_studio and hasattr(story_studio, "_model") else s.stories.model.strip() or current.judge_model
    story_checks = [model_item("stories_model", "Story team model", story_model, "stories.model"),
                    model_item("stories_creative_model", "Story idea model", creative_model, "creative.model")]
    for id_ in ("ffmpeg", "ffprobe"):
        source = lookup[id_]
        story_checks.append(_item("stories_" + id_, source["label"], source["ok"], source["detail"], source["field"], True))
    narrator = bool(caps.get("narrator_available")) and s.stories.narrator_backend != "openai_compatible"
    story_checks.append(_item("stories_narrator", "Narration capability", narrator,
                             caps.get("narrator_label", "Narrator has not been inspected") +
                             (" · local speech connection is checked on render" if s.stories.narrator_backend == "openai_compatible" else
                              " · " + "; ".join(caps.get("reasons", []))), "stories.narrator_backend", True))
    story_checks.append(_item("stories_visuals", "Visual provider", bool(caps.get("visual_provider", {}).get("available")),
                             caps.get("visual_provider", {}).get("label", "Visual provider has not been inspected") +
                             (" · configured external provider is checked on render" if s.stories.image_provider_url else ""), "stories.image_provider_url", True))
    runtime = pipeline.business_state("stories") if pipeline and hasattr(pipeline, "business_state") else {}
    row("stories", "Hollow", s.businesses.hollow_enabled, story_checks, runtime,
        "Models, local narrator inventory and render dependencies checked. A configured speech server needs a real render to verify it.")

    studio_state, reaper = {}, {}
    service = getattr(ctx, "music_bridge", None)
    music_error = "Local studio has not been inspected. Start Resonance or check the managed installation."
    if service:
        results = await asyncio.gather(*(asyncio.wait_for(service.call("GET", route), timeout=s.music.request_timeout_s)
                                         for route in ("/api/status", "/api/reaper/status")), return_exceptions=True)
        if isinstance(results[0], dict):
            studio_state = results[0]
        else:
            music_error = str(getattr(results[0], "detail", results[0]))
        if isinstance(results[1], dict):
            reaper = results[1]
    health = reaper.get("native_health", {})
    native_verified = bool(reaper.get("ready")) and health.get("status") == "verified"
    audio_verified = any(revision.get("status") == "completed" and revision.get("audio_url") and
                         isinstance(revision.get("qc"), dict) and revision["qc"].get("duration_seconds", 0) > 0
                         for project in reaper.get("projects", []) for revision in project.get("revisions", []))
    music_checks = [_item("music_engine", "Local YuE2 generation engine", bool(studio_state.get("ready")),
                         str(studio_state.get("message") or music_error), "music.root_dir", True),
                    _item("music_reaper_installed", "REAPER executable", bool(reaper.get("installed")),
                          "Executable found; native health is checked separately." if reaper.get("installed") else
                          "REAPER executable was not detected by the local studio.", "music.root_dir", True),
                    _item("music_reaper_native", "Native REAPER session editing", native_verified,
                          str(health.get("message") or "Native editing/rendering is unverified. Finding an executable does not verify audio production."), "", True),
                    _item("music_reaper_audio", "Native audio export evidence", native_verified and audio_verified,
                          "A completed native revision includes measured playable audio." if native_verified and audio_verified else
                          "No completed native audio revision with measured duration was reported. A session edit alone does not verify export.", "", True),
                    model_item("music_producer_model", "AI music producer model", s.music.producer_model.strip() or plan(s, None).judge_model or s.ai.model, "music.producer_model"),
                    model_item("music_creative_model", "Lyric and musical direction model", creative_model, "creative.model")]
    producer = getattr(service, "producer", None)
    if getattr(producer, "error", ""):
        music_checks.append(_item("music_history", "Production history", False, producer.error, "", True))
    row("music", "Resonance", s.businesses.resonance_enabled, music_checks,
        {"busy": bool(studio_state.get("busy")) or bool(reaper.get("busy")) or bool(producer and producer.busy)},
        "Native health reports the last real edit. Listening and musical approval remain specific to each revision.")

    social = getattr(ctx, "social_studio", None)
    social_state = social.state() if social else {}
    social_checks = [model_item("social_model", "Client draft writer model", s.social.model.strip() or s.ai.model, "social.model"),
                     model_item("social_creative_model", "Idea and reference learning model", creative_model, "creative.model"),
                     _item("social_publishing", "Publishing workflow", True,
                           "Manual publishing only. Saved public profile links are not connected publishing accounts.", "", False)]
    if social_state.get("message") and getattr(social, "error", ""):
        social_checks.append(_item("social_history", "Saved client workspace", False, social_state["message"], "", True))
    row("social", "Social Studio", s.businesses.social_enabled, social_checks, social_state,
        "Models are present for client drafts and reference learning. Media analysis reports its own evidence limits; publication is manual.")
    active = [group["name"] for group in groups if group["busy"]]
    if active:
        shared["resource_busy"] = True
        shared["message"] = "Work is active in " + ", ".join(active) + ". Dependency checks do not verify spare GPU capacity for simultaneous jobs."
        for group in groups:
            if group["enabled"] and group["status"] == "ready":
                group.update(status="busy", ready=False,
                             message="Other local work is active; resources may be shared. Installed dependencies passed their checks.")
    return groups, shared
