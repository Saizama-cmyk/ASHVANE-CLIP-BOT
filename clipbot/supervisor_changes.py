"""Independent source-only staging, promotion journal and conflict-aware rollback.

This boundary is excluded from autonomous edits. Runtime content, account data and
credentials never enter a candidate workspace.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .config import atomic_write as _write_text

SOURCE_DIRS = {"clipbot", "tests", "scripts", "installer", "integrations", "docs", "phone", "art", "assets", "tiktok-site"}
SOURCE_FILES = {"requirements.txt", "pytest.ini", "pyproject.toml", "conftest.py"}
EDIT_SUFFIXES = {".py", ".js", ".css", ".html", ".txt", ".toml", ".ini", ".svg"}
SOURCE_SUFFIXES = EDIT_SUFFIXES | {".md", ".cjs", ".mjs", ".yaml", ".yml", ".iss", ".patch", ".swift", ".plist", ".pbxproj", ".entitlements", ".json", ".png", ".jpg", ".jpeg", ".ico", ".ttf", ".woff", ".woff2", ".wav"}
GENERATED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".expo", "out", "out_ashvane", "build", "dist", "artifacts"}
PROTECTED = {"clipbot/supervisor_changes.py", "clipbot/supervisor_sandbox.py",
             "clipbot/supervisor_bootstrap.py", "clipbot/__main__.py", "clipbot/__init__.py",
             "clipbot/auth.py", "clipbot/secure.py", "clipbot/publishers/oauth.py",
             "clipbot/supervisor_files.py", "clipbot/supervisor_extensions.py", "clipbot/supervisor_memory.py"}
PRIVATE_NAMES = {"settings.json", "profiles.json", "tokens.json", ".env", "credentials.json"}
PRIVATE_CALLS = {"eval", "exec", "__import__", "unprotect", "getenv", "home", "system", "_exit"}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path, content):
    if isinstance(content, str):
        return _write_text(path, content)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def source_path(root: Path, relative: str, *, edit=False) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Use a repository-relative source path")
    part = PurePosixPath(relative)
    if (part.as_posix() != relative or part.is_absolute() or ".." in part.parts or not part.parts
            or ":" in relative or part.name.casefold() in PRIVATE_NAMES or part.name.casefold().startswith(".env")
            or (part.suffix == ".json" and any(word in part.name.casefold() for word in ("token", "credential", "session", "secret")))
            or part.suffix not in SOURCE_SUFFIXES
            or (part.parts[0] not in SOURCE_DIRS and relative not in SOURCE_FILES)
            or (edit and (relative.casefold() in {p.casefold() for p in PROTECTED} or part.parts[0] != "clipbot" or part.suffix not in EDIT_SUFFIXES
                          or part.name.casefold() in {"__init__.py", "__main__.py"}
                          or (part.suffix != ".py" and part.parts[:len(("clipbot", "dashboard", "static"))] != ("clipbot", "dashboard", "static"))))):
        raise ValueError("This path is outside the supervisor's source-edit capability")
    target = root.joinpath(*part.parts)
    for path in (target, *target.parents):
        if path == root.parent:
            break
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Linked source paths are not allowed")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Source path escaped the checkout")
    if target.is_file() and target.stat().st_nlink > 1:
        raise ValueError("Hard-linked source files are excluded")
    return target


class SourceChanges:
    def __init__(self, settings, workspace: Path):
        self.settings, self.workspace = settings, workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    @property
    def root(self):
        raw = self.settings.supervisor.source_root
        root = Path(raw)
        if not raw or not root.is_absolute() or not (root / "clipbot").is_dir():
            raise ValueError("Configure a local Ashvane source checkout")
        if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
            raise ValueError("The source checkout cannot be a link")
        return root.resolve()

    def inventory(self):
        result, total = [], 0
        root = self.root
        paths = []
        for name in SOURCE_DIRS:
            for folder, directories, names in os.walk(root / name, followlinks=False):
                directories[:] = [part for part in directories if part not in GENERATED_DIRS and
                                  not (name == "art" and part.startswith("out_"))]
                for part in directories:
                    directory = Path(folder) / part
                    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
                        raise ValueError("Linked source directories are excluded")
                paths.extend(Path(folder) / name for name in names)
        paths += [root / name for name in SOURCE_FILES if (root / name).is_file()]
        for path in sorted(paths):
            rel = path.relative_to(root).as_posix()
            if "__pycache__" in path.parts or path.suffix not in SOURCE_SUFFIXES:
                continue
            if path.name.casefold() in PRIVATE_NAMES or path.name.casefold().startswith(".env") or (path.suffix == ".json" and any(word in path.name.casefold() for word in ("token", "credential", "session", "secret"))):
                continue
            source_path(root, rel)
            size = path.stat().st_size
            total += size
            if total > self.settings.supervisor.max_source_bytes:
                raise ValueError("Sanitized source exceeds its snapshot budget")
            try:
                source_path(root, rel, edit=True)
                editable = True
            except ValueError:
                editable = False
            result.append({"path": rel, "bytes": size, "sha256": digest(path.read_bytes()), "editable": editable})
        return result

    def read(self, relative):
        target = source_path(self.root, relative, edit=True)
        if target.stat().st_size > self.settings.supervisor.max_text_chars:
            # Reading is explicit and bounded, not a raw whole-repository dump.
            return target.read_text(encoding="utf-8")[:self.settings.supervisor.max_text_chars]
        return target.read_text(encoding="utf-8")

    def stage(self, job: Path, edits: list[dict]):
        cfg = self.settings.supervisor
        if not isinstance(edits, list) or not edits or len(edits) > cfg.max_patch_files:
            raise ValueError("Candidate has no edits or exceeds its file budget")
        baseline, candidate = job / "baseline", job / "candidate"
        baseline.mkdir(parents=True, exist_ok=False)
        candidate.mkdir(exist_ok=False)
        for record in self.inventory():
            rel = record["path"]
            for destination in (baseline, candidate):
                target = source_path(destination, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path(self.root, rel), target)
        changes, seen = [], set()
        for edit in edits:
            rel, text = edit.get("path"), edit.get("content")
            original = source_path(self.root, rel, edit=True)
            target = source_path(candidate, rel, edit=True)
            before = original.read_bytes() if original.exists() else b""
            if text is None and isinstance(edit.get("search"), str) and isinstance(edit.get("replacement"), str):
                search = edit["search"]
                old = before.decode()
                if not search or old.count(search) != 1:
                    raise ValueError("An edit must match one exact source fragment")
                text = old.replace(search, edit["replacement"], 1)
            if rel in seen or not isinstance(text, str) or len(text.encode()) > cfg.response_max_bytes:
                raise ValueError("Duplicate or oversized candidate edit")
            seen.add(rel)
            if edit.get("before_sha256") != digest(before):
                raise ValueError("Source changed since the engineer read it")
            if rel.endswith(".py"):
                new_tree = ast.parse(text)
                old_tree = ast.parse(before.decode()) if before else ast.parse("")
                old_calls = {ast.dump(n) for n in ast.walk(old_tree) if isinstance(n, ast.Call)}
                for node in ast.walk(new_tree):
                    if isinstance(node, ast.Call) and ast.dump(node) not in old_calls:
                        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                        if name in PRIVATE_CALLS:
                            raise ValueError("Candidate introduced a private-data or dynamic-execution capability")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            changes.append({"path": rel, "before_sha256": digest(before), "after_sha256": digest(text.encode()),
                            "existed": original.exists()})
        atomic_write(job / "changes.json", json.dumps(changes, indent=2))
        return baseline, candidate, changes

    def promote(self, job: Path, *, checks: dict, review: dict, home: Path | None = None):
        if checks.get("passed") is not True or review.get("passed") is not True:
            raise ValueError("Independent review and isolated checks must pass before promotion")
        changes = json.loads((job / "changes.json").read_text())
        for change in changes:
            current = source_path(self.root, change["path"], edit=True)
            if digest(current.read_bytes() if current.exists() else b"") != change["before_sha256"]:
                raise ValueError("Promotion conflict: current source has changed")
            candidate = source_path(job / "candidate", change["path"], edit=True)
            if digest(candidate.read_bytes()) != change["after_sha256"]:
                raise ValueError("Candidate changed after its evaluation")
        journal = {"status": "applying", "changes": changes, "job": job.name}
        atomic_write(job / "promotion.json", json.dumps(journal))
        try:
            for change in changes:
                target = source_path(self.root, change["path"], edit=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(target, source_path(job / "candidate", change["path"], edit=True).read_bytes())
            if home is not None:
                from .supervisor_bootstrap import stage_overlay
                journal["overlay"] = stage_overlay(job / "candidate", changes, home, job.name)
            journal["status"] = "applied"
            atomic_write(job / "promotion.json", json.dumps(journal))
        except BaseException:
            self.rollback(job, partial=True, home=home)
            raise
        return {"status": "source_applied", "files": len(changes), "restart_required": True,
                "deployment": "Verified runtime overlay activates at next restart" if home is not None else "Source checkout updated; restart source runtime to activate",
                "overlay": journal.get("overlay")}

    def rollback(self, job: Path, *, partial=False, home: Path | None = None):
        journal = json.loads((job / "promotion.json").read_text())
        changes = journal["changes"]
        # Preflight every path before touching any source; preserve concurrent owner edits.
        for change in changes:
            current = source_path(self.root, change["path"], edit=True)
            actual = digest(current.read_bytes() if current.exists() else b"")
            allowed = {change["after_sha256"], change["before_sha256"]} if partial else {change["after_sha256"]}
            if actual not in allowed:
                raise ValueError("Rollback conflict: preserve the owner's subsequent source edit")
            baseline = source_path(job / "baseline", change["path"])
            if change["existed"] and digest(baseline.read_bytes()) != change["before_sha256"]:
                raise ValueError("Rollback baseline digest changed")
        if journal.get("overlay") and home is not None:
            from .supervisor_bootstrap import rollback_overlay
            rollback_overlay(home, job.name)
        for change in changes:
            target = source_path(self.root, change["path"], edit=True)
            if change["existed"]:
                atomic_write(target, source_path(job / "baseline", change["path"]).read_bytes())
            else:
                target.unlink(missing_ok=True)
        journal["status"] = "rolled_back"
        atomic_write(job / "promotion.json", json.dumps(journal))
        return {"status": "rolled_back", "files": len(changes)}
