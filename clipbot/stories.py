"""Original horror stories, local editorial roles and durable video-production jobs.

The director and jury are private. Only a validated public story is handed to the
renderer. The models have no tools and cannot choose filesystem paths or fetch URLs.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import shutil
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx

from .aiplan import plan
from .clipability import BadModelOutput, _extract_json
from .config import AppPaths, Settings
from .copywriter import YOUTUBE_DESC_MAX, YOUTUBE_TAGS_TOTAL_MAX, YOUTUBE_TITLE_MAX
from .public_copy import check_public_text
from .util import ERR_SNIPPET

logger = logging.getLogger("clipbot.stories")
GENRES = (
    ("paranormal", "Paranormal"), ("psychological", "Psychological"),
    ("creature", "Creature"), ("urban_legend", "Urban legend"), ("analog", "Analog horror"),
    ("cosmic", "Cosmic horror"), ("folklore", "Folklore"), ("sci_fi", "Science fiction"),
    ("survival", "Survival"),
)
FORMATS = {"still", "animated"}
VISUAL_CHOICES = {"setting": {"corridor", "forest", "street", "room", "station"},
                  "subject": {"figure", "creature", "none"},
                  "action": {"approach", "reveal", "vanish", "follow", "wait"}}
ROLES = ("director", "writer", "judge")
ACTIVE = {"queued", "directing", "writing", "judging", "narrating", "rendering"}
PUBLISH_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook", "discord"}
PUBLISH_STATES = {"pending", "uploading", "published", "failed", "uncertain"}
_ID = re.compile(r"^[a-f0-9]{32}$")
FICTION_LABEL = "Original fiction."
PUBLIC_FIELDS = ("id", "title", "topic", "genre", "format", "duration_s", "voice",
                 "script", "scenes", "public_copy")


class StoryBusy(RuntimeError):
    """One local production job is already running."""


def _clean_text(value, name: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit:
        raise ValueError(f"{name} must be {'at most' if empty else '1 to'} {limit} characters")
    if "\x00" in value:
        raise ValueError(f"{name} contains invalid text")
    return value.strip()


def _words(value: str) -> list[str]:
    return re.findall(r"\b[\w]+(?:['’][\w]+)*\b", value)


def _joined(value: str) -> str:
    return " ".join(value.split())


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid story ID")
    return value


class StoryStudio:
    """One background job, with a shared GPU lock and an injected local renderer."""

    vram_gb: float | None = None

    def __init__(self, settings: Settings, http: httpx.AsyncClient, paths: AppPaths,
                 gpu_lock: asyncio.Lock | None = None) -> None:
        self.settings, self.http = settings, http
        self._gpu_lock = gpu_lock or asyncio.Lock()
        self.cache_path = Path(paths.data) / "stories.json"
        self.project_root = Path(paths.data) / "stories"
        self.renderer = None
        self.capabilities: dict | None = None
        self.projects: list[dict] = []
        self.errors: list[str] = []
        self._task: asyncio.Task | None = None
        self._active_id = ""
        self._closed = False
        self._load()

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _directory(self, project_id: str) -> Path:
        root = self.project_root.resolve()
        candidate = (root / _identifier(project_id)).resolve()
        if candidate.parent != root or candidate.name != project_id:
            raise ValueError("Story directory must stay inside the story library")
        return candidate

    def _inside(self, project_id: str, value: str, *, exists: bool = True) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("Missing story asset path")
        root = self._directory(project_id)
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root) or candidate == root:
            raise ValueError("Story assets must stay inside this project's folder")
        if exists and not candidate.is_file():
            raise ValueError("Story asset is missing")
        return candidate

    def _load(self) -> None:
        if not self.cache_path.exists():
            return
        changed = False
        try:
            saved = json.loads(self.cache_path.read_text(encoding="utf-8"))
            rows = saved.get("projects") if isinstance(saved, dict) else None
            if not isinstance(rows, list):
                raise ValueError("Invalid story library")
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid saved story")
                pid = _identifier(row.get("id"))
                if pid in seen:
                    raise ValueError("Duplicate saved story ID")
                seen.add(pid)
                self._directory(pid)
                row.setdefault("revision", 0)
                row.setdefault("publishing", {})
                for publication in row["publishing"].values():
                    if publication.get("status") == "uploading":
                        publication.update(status="uncertain", error="The app stopped during upload. Check the destination account before retrying.")
                        changed = True
                for publication in row.get("publication_history", []):
                    if publication.get("status") == "uploading":
                        publication.update(status="uncertain", error="The app stopped during upload. Check the destination account before retrying.")
                        changed = True
                if row.get("status") in ACTIVE:
                    row.update(status="interrupted", error="The app stopped during this job. Your saved draft is available to edit or retry.")
                    for agent in row.get("agents", []):
                        if agent.get("status") == "running":
                            agent.update(status="failed", detail="Job interrupted")
                    changed = True
                if row.get("output"):
                    try:
                        self._validate_output(row, row["output"])
                    except (ValueError, TypeError, OSError):
                        self._invalidate_output(row)
                        if row.get("status") == "ready":
                            row["status"] = "draft"
                        row["error"] = "The saved video is missing or no longer belongs to this story. Render it again."
                        changed = True
                self.projects.append(row)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.projects = []
            self.errors.append(f"Story library could not be read: {exc}")
            logger.error("story library could not be read: %s", exc)
            return
        self.projects.sort(key=lambda row: row.get("created_at", 0), reverse=True)
        if changed:
            try:
                self._save()
            except OSError as exc:
                self.errors.append(f"Interrupted stories could not be saved: {exc}")
                logger.error("could not save recovered story state: %s", exc)

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "projects": self.projects}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.cache_path)

    def _persist_job(self, project: dict) -> None:
        try:
            self._save()
        except OSError as exc:
            message = f"Story progress could not be saved: {exc}"
            self.errors.append(message)
            project["error"] = message
            logger.error(message)

    def apply(self, settings: Settings) -> None:
        self.settings = settings

    def start(self) -> None:
        self._closed = False

    async def stop(self) -> None:
        self._closed = True
        if self.busy:
            self.cancel(self._active_id)
            await asyncio.gather(self._task, return_exceptions=True)
        # Cancellation before the coroutine's first turn cannot execute its finally.
        # Persist the interrupted draft explicitly so it survives a later relaunch.
        for project in self.projects:
            if project.get("status") in ACTIVE:
                project.update(status="interrupted", error="Hollow stopped. Your saved story is still available.")
                for agent in project.get("agents", []):
                    if agent.get("status") in {"idle", "running"}:
                        agent.update(status="skipped", detail=project["error"])
                self._persist_job(project)
        self._active_id = ""

    def _capabilities(self) -> dict:
        if self.capabilities is not None:
            return copy.deepcopy(self.capabilities)
        raw = getattr(self.renderer, "capabilities", {}) if self.renderer is not None else {}
        if callable(raw):
            raw = raw()
        return copy.deepcopy(raw) if isinstance(raw, dict) else {}

    def state(self) -> dict:
        cfg = self.settings.stories
        job = None
        if self.busy:
            active = self._find(self._active_id)
            job = {"project_id": active["id"], "stage": active["status"], "progress": active["progress"]}
        safe_settings = {key: getattr(cfg, key) for key in (
            "enabled", "model", "default_duration_s", "default_genre", "default_format", "voice",
            "narrator_backend", "speech_rate", "narration_words_per_min", "max_projects", "max_scenes", "max_script_words",
            "min_duration_s", "max_duration_s", "min_script_words", "max_topic_chars", "max_title_chars",
            "auto_render", "auto_publish", "publish_destinations", "publish_privacy",
        )}
        return {"projects": copy.deepcopy(self.projects), "busy": self.busy, "job": job,
                "account_profile_id": self.account_profile_id() if hasattr(self, "account_profile_id") else "default",
                "compilation": {"max_stories": cfg.compilation_max_stories,
                                "opening_s": cfg.compilation_opening_s, "between_s": cfg.compilation_between_s},
                "genres": [{"id": key, "label": label} for key, label in GENRES],
                "capabilities": self._capabilities(), "settings": safe_settings, "errors": list(self.errors)}

    def _find(self, project_id: str) -> dict:
        _identifier(project_id)
        project = next((row for row in self.projects if row["id"] == project_id), None)
        if project is None:
            raise KeyError("Story not found")
        return project

    def get(self, project_id: str) -> dict | None:
        try:
            return copy.deepcopy(self._find(project_id))
        except KeyError:
            return None

    def _available(self) -> None:
        if not self.settings.businesses.hollow_enabled:
            raise StoryBusy("Hollow is stopped. Start it from the business switcher")
        if self._closed:
            raise StoryBusy("Story production is shutting down")
        if not self.settings.stories.enabled:
            raise StoryBusy("Enable Story Studio in Settings to start a production job")
        if self.busy:
            raise StoryBusy("The local story team is busy. Wait for the current job or cancel it")

    def _launch(self, project: dict, coroutine, name: str) -> None:
        self._active_id = project["id"]
        self._task = asyncio.create_task(coroutine, name=name)
        self._task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        if task is not self._task:
            return
        project = next((row for row in self.projects if row["id"] == self._active_id), None)
        if project is not None and project.get("status") in ACTIVE:
            if task.cancelled():
                project.update(status="interrupted", error="Job cancelled. Your saved story is still available.")
            elif task.exception() is not None:
                logger.error("story task failed unexpectedly", exc_info=task.exception())
                project.update(status="failed", error=str(task.exception())[:ERR_SNIPPET])
            self._persist_job(project)
        self._active_id = ""

    def create(self, topic: str, genre: str, format: str, duration_s: int, voice: str = "") -> dict:
        self._available()
        cfg = self.settings.stories
        if len(self.projects) >= cfg.max_projects:
            raise StoryBusy("The story library is full. Delete a finished project before adding another")
        topic = _clean_text(topic, "Story idea", cfg.max_topic_chars)
        if not isinstance(genre, str) or genre not in dict(GENRES):
            raise ValueError("Choose a supported horror genre")
        if not isinstance(format, str) or format not in FORMATS:
            raise ValueError("Choose still or animated format")
        if isinstance(duration_s, bool) or not isinstance(duration_s, int) or not cfg.min_duration_s <= duration_s <= cfg.max_duration_s:
            raise ValueError(f"Story duration must be {cfg.min_duration_s} to {cfg.max_duration_s} seconds")
        voice = _clean_text(voice, "Voice", cfg.max_topic_chars, empty=True) or cfg.voice
        now = time.time()
        project = {"id": uuid.uuid4().hex, "title": topic[:min(cfg.max_title_chars, YOUTUBE_TITLE_MAX)],
                   "account_profile_id": self.account_profile_id() if hasattr(self, "account_profile_id") else "default",
                   "topic": topic, "genre": genre, "format": format, "duration_s": duration_s,
                   "voice": voice, "created_at": now, "updated_at": now, "status": "queued", "progress": 0,
                   "script": "", "scenes": [], "public_copy": {}, "review": {}, "error": "",
                   "output": {}, "video_url": "", "audio_url": "", "manual_edit": False,
                   "revision": 0, "publishing": {}, "publication_history": [],
                   "agents": [{"role": role, "status": "idle", "model": "", "detail": ""} for role in ROLES]}
        self.projects.insert(0, project)
        try:
            self._directory(project["id"]).mkdir(parents=True, exist_ok=True)
            self._save()
        except OSError:
            self.projects.remove(project)
            raise
        self._launch(project, self._generate(project, self.settings.model_copy(deep=True)), "story-generate")
        return copy.deepcopy(project)

    def create_compilation(self, title: str, project_ids: list[str], landscape: bool = True,
                           account_profile_id: str = "") -> dict:
        """A new edition of finished, approved stories; original projects stay intact."""
        self._available()
        cfg = self.settings.stories
        if len(self.projects) >= cfg.max_projects:
            raise StoryBusy("The story library is full. Delete a finished project before adding another")
        profile = self.account_profile_id() if hasattr(self, "account_profile_id") else "default"
        if account_profile_id and account_profile_id != profile:
            raise StoryBusy("The Hollow account profile changed. Reload before creating this compilation")
        title = " ".join(_clean_text(title, "Compilation title", min(cfg.max_title_chars, YOUTUBE_TITLE_MAX)).split())
        if type(landscape) is not bool:
            raise ValueError("Choose landscape or portrait for the compilation")
        if (not isinstance(project_ids, list) or not 2 <= len(project_ids) <= cfg.compilation_max_stories
                or any(not isinstance(pid, str) for pid in project_ids) or len(set(project_ids)) != len(project_ids)):
            raise ValueError(f"Choose 2 to {cfg.compilation_max_stories} different finished stories in order")
        sources = []
        for pid in project_ids:
            source = self._find(pid)
            identity = self.content_fingerprint(pid)
            if (source.get("kind") == "compilation" or source.get("status") != "ready"
                    or not source.get("output", {}).get("video_path")
                    or source.get("review", {}).get("passed") is not True
                    or source["review"].get("content_hash") != identity):
                raise ValueError("Each selection must be a finished individual story with a current passing review")
            if (source.get("account_profile_id") or "default") != profile:
                raise ValueError("Choose stories belonging to the current Hollow account profile")
            check_public_text(SimpleNamespace(verdict=source["review"], visual="", words=[], transcript=source["script"]),
                              {"chapter_title": source["title"]}, self.settings)
            sources.append({"project_id": pid, "title": source["title"], "content_hash": identity})
        public_copy = self._validate_copy({"youtube": {"title": title,
            "description": f"{FICTION_LABEL}\n\n{len(sources)} original horror stories, together in one collection.",
            "tags": ["horror stories", "scary story compilation"], "hashtags": ["HorrorStories"]}}, title, self.settings)
        check_public_text(SimpleNamespace(verdict={}, visual="", words=[], transcript=""),
                          {"title": title, "public_copy": public_copy}, self.settings)
        now = time.time()
        project = {"id": uuid.uuid4().hex, "kind": "compilation", "title": title,
            "account_profile_id": profile, "topic": f"{len(sources)} original horror stories",
            "genre": "mixed", "format": "compilation", "duration_s": 0, "voice": "Original story audio",
            "created_at": now, "updated_at": now, "status": "rendering", "progress": 0,
            "script": "", "scenes": [], "public_copy": public_copy, "review": {}, "error": "",
            "output": {}, "video_url": "", "audio_url": "", "manual_edit": False, "revision": 0,
            "publishing": {}, "publication_history": [], "agents": [],
            "compilation": {"sources": sources, "landscape": landscape,
                            "base_description": public_copy["youtube"]["description"],
                            "opening_s": cfg.compilation_opening_s, "between_s": cfg.compilation_between_s}}
        self.projects.insert(0, project)
        try:
            self._directory(project["id"]).mkdir(parents=True, exist_ok=True)
            self._save()
        except OSError:
            self.projects.remove(project)
            raise
        self._launch(project, self._render_compilation(project, self.settings.model_copy(deep=True)), "story-compilation")
        return copy.deepcopy(project)

    async def _render_compilation(self, project: dict, settings: Settings) -> None:
        from .story_compilation import StoryCompiler
        try:
            compilation = project["compilation"]
            inputs = []
            snapshots = compilation.get("snapshots", [])
            for index, source in enumerate(compilation["sources"]):
                if snapshots:
                    path = self._inside(project["id"], snapshots[index]["file"])
                else:
                    original = self._find(source["project_id"])
                    if (self.content_fingerprint(original["id"]) != source["content_hash"]
                            or original.get("status") != "ready"):
                        raise ValueError("A source story changed before assembly. Create the compilation again")
                    path = self._inside(original["id"], original["output"]["video_path"])
                inputs.append({"project_id": source["project_id"], "title": source["title"], "path": path})
            directory = self._directory(project["id"]) / ("edition-" + uuid.uuid4().hex)
            result = await StoryCompiler(settings).compile(inputs, directory, title=project["title"],
                opening_s=compilation["opening_s"], between_s=compilation["between_s"], landscape=compilation["landscape"])
            output = self._validate_output(project, result)
            chapters = copy.deepcopy(result["chapters"])
            snapshots = copy.deepcopy(result["source_snapshots"])
            for source in snapshots:
                source["file"] = str(self._inside(project["id"], source["file"]))
            compilation.update(chapters=chapters, snapshots=snapshots)
            def timestamp(seconds):
                seconds = int(seconds)
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
            chapter_text = "\n".join(f"{timestamp(row['start_s'])} {row['title']}" for row in chapters)
            description = compilation["base_description"].rstrip() + "\n\n" + chapter_text
            compilation["chapter_text"] = chapter_text
            project["public_copy"]["youtube"]["description"] = description
            project["public_copy"] = self._validate_copy(project["public_copy"], project["title"], settings)
            check_public_text(SimpleNamespace(verdict={}, visual="", words=[], transcript=""),
                              {"title": project["title"], "public_copy": project["public_copy"], "chapters": chapters}, settings)
            project.update(output=output, duration_s=output["duration_s"], status="ready", progress=1,
                           video_url=f"/api/stories/projects/{project['id']}/video",
                           audio_url=f"/api/stories/projects/{project['id']}/audio")
            project["review"] = {"passed": True, "scope": "source_approvals_and_assembly",
                "reason": "Each source had a current passing story review. Compilation audio/video and chapter timings passed technical checks. This is not a new creative or visual jury review.",
                "issues": [], "content_hash": self.content_fingerprint(project["id"])}
        except asyncio.CancelledError:
            self._invalidate_output(project)
            project.update(status="interrupted", error="Compilation cancelled. Your original stories are intact.")
            raise
        except Exception as exc:
            logger.exception("story compilation failed for %s", project["id"])
            self._invalidate_output(project)
            project.update(status="failed", error=f"Compilation failed: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}")
        finally:
            project["updated_at"] = time.time()
            self._persist_job(project)

    def _validate_copy(self, value, title: str, settings: Settings) -> dict:
        if not isinstance(value, dict) or not isinstance(value.get("youtube"), dict):
            raise ValueError("YouTube public copy is required")
        raw = value["youtube"]
        public_title = _clean_text(raw.get("title", title), "Public title", min(settings.stories.max_title_chars, YOUTUBE_TITLE_MAX))
        description = _clean_text(raw.get("description", ""), "Public description", YOUTUBE_DESC_MAX, empty=True)
        if not description.casefold().startswith(FICTION_LABEL.casefold()):
            description = f"{FICTION_LABEL}\n\n{description}".strip()
        if len(description) > YOUTUBE_DESC_MAX:
            raise ValueError("Public description has no room for the original-fiction label")
        tags, hashtags = [], []
        for key, output in (("tags", tags), ("hashtags", hashtags)):
            items = raw.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"Public {key} must be a list of words")
            for item in items:
                clean = item.strip().lstrip("#")
                if clean and clean not in output:
                    output.append(clean)
            if sum(len(item) for item in output) > YOUTUBE_TAGS_TOTAL_MAX:
                raise ValueError(f"Public {key} are too long")
        return {"youtube": {"title": public_title, "description": description, "tags": tags, "hashtags": hashtags}}

    def _normalize_story(self, project: dict, supplied: dict, settings: Settings, *, allow_assets: bool) -> dict:
        cfg = settings.stories
        title = _clean_text(supplied.get("title"), "Story title", min(cfg.max_title_chars, YOUTUBE_TITLE_MAX))
        script = supplied.get("script")
        if not isinstance(script, str) or "\x00" in script:
            raise ValueError("Narration must be plain story text")
        script = script.strip()
        from .story_voice import validate_spoken_text
        validate_spoken_text(script)
        word_count = len(_words(script))
        if not cfg.min_script_words <= word_count <= cfg.max_script_words:
            raise ValueError(f"The story must contain {cfg.min_script_words} to {cfg.max_script_words} spoken words")
        scenes = supplied.get("scenes")
        if not isinstance(scenes, list) or not 1 <= len(scenes) <= cfg.max_scenes:
            raise ValueError(f"Provide 1 to {cfg.max_scenes} scenes")
        normalized, seen = [], set()
        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError("Every scene must contain narration and a visual prompt")
            narration = scene.get("narration")
            if not isinstance(narration, str) or not narration.strip():
                raise ValueError("Every scene needs spoken narration")
            prompt = _clean_text(scene.get("visual_prompt"), "Scene visual prompt", cfg.max_visual_prompt_chars)
            scene_id = scene.get("id") if allow_assets else None
            if scene_id is not None:
                _identifier(scene_id)
            scene_id = scene_id or uuid.uuid4().hex
            if scene_id in seen:
                raise ValueError("Scene IDs must be unique")
            seen.add(scene_id)
            row = {"id": scene_id, "narration": narration.strip(), "visual_prompt": prompt}
            if scene.get("visual") is not None:
                visual = scene["visual"]
                if not isinstance(visual, dict) or set(visual) != set(VISUAL_CHOICES):
                    raise ValueError("Scene visual must describe setting, subject and action")
                if any(not isinstance(value, str) or value not in VISUAL_CHOICES[key] for key, value in visual.items()):
                    raise ValueError("Choose supported scene settings, subjects and actions")
                row["visual"] = dict(visual)
            if allow_assets and scene.get("asset_path"):
                row["asset_path"] = str(self._inside(project["id"], scene["asset_path"]))
            normalized.append(row)
        if _joined(" ".join(scene["narration"] for scene in normalized)) != _joined(script):
            raise ValueError("Scene narration must match the full script in order, without omissions or repeats")
        public_copy = self._validate_copy(supplied.get("public_copy"), title, settings)
        # Source separation is primary: no review object enters this check or renderer.
        # Reuse the clip system's configurable diagnostic-language protection as well.
        check_public_text(SimpleNamespace(verdict={}, visual="", words=[], transcript=""),
                          {"title": title, "script": script, "public_copy": public_copy}, settings)
        return {"title": title, "script": script, "scenes": normalized, "public_copy": public_copy,
                "word_count": word_count, "estimated_duration_s": word_count / cfg.narration_words_per_min * 60}

    @staticmethod
    def _invalidate_output(project: dict) -> None:
        project.update(output={}, video_url="", audio_url="")

    def update(self, project_id: str, script: str | None = None, scenes: list | None = None,
               title: str | None = None, public_copy: dict | None = None) -> dict:
        project = self._find(project_id)
        self._not_uploading(project)
        if self.busy and self._active_id == project_id:
            raise StoryBusy("Wait for this story's job to finish or cancel it before editing")
        if all(value is None for value in (script, scenes, title, public_copy)):
            raise ValueError("Provide a script, scenes, title or public copy to update")
        draft = copy.deepcopy(project)
        if project.get("kind") == "compilation":
            if (script is not None and script != project["script"]) or (scenes is not None and scenes != project["scenes"]):
                raise ValueError("Edit individual stories before making a compilation. Compilation narration stays with its source videos")
            if title is not None:
                draft["title"] = _clean_text(title, "Compilation title", min(self.settings.stories.max_title_chars, YOUTUBE_TITLE_MAX))
            draft["public_copy"] = self._validate_copy(public_copy or draft["public_copy"], draft["title"], self.settings)
            description = draft["public_copy"]["youtube"]["description"]
            previous_chapters = draft["compilation"].get("chapter_text", "")
            if previous_chapters and description.rstrip().endswith(previous_chapters):
                description = description.rstrip()[:-len(previous_chapters)].rstrip()
            draft["compilation"]["base_description"] = description
            check_public_text(SimpleNamespace(verdict={}, visual="", words=[], transcript=""),
                              {"title": draft["title"], "public_copy": draft["public_copy"]}, self.settings)
            self._invalidate_output(draft)
            draft.update(status="draft", progress=0, updated_at=time.time(), manual_edit=True, error="",
                         revision=project.get("revision", 0) + 1,
                         review={"passed": None, "reason": "Compilation changed. Assemble it again before publishing.", "issues": []})
            index = self.projects.index(project)
            self.projects[index] = draft
            try:
                self._save()
            except OSError:
                self.projects[index] = project
                raise
            return copy.deepcopy(draft)
        if title is not None:
            draft["title"] = title
        if script is not None:
            draft["script"] = script
            if scenes is None and _joined(script) != _joined(project["script"]):
                # A script-only edit cannot leave stale narration split across old scenes.
                # Keep one existing visual as a starting point, and show that scene for edits.
                first = project["scenes"][0] if project["scenes"] else {}
                draft["scenes"] = [{"narration": script,
                                    "visual_prompt": first.get("visual_prompt") or project["topic"]}]
        if scenes is not None:
            draft["scenes"] = scenes
            if script is None and isinstance(scenes, list) and all(isinstance(scene, dict) and isinstance(scene.get("narration"), str) for scene in scenes):
                draft["script"] = "\n\n".join(scene["narration"].strip() for scene in scenes)
        if public_copy is not None:
            draft["public_copy"] = public_copy
        elif not draft.get("public_copy"):
            draft["public_copy"] = {"youtube": {"title": draft["title"], "description": "", "tags": [], "hashtags": []}}
        draft.update(self._normalize_story(draft, draft, self.settings, allow_assets=True))
        self._invalidate_output(draft)
        draft.update(status="draft", progress=1, updated_at=time.time(), manual_edit=True, error="",
                     revision=project.get("revision", 0) + 1,
                     review={"passed": None, "reason": "Edited by you. The previous automatic review no longer applies; review the story before rendering.", "issues": []})
        index = self.projects.index(project)
        self.projects[index] = draft
        try:
            self._save()
        except OSError:
            self.projects[index] = project
            raise
        return copy.deepcopy(draft)

    @staticmethod
    def _not_uploading(project: dict) -> None:
        if any(row.get("status") == "uploading" for row in project.get("publishing", {}).values()):
            raise StoryBusy("A story upload is in progress. Wait for it to finish before changing or deleting this project")

    def content_fingerprint(self, project_id: str) -> str:
        """Stable content identity for a publisher snapshot, independent of job state."""
        project = self._find(project_id)
        public = {key: project[key] for key in PUBLIC_FIELDS}
        return hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def record_publish(self, project_id: str, platform: str, status: str, external_id: str = "",
                       url: str = "", error: str = "", content_hash: str = "", account_id: str = "") -> dict:
        """Durable publication ledger; the caller owns the actual platform request.

        Persist ``uploading`` before contacting a platform. An upload left in that
        state on restart is uncertain and must be reconciled rather than retried.
        """
        project = self._find(project_id)
        if not isinstance(platform, str) or not isinstance(status, str) or platform not in PUBLISH_PLATFORMS or status not in PUBLISH_STATES:
            raise ValueError("Unsupported publication destination or status")
        current_hash = self.content_fingerprint(project_id)
        previous = project.get("publishing", {}).get(platform, {})
        snapshot_hash = content_hash or (previous.get("content_hash") if status not in {"pending", "uploading"} else current_hash)
        if not isinstance(snapshot_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_hash):
            raise ValueError("Invalid publication content fingerprint")
        same_content = previous.get("content_hash") == snapshot_hash
        if status in {"pending", "uploading"}:
            if self.busy and self._active_id == project_id:
                raise StoryBusy("Wait for this story's production job to finish before publishing")
            if (project.get("status") != "ready" or project.get("review", {}).get("passed") is not True
                    or project.get("review", {}).get("content_hash") != current_hash):
                raise ValueError("Only a rendered story with a current passing review may be published")
            if snapshot_hash != current_hash:
                raise ValueError("The story changed after the publication snapshot was created")
            self._validate_output(project, project["output"])
            if same_content and previous.get("status") in {"uploading", "uncertain", "published"}:
                raise StoryBusy("This story is already uploading, published, or awaiting upload reconciliation")
        elif not same_content:
            raise ValueError("Publication result does not match the recorded upload")
        elif status == "published" and previous.get("status") not in {"uploading", "uncertain", "published"}:
            raise ValueError("A story must have a recorded upload before recording publication")
        elif status in {"failed", "uncertain"} and previous.get("status") == "published":
            raise ValueError("A published upload cannot be changed to a failure")
        for value, name in ((external_id, "External ID"), (url, "Publication URL"),
                            (error, "Publication error"), (account_id, "Account ID")):
            _clean_text(value, name, self.settings.stories.max_visual_prompt_chars, empty=True)
        record = {"status": status, "content_hash": snapshot_hash,
                  "revision": project.get("revision", 0) if snapshot_hash == current_hash else previous.get("revision", 0),
                  "account_id": account_id or previous.get("account_id", ""),
                  "external_id": external_id or previous.get("external_id", ""),
                  "url": url or previous.get("url", ""), "error": error, "updated_at": time.time()}
        if status == "uploading":
            record["attempted_at"] = time.time()
            record["attempt_id"] = uuid.uuid4().hex
        elif same_content and previous.get("attempted_at"):
            record["attempted_at"] = previous["attempted_at"]
            if previous.get("attempt_id"):
                record["attempt_id"] = previous["attempt_id"]
        before = copy.deepcopy(project)
        project.setdefault("publishing", {})[platform] = record
        if record.get("attempt_id"):
            history = project.setdefault("publication_history", [])
            historical = next((row for row in history if row.get("attempt_id") == record["attempt_id"]), None)
            if historical is None:
                history.append({"platform": platform, **copy.deepcopy(record)})
            else:
                historical.update(copy.deepcopy(record))
        project["updated_at"] = time.time()
        try:
            self._save()
        except OSError:
            project.clear()
            project.update(before)
            raise
        return copy.deepcopy(project)

    def retry(self, project_id: str) -> dict:
        """Restart an interrupted/failed draft job without adding another library row."""
        self._available()
        project = self._find(project_id)
        if project.get("kind") == "compilation":
            return self.render(project_id)
        self._not_uploading(project)
        if project.get("status") not in {"failed", "interrupted", "needs_review"}:
            raise ValueError("Only a failed, interrupted or rejected story may be regenerated")
        previous = copy.deepcopy(project)
        self._invalidate_output(project)
        project.update(status="queued", progress=0, error="", review={}, manual_edit=False,
                       revision=project.get("revision", 0) + 1, updated_at=time.time(),
                       agents=[{"role": role, "status": "idle", "model": "", "detail": ""} for role in ROLES])
        try:
            self._save()
        except OSError:
            project.clear()
            project.update(previous)
            raise
        self._launch(project, self._generate(project, self.settings.model_copy(deep=True)), "story-generate")
        return copy.deepcopy(project)

    def review(self, project_id: str) -> dict:
        """Run the private jury again after a user edits the public manuscript."""
        self._available()
        project = self._find(project_id)
        if project.get("kind") == "compilation":
            raise ValueError("Individual stories supply the creative reviews. Assemble the compilation to verify its audio/video and chapters")
        self._not_uploading(project)
        if project.get("status") not in {"draft", "needs_review", "ready", "failed", "interrupted"}:
            raise ValueError("Save a complete story before requesting review")
        normalized = self._normalize_story(project, project, self.settings, allow_assets=True)
        previous = copy.deepcopy(project)
        project.update(normalized, status="judging", progress=0, error="", review={}, updated_at=time.time())
        try:
            self._save()
        except OSError:
            project.clear()
            project.update(previous)
            raise
        self._launch(project, self._review(project, self.settings.model_copy(deep=True)), "story-review")
        return copy.deepcopy(project)

    def _stage(self, project: dict, stage: str, progress: float, detail: str = "", role: str = "", model: str = "") -> None:
        project.update(status=stage, progress=progress, updated_at=time.time())
        if role:
            agent = next(row for row in project["agents"] if row["role"] == role)
            agent.update(status="running", detail=detail, model=model)
        self._persist_job(project)

    def report_progress(self, project_id: str, stage: str, progress: float) -> None:
        """Optional renderer callback; only the active job may report bounded progress."""
        if not self.busy or project_id != self._active_id:
            return
        if stage not in {"narrating", "rendering"} or isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress) or not 0 <= progress <= 1:
            raise ValueError("Invalid render progress")
        self._stage(self._find(project_id), stage, progress)

    def _model(self, settings: Settings) -> str:
        current = plan(settings, self.vram_gb)
        return settings.stories.model.strip() or (current.judge_model if current.one_model else settings.ai.model)

    @staticmethod
    def _schema(role: str, settings: Settings, payload: dict) -> dict:
        """Ollama's constrained decoder enforces field types before JSON is sampled."""
        cfg = settings.stories
        text = {"type": "string", "minLength": 1, "maxLength": cfg.max_visual_prompt_chars}
        scene_limit = min(cfg.max_scenes, max(1, math.ceil(payload.get("target_seconds", cfg.default_duration_s) / cfg.scene_target_s)))

        def obj(properties):
            return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

        if role == "director":
            return obj({"title": text, "premise": text, "ending": text,
                        "beats": {"type": "array", "minItems": 1, "maxItems": scene_limit, "items": text}})
        if role == "judge":
            return obj({"passed": {"type": "boolean"}, "reason": text,
                        "issues": {"type": "array", "maxItems": cfg.max_scenes, "items": text}})
        words_per_scene = max(1, payload.get("total_narration_words_max", cfg.max_script_words) // scene_limit)
        narration = {"type": "string", "minLength": 1,
                     "pattern": rf"^(?:\S+\s+){{0,{words_per_scene - 1}}}\S+$"}
        scene = obj({"narration": narration, "visual_prompt": text,
                     "visual": obj({key: {"type": "string", "enum": sorted(values)} for key, values in VISUAL_CHOICES.items()})})
        ending = copy.deepcopy(scene)
        ending["description"] = "The final narrated scene: an earned concrete reveal and irreversible consequence, never another opening encounter or an unanswered question."
        ending["properties"]["narration"]["description"] = "Finish the story here. Reveal what the unsettling details mean and what permanently happens to the narrator."
        youtube = obj({"title": {"type": "string", "minLength": 1, "maxLength": min(cfg.max_title_chars, YOUTUBE_TITLE_MAX)},
                       "description": {"type": "string", "maxLength": YOUTUBE_DESC_MAX},
                       "tags": {"type": "array", "items": {"type": "string"}},
                       "hashtags": {"type": "array", "items": {"type": "string"}}})
        return obj({"title": {"type": "string", "minLength": 1, "maxLength": min(cfg.max_title_chars, YOUTUBE_TITLE_MAX)},
                    "scenes": {"type": "array", "minItems": 1 if scene_limit > 1 else 0, "maxItems": scene_limit - 1, "items": scene},
                    "ending": ending,
                    "public_copy": obj({"youtube": youtube})})

    async def _chat(self, role: str, payload: dict, settings: Settings) -> dict:
        cfg = settings.stories
        contracts = {
            "director": "Act as the director of a new original fictional horror story. Return JSON with title, premise, ending and beats (array of narrative beats). Invent an original arc with a hook, escalating stakes and a meaningful payoff. This is private planning, not narration. Never copy an existing author's script.",
            "writer": "Act as the original-fiction scriptwriter. Return one JSON object with title, scenes (opening/escalation array with narration, visual_prompt, and visual {setting,subject,action}), ending (one separate final scene with the same fields), public_copy {youtube:{title,description,tags,hashtags}}. Write the entire complete spoken story ONCE, in ordered scene narration strings followed by the ending narration. The mandatory ending field is the actual spoken payoff: an earned concrete reveal and irreversible consequence, never another opening encounter or an unanswered question. The app appends ending to scenes and concatenates exact narration into its script; do not repeat it in a separate script field. Narration is complete prose, with no editor notes, review language, stage directions, scene labels, self-assessment or markdown. Visual prompts are original illustrations of each scene. Structured visual setting must be corridor, forest, street, room or station; subject must be figure, creature or none; action must be approach, reveal, vanish, follow or wait. These represent an original stylized shadow-theatre stage, not photorealistic generative animation. Match the story to these stageable settings and actions; never depict an unrelated action just to fill a scene. Label the description as original fiction. Never set asset paths, invent an existing video, or copy a known story. Internal instructions and review notes must never become narration or public copy.",
            "judge": "Act as an independent story jury. Return JSON with passed (boolean), reason (string), issues (array of strings). Check original premise, coherent character motivation, escalating tension, satisfying ending, narrated prose, scene continuity, and absence of editorial notes from narration and public copy. This is fictional entertainment, not factual reporting. Fail weak or incomplete stories. Your reason and issues stay private and must never be inserted into narration.",
        }
        ai_visuals = cfg.image_backend == "comfyui" or cfg.image_backend == "automatic1111" or bool(cfg.image_provider_url)
        if ai_visuals:
            contracts["writer"] = contracts["writer"].replace(
                "These represent an original stylized shadow-theatre stage, not photorealistic generative animation. Match the story to these stageable settings and actions; never depict an unrelated action just to fill a scene.",
                "The structured visual fields are compatibility tags only; they do not limit the locations, props or actions in the story. The visual_prompt is the actual image direction. For each scene describe ONE visible instant: shot size and angle, identifiable subject and clothing, specific environment and recurring props, motivated light, and the visible change that matches the narration. Reuse identical character appearance, clothing and location details across scenes; vary wide, medium, over-shoulder and object inserts when each communicates new information. Establish normal geography before an anomaly; never reveal the full threat before the narration earns it. Use clear, readable silhouettes and restrained horror, not an unrelated monster in every image. No lettering, captions, logos, collages or creator imitation. Do not describe a sequence of incompatible actions in one still. Animated format currently means illustrated shots with restrained camera movement; do not promise lip sync or generated character acting.")
            contracts["director"] += " Plan a visually concrete story world: recurring character appearance and clothing, location layout, important props and the progression from normal state to anomaly, reveal and consequence. Include those details in the existing premise and beats, so the writer can preserve them. Choose purposeful viewpoints rather than repeating generic corridors."
            contracts["judge"] += " Also check that each image direction depicts its narrated event, preserves recurring appearances and props, and respects reveal order. Reject vague repeated atmosphere or an early monster reveal that spoils the scene."
        if cfg.image_backend == "comfyui" and cfg.motion_backend == "wan":
            contracts["writer"] = contracts["writer"].replace("Animated format currently means illustrated shots with restrained camera movement; do not promise lip sync or generated character acting.", "Animated format uses local image-to-video scene motion. The illustration establishes the first frame; describe a legible initial state that permits the narrated action, preserving the threat's reveal order. Keep movement physically simple and purposeful. Do not promise lip sync or actor-level performance.")
        prompt = cfg.jury_prompt if role == "judge" else cfg.prompt
        schema = self._schema(role, settings, payload)
        body = {"model": self._model(settings), "stream": False,
                "keep_alive": 0 if cfg.image_backend == "comfyui" and cfg.visual_release_story_model else settings.ai.keep_alive,
                "format": schema,
                "messages": [{"role": "system", "content": prompt + "\n\n" + contracts[role]},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                "options": {"temperature": 0 if role == "judge" else cfg.temperature,
                            "num_ctx": settings.ai.num_ctx, "num_predict": cfg.model_num_predict}}
        if settings.ai.vision_disable_thinking:
            body["think"] = False
        url = settings.ai.ollama_url.rstrip("/") + "/api/chat"
        async with self._gpu_lock:
            response = await self.http.post(url, json=body, timeout=cfg.timeout_s)
            if response.status_code == 400 and "think" in body:
                body.pop("think")
                response = await self.http.post(url, json=body, timeout=cfg.timeout_s)
            response.raise_for_status()
            raw = response.json().get("message", {}).get("content", "")
            if not isinstance(raw, str):
                raise BadModelOutput("The local model returned no story text")
            parsed = _extract_json(raw)
            if not isinstance(parsed, dict):
                raise BadModelOutput("The local model must return a JSON object")
            if role == "writer" and isinstance(parsed.get("ending"), dict) and isinstance(parsed.get("scenes"), list):
                parsed["scenes"] = [*parsed["scenes"], parsed.pop("ending")]
            if role == "writer" and "script" not in parsed:
                scenes = parsed.get("scenes", [])
                if isinstance(scenes, list) and all(isinstance(row, dict) and isinstance(row.get("narration"), str) for row in scenes):
                    parsed["script"] = "\n\n".join(row["narration"].strip() for row in scenes)
            return parsed

    def _role_complete(self, project: dict, role: str, detail: str) -> None:
        agent = next(row for row in project["agents"] if row["role"] == role)
        agent.update(status="complete", detail=detail)

    def _jury_result(self, verdict: dict, settings: Settings) -> dict:
        if not isinstance(verdict.get("passed"), bool) or not isinstance(verdict.get("issues"), list) or any(not isinstance(item, str) for item in verdict["issues"]):
            raise BadModelOutput("The story jury returned an incomplete review")
        reason = _clean_text(verdict.get("reason"), "Jury reason", settings.stories.max_visual_prompt_chars)
        issues = [_clean_text(issue, "Jury issue", settings.stories.max_visual_prompt_chars)
                  for issue in verdict["issues"] if issue.strip()]
        return {"passed": verdict["passed"] and not issues, "reason": reason, "issues": issues}

    @staticmethod
    def _word_budget(project: dict, settings: Settings) -> tuple[int, int, int]:
        cfg = settings.stories
        target = round(project["duration_s"] * cfg.narration_words_per_min / 60)
        minimum = max(cfg.min_script_words, math.ceil(target * cfg.target_words_min_ratio))
        maximum = min(cfg.max_script_words, math.floor(target * cfg.target_words_max_ratio))
        if minimum > maximum:
            raise ValueError("The requested duration conflicts with the configured narration word limits")
        return target, minimum, maximum

    def _direction(self, value: dict, settings: Settings) -> dict:
        outline = {key: value.get(key) for key in ("title", "premise", "ending", "beats")}
        for key in ("title", "premise", "ending"):
            _clean_text(outline[key], f"Director {key}", settings.stories.max_visual_prompt_chars)
        beats = outline["beats"]
        if (not isinstance(beats, list) or not 1 <= len(beats) <= settings.stories.max_scenes
                or any(not isinstance(beat, str) or not beat.strip() for beat in beats)):
            raise BadModelOutput("The director must provide narrative beats as an array of nonempty strings")
        return outline

    def _written(self, project: dict, value: dict, settings: Settings) -> dict:
        normalized = self._normalize_story(project, value, settings, allow_assets=False)
        _, minimum, maximum = self._word_budget(project, settings)
        if not minimum <= normalized["word_count"] <= maximum:
            raise BadModelOutput(f"The ENTIRE narration must contain {minimum} to {maximum} words for the requested {project['duration_s']} seconds; this response contains {normalized['word_count']} words. Rewrite a complete compact arc within that total budget, not that many words per scene.")
        return normalized

    async def _complete_role(self, role: str, payload: dict, settings: Settings, validate):
        current = payload
        for attempt in range(settings.stories.role_max_attempts):
            try:
                result = await self._chat(role, current, settings)
                return validate(result)
            except (ValueError, BadModelOutput) as exc:
                if attempt + 1 >= settings.stories.role_max_attempts:
                    raise
                logger.warning("story %s response failed validation; requesting bounded repair: %s", role, exc)
                current = {**payload, "repair_required": str(exc),
                           "repair_instruction": "Return a NEW complete JSON response matching the same schema and the total story word budget. Do not include this validation message in the narration or public metadata."}

    async def _review(self, project: dict, settings: Settings) -> None:
        try:
            self._stage(project, "judging", 0, "Reviewing your saved manuscript", "judge", self._model(settings))
            payload = {"genre": project["genre"], "target_seconds": project["duration_s"],
                       "story": {key: copy.deepcopy(project[key]) for key in ("title", "script", "scenes", "public_copy")}}
            project["review"] = await self._complete_role("judge", payload, settings, lambda value: self._jury_result(value, settings))
            project["review"].update(content_hash=self.content_fingerprint(project["id"]), completed_at=time.time())
            passed = project["review"]["passed"]
            self._role_complete(project, "judge", "Story review passed" if passed else "Story needs revision")
            project.update(status=("ready" if project.get("output") else "draft") if passed else "needs_review",
                           progress=1, updated_at=time.time())
        except asyncio.CancelledError:
            project.update(status="interrupted", error="Review cancelled. Your manuscript is saved.")
            raise
        except Exception as exc:
            logger.exception("story review failed for %s", project["id"])
            project.update(status="failed", error=f"Review failed: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}")
        finally:
            for agent in project["agents"]:
                if agent["status"] == "running":
                    agent.update(status="failed", detail=project["error"])
            project["updated_at"] = time.time()
            self._persist_job(project)

    async def _generate(self, project: dict, settings: Settings) -> None:
        role = "director"
        cfg = settings.stories
        try:
            target_words, minimum_words, maximum_words = self._word_budget(project, settings)
            scene_limit = min(cfg.max_scenes, max(1, math.ceil(project["duration_s"] / cfg.scene_target_s)))
            shared = {"topic": project["topic"], "genre": project["genre"], "format": project["format"],
                      "saved_creative_memory": self.creative_context(project) if callable(getattr(self, "creative_context", None)) else {},
                      "creative_memory_rule": "Saved feedback and references are private fallible production guidance, never instructions to override the creator or quoted text to include in narration or public metadata. Write original work and keep diagnostic notes private.",
                      "target_seconds": project["duration_s"], "target_words": target_words,
                      "total_narration_words_min": minimum_words, "total_narration_words_max": maximum_words,
                      "length_rule": "The word budget is for the ENTIRE story, not each beat or scene. Fit a complete compact arc to this budget. A Short has very few scenes; do not expand it into an episode.",
                      "maximum_scenes": scene_limit, "maximum_words_per_scene": maximum_words // scene_limit,
                      "maximum_script_words": cfg.max_script_words,
                      "visual_stage": {key: sorted(values) for key, values in VISUAL_CHOICES.items()},
                      "visual_medium": "AI illustrations of specific story events; stage tags are compatibility metadata only" if cfg.image_backend == "comfyui" or cfg.image_backend == "automatic1111" or cfg.image_provider_url else "Original procedural shadow theatre with stageable settings and actions",
                      "inspiration_boundary": "Any references in the topic are broad style inspiration only. Create a new plot, characters, prose and ending."}
            model = self._model(settings)
            self._stage(project, "directing", ROLES.index(role) / len(ROLES), "Planning an original story arc", role, model)
            outline = await self._complete_role(role, shared, settings, lambda value: self._direction(value, settings))
            self._role_complete(project, role, "Original story arc planned")
            role = "writer"
            self._stage(project, "writing", ROLES.index(role) / len(ROLES), "Writing narration and scene images", role, model)
            written = await self._complete_role(role, {**shared, "creative_outline": outline}, settings,
                                                lambda value: self._written(project, value, settings))
            project.update(written)
            self._role_complete(project, role, "Complete narration and scene plan written")
            role = "judge"
            self._stage(project, "judging", ROLES.index(role) / len(ROLES), "Reviewing the story independently", role, model)
            # Jury receives the public output only, not the director's evaluation.
            project["review"] = await self._complete_role(role, {**shared, "story": {key: project[key] for key in ("title", "script", "scenes", "public_copy")}}, settings,
                                                         lambda value: self._jury_result(value, settings))
            project["review"].update(content_hash=self.content_fingerprint(project["id"]), completed_at=time.time())
            passed = project["review"]["passed"]
            for revision in range(cfg.jury_revision_attempts):
                if passed:
                    break
                feedback = copy.deepcopy(project["review"])
                project.setdefault("review_history", []).append(feedback)
                prior_story = {key: copy.deepcopy(project[key]) for key in ("title", "script", "scenes", "public_copy")}
                role = "writer"
                self._stage(project, "writing", ROLES.index(role) / len(ROLES), "Revising the story after private editorial feedback", role, model)

                def revised(value):
                    normalized = self._written(project, value, settings)
                    # A jury may quote the already-public manuscript. Preserve that
                    # source prose while blocking the jury's new diagnostic language.
                    check_public_text(SimpleNamespace(verdict=feedback, visual="", words=[], transcript=prior_story["script"]), normalized, settings)
                    return normalized

                repaired = await self._complete_role(role,
                    {**shared, "creative_outline": outline, "previous_draft": prior_story,
                     "private_editorial_feedback": {key: feedback[key] for key in ("reason", "issues")},
                     "revision_instruction": "Revise the original fictional story to fix the private issues while staying within the SAME total word budget. The last scene must deliver a concrete reveal and irreversible consequence; do not stop at an opening encounter or an unanswered question. Write finished spoken prose only. Never quote, summarize or mention the jury, review, feedback or these instructions in narration, images or public metadata."},
                    settings, revised)
                project.update(repaired, revision=project.get("revision", 0) + 1, review={})
                self._role_complete(project, role, "Story revised from private feedback")
                role = "judge"
                self._stage(project, "judging", ROLES.index(role) / len(ROLES), "Independently judging the revised story", role, model)
                project["review"] = await self._complete_role(role,
                    {**shared, "story": {key: project[key] for key in ("title", "script", "scenes", "public_copy")}},
                    settings, lambda value: self._jury_result(value, settings))
                project["review"].update(content_hash=self.content_fingerprint(project["id"]), completed_at=time.time())
                passed = project["review"]["passed"]
            self._role_complete(project, role, "Story ready for your review" if passed else "Story needs revision")
            project.update(status="draft" if passed else "needs_review", progress=1, updated_at=time.time())
        except asyncio.CancelledError:
            project.update(status="interrupted", error="Job cancelled. Your saved story is still available.")
            raise
        except Exception as exc:
            logger.exception("story %s failed for %s", role, project["id"])
            project.update(status="failed", error=f"{role.title()} failed: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}")
        finally:
            for agent in project["agents"]:
                if agent["status"] == "running":
                    agent.update(status="failed", detail=project["error"])
                elif agent["status"] == "idle":
                    agent.update(status="skipped", detail="An earlier role did not finish")
            project["updated_at"] = time.time()
            self._persist_job(project)

    def _validate_output(self, project: dict, result: dict) -> dict:
        if not isinstance(result, dict):
            raise ValueError("Renderer returned no video")
        video = self._inside(project["id"], result.get("video_path"))
        audio = self._inside(project["id"], result.get("audio_path"))
        duration = result.get("duration_s")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Renderer did not return a measured narration duration")
        if video.stat().st_size == 0 or audio.stat().st_size == 0:
            raise ValueError("Renderer returned an empty video or audio file")
        # Keep only production metadata. A renderer cannot replace script, copy or review.
        clean = {"video_path": str(video), "audio_path": str(audio), "duration_s": duration}
        for key in ("width", "height", "fps", "visual_mode", "narrator", "warnings"):
            if key in result:
                clean[key] = copy.deepcopy(result[key])
        return clean

    def render(self, project_id: str) -> dict:
        self._available()
        project = self._find(project_id)
        self._not_uploading(project)
        if project.get("kind") == "compilation":
            if project["status"] not in {"draft", "ready", "failed", "interrupted"}:
                raise ValueError("Wait for compilation assembly to finish or cancel it")
            previous = copy.deepcopy(project)
            self._invalidate_output(project)
            project.update(status="rendering", progress=0, error="", review={}, updated_at=time.time())
            try:
                self._save()
            except OSError:
                project.clear()
                project.update(previous)
                raise
            self._launch(project, self._render_compilation(project, self.settings.model_copy(deep=True)), "story-compilation")
            return copy.deepcopy(project)
        if project["status"] not in {"draft", "ready"}:
            raise ValueError("Review and save a complete story draft before rendering")
        capabilities = self._capabilities()
        if self.renderer is None or not callable(self.renderer) or not capabilities.get("narrator_available"):
            raise ValueError("A working local narrator is required before rendering")
        if capabilities.get("render_available") is False or not capabilities.get(f"{project['format']}_available"):
            raise ValueError(f"The {project['format']} renderer is not available on this PC")
        normalized = self._normalize_story(project, project, self.settings, allow_assets=True)
        previous = copy.deepcopy(project)
        project.update(normalized)
        self._invalidate_output(project)
        project.update(status="narrating", progress=0, error="", updated_at=time.time())
        try:
            self._save()
        except OSError:
            project.clear()
            project.update(previous)
            raise
        self._launch(project, self._render(project, self.settings.model_copy(deep=True)), "story-render")
        return copy.deepcopy(project)

    async def _render(self, project: dict, settings: Settings) -> None:
        try:
            # Never send editorial/private fields to narration or visual generation.
            public = {key: copy.deepcopy(project[key]) for key in PUBLIC_FIELDS}
            result = await self.renderer(public, self._directory(project["id"]), settings)
            output = self._validate_output(project, result)
            project.update(output=output, status="ready", progress=1,
                           video_url=f"/api/stories/projects/{project['id']}/video",
                           audio_url=f"/api/stories/projects/{project['id']}/audio", updated_at=time.time())
        except asyncio.CancelledError:
            self._invalidate_output(project)
            project.update(status="interrupted", error="Production cancelled. The story draft is saved.")
            raise
        except Exception as exc:
            logger.exception("story production failed for %s", project["id"])
            self._invalidate_output(project)
            project.update(status="failed", error=f"Production failed: {str(exc)[:ERR_SNIPPET] or type(exc).__name__}")
        finally:
            project["updated_at"] = time.time()
            self._persist_job(project)

    def cancel(self, project_id: str) -> bool:
        project = self._find(project_id)
        if not self.busy or self._active_id != project_id:
            return False
        if not self._task.cancelling():
            self._task.cancel()
        # Persist immediately, including cancellation before the coroutine first runs.
        project.update(status="interrupted", error="Job cancelled. Your saved story is still available.", updated_at=time.time())
        self._persist_job(project)
        return True

    def delete(self, project_id: str) -> bool:
        try:
            project = self._find(project_id)
        except KeyError:
            return False
        self._not_uploading(project)
        if self.busy and self._active_id == project_id:
            raise StoryBusy("Cancel this story's job before deleting it")
        directory = self._directory(project_id)  # resolved strict hex child of the library
        index = self.projects.index(project)
        self.projects.remove(project)
        try:
            self._save()
        except OSError:
            self.projects.insert(index, project)
            raise
        if directory.exists():
            try:
                shutil.rmtree(directory)
            except OSError as exc:
                message = f"Story removed from the library, but some project files could not be deleted: {exc}"
                self.errors.append(message)
                logger.warning(message)
        return True
