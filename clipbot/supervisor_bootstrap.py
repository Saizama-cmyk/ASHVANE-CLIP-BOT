"""Protected, stdlib-only startup gate for independently proven source overlays.

The frozen entrypoint calls activate_bootstrap before importing application modules.
Only manifest-pinned clipbot modules enter the import finder; sys.path is untouched.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import logging
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath

logger = logging.getLogger("clipbot.supervisor_bootstrap")
# Immutable bootstrap safety ceilings: settings/config cannot be imported at this gate.
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_OVERLAY_BYTES = 64 * 1024 * 1024
MAX_OVERLAY_FILES = 4096
FORMAT = 1
PROTECTED = frozenset({"clipbot/auth.py", "clipbot/secure.py", "clipbot/publishers/oauth.py",
    "clipbot/supervisor_changes.py", "clipbot/supervisor_sandbox.py", "clipbot/supervisor_bootstrap.py",
    "clipbot/supervisor_files.py", "clipbot/supervisor_extensions.py", "clipbot/supervisor_memory.py"})
STATIC_PREFIX = ("clipbot", "dashboard", "static")
STATIC_SUFFIXES = frozenset({".js", ".css", ".html", ".txt", ".svg", ".png", ".jpg", ".jpeg",
    ".ico", ".ttf", ".woff", ".woff2", ".wav"})
PRIVATE_NAMES = frozenset({"settings.json", "profiles.json", "tokens.json", "credentials.json", ".env"})
RESERVED = frozenset({"con", "prn", "aux", "nul", *("com" + n for n in "123456789"),
                       *("lpt" + n for n in "123456789")})
SHA256 = re.compile(r"[a-f0-9]{64}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
PYTHON_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ACTIVE = None


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plain(path: Path) -> Path:
    absolute = Path(path).absolute()
    for item in (absolute, *absolute.parents):
        if item.exists() or item.is_symlink():
            attrs = getattr(item.lstat(), "st_file_attributes", 0)
            if item.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Overlay paths cannot contain links or junctions")
    return absolute.resolve()


def _runtime(home: Path) -> Path:
    return _plain(Path(home) / "supervisor" / "runtime")


def _version(value: str) -> str:
    if (not isinstance(value, str) or not VERSION.fullmatch(value)
            or value.endswith(".") or value.casefold() in {"active.json", "pending.json", "manifest.json"}
            or value.split(".", 1)[0].casefold() in RESERVED):
        raise ValueError("Invalid overlay version")
    return value


def _relative(value: str) -> PurePosixPath:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(c) < ord(" ") for c in value)):
        raise ValueError("Use a strict clipbot source-relative path")
    part = PurePosixPath(value)
    if (part.is_absolute() or part.as_posix() != value or len(part.parts) < 2
            or part.parts[0] != "clipbot" or any(p.startswith(".") or p.endswith((".", " "))
                or p.split(".", 1)[0].casefold() in RESERVED for p in part.parts)
            or part.name.casefold() in PRIVATE_NAMES or value.casefold() in PROTECTED
            or part.name.casefold() in {"__init__.py", "__main__.py"}):
        raise ValueError("Overlay path is private, protected or outside clipbot")
    if part.parts[:len(STATIC_PREFIX)] == STATIC_PREFIX:
        if part.suffix not in STATIC_SUFFIXES:
            raise ValueError("Unsupported static overlay asset")
    elif part.suffix != ".py" or any(not PYTHON_NAME.fullmatch(p) for p in (*part.parts[:-1], part.stem)):
        raise ValueError("Only Python modules or dashboard static assets may be overlaid")
    return part


def _target(root: Path, relative: str) -> Path:
    part = _relative(relative)
    target = _plain(root.joinpath(*part.parts))
    if not target.is_relative_to(_plain(root)):
        raise ValueError("Overlay path escaped its source root")
    return target


def _read(path: Path, limit: int) -> bytes:
    target = _plain(path)
    if target.is_file() and target.stat().st_nlink != 1:
        raise ValueError("Hard-linked overlay files are not allowed")
    if not target.is_file() or target.stat().st_size > limit:
        raise ValueError("Overlay file is missing or exceeds its security ceiling")
    with target.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Overlay file grew beyond its security ceiling")
    return raw


def _encoded(value: dict) -> bytes:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Overlay metadata exceeds its security ceiling")
    return raw


def _atomic(path: Path, value: dict) -> None:
    target = _plain(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("." + target.name + "-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(_encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _reference(value) -> dict | None:
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"version", "manifest_sha256"}
            or not isinstance(value.get("manifest_sha256"), str)
            or not SHA256.fullmatch(value["manifest_sha256"])):
        raise ValueError("Invalid pinned overlay reference")
    return {"version": _version(value.get("version")), "manifest_sha256": value["manifest_sha256"]}


def _pointer(runtime: Path) -> dict:
    path = _plain(runtime / "active.json")
    if not path.exists():
        return {"format": FORMAT, "active": None, "previous": None}
    value = json.loads(_read(path, MAX_MANIFEST_BYTES))
    if (not isinstance(value, dict) or set(value) != {"format", "active", "previous"}
            or type(value["format"]) is not int or value["format"] != FORMAT):
        raise ValueError("Invalid overlay activation pointer")
    return {"format": FORMAT, "active": _reference(value["active"]), "previous": _reference(value["previous"])}


def _verify(runtime: Path, reference: dict) -> tuple[Path, dict]:
    reference = _reference(reference)
    if reference is None:
        raise ValueError("No overlay is selected")
    folder = _plain(runtime / reference["version"])
    if folder.parent != runtime:
        raise ValueError("Overlay version escaped runtime storage")
    raw = _read(folder / "manifest.json", MAX_MANIFEST_BYTES)
    if _digest(raw) != reference["manifest_sha256"]:
        raise ValueError("Overlay manifest changed after its promotion")
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "files"}
            or type(manifest["format"]) is not int or manifest["format"] != FORMAT
            or manifest["version"] != reference["version"] or not isinstance(manifest["files"], dict)
            or not manifest["files"] or len(manifest["files"]) > MAX_OVERLAY_FILES):
        raise ValueError("Invalid overlay manifest")
    total, folded = 0, set()
    for relative, entry in manifest["files"].items():
        target = _target(folder, relative)
        if (relative.casefold() in folded or not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"}
                or type(entry["bytes"]) is not int or entry["bytes"] < 0
                or not isinstance(entry["sha256"], str) or not SHA256.fullmatch(entry["sha256"])):
            raise ValueError("Invalid or duplicate overlay file pin")
        folded.add(relative.casefold())
        total += entry["bytes"]
        if total > MAX_OVERLAY_BYTES:
            raise ValueError("Overlay exceeds its total security ceiling")
        data = _read(target, min(MAX_OVERLAY_BYTES, entry["bytes"]))
        if len(data) != entry["bytes"] or _digest(data) != entry["sha256"]:
            raise ValueError("Overlay source changed after its promotion")
        if target.suffix == ".py":
            compile(data, str(target), "exec", dont_inherit=True)
    return folder, manifest


def stage_overlay(candidate: Path, changes: list, home: Path, version: str) -> dict:
    """Called only by the independent review/test promotion gate; never imports code."""
    runtime, candidate, version = _runtime(home), _plain(candidate), _version(version)
    if not isinstance(changes, list) or not changes or len(changes) > MAX_OVERLAY_FILES:
        raise ValueError("Overlay needs a bounded nonempty proven change list")
    runtime.mkdir(parents=True, exist_ok=True)
    initial = _pointer(runtime)
    final = _plain(runtime / version)
    if final.exists():
        raise ValueError("Overlay versions are immutable; choose a new version")
    files = {}
    previous_folder = None
    if initial["active"] is not None:
        previous_folder, previous_manifest = _verify(runtime, initial["active"])
        files.update(previous_manifest["files"])
    updates, seen = {}, set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Invalid proven change record")
        relative = change.get("path")
        target = _target(candidate, relative)
        if relative.casefold() in seen or not isinstance(change.get("after_sha256"), str):
            raise ValueError("Duplicate or unpinned overlay change")
        seen.add(relative.casefold())
        raw = _read(target, MAX_OVERLAY_BYTES)
        if not SHA256.fullmatch(change["after_sha256"]) or _digest(raw) != change["after_sha256"]:
            raise ValueError("Candidate changed after its isolated proof")
        if target.suffix == ".py":
            compile(raw, str(target), "exec", dont_inherit=True)
        updates[relative] = raw
        files[relative] = {"sha256": _digest(raw), "bytes": len(raw)}
    if len(files) > MAX_OVERLAY_FILES or sum(item["bytes"] for item in files.values()) > MAX_OVERLAY_BYTES:
        raise ValueError("Cumulative overlay exceeds its security ceiling")
    # Also reject differently cased versions of existing file names on every OS.
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError("Case-colliding overlay paths")
    stage = runtime / (".stage-" + uuid.uuid4().hex)
    stage.mkdir(exist_ok=False)
    try:
        for relative, entry in files.items():
            target = _target(stage, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = updates.get(relative)
            if raw is None:
                raw = _read(_target(previous_folder, relative), entry["bytes"])
                if _digest(raw) != entry["sha256"]:
                    raise ValueError("Previous overlay changed while staging")
            target.write_bytes(raw)
        manifest = {"format": FORMAT, "version": version, "files": files}
        _atomic(stage / "manifest.json", manifest)
        reference = {"version": version, "manifest_sha256": _digest(_read(stage / "manifest.json", MAX_MANIFEST_BYTES))}
        if _pointer(runtime) != initial:
            raise ValueError("Overlay promotion conflict: activation pointer changed")
        os.rename(stage, final)
        _verify(runtime, reference)
        for path in final.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        _atomic(runtime / "active.json", {"format": FORMAT, "active": reference, "previous": initial["active"]})
        return {"status": "overlay_staged", "version": version, "files": len(files),
                "overlay": str(final), "restart_required": True}
    finally:
        if stage.exists():
            checked = _plain(stage)
            if checked.parent != runtime or not checked.name.startswith(".stage-"):
                raise ValueError("Refusing unsafe staging cleanup")
            shutil.rmtree(checked)


class _PinnedLoader(importlib.abc.Loader):
    def __init__(self, finder, relative: str):
        self.finder, self.relative = finder, relative

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw = self.finder.read(self.relative)
        code = compile(raw, str(path), "exec", dont_inherit=True)
        module.__file__ = str(path)
        exec(code, module.__dict__)


class _OverlayFinder(importlib.abc.MetaPathFinder):
    def __init__(self, home: Path, folder: Path, manifest: dict, reference: dict):
        self.home, self.folder, self.manifest, self.reference = _plain(home), folder, manifest, reference
        self.modules = {relative[:-len(".py")].replace("/", "."): relative
                        for relative in manifest["files"] if relative.endswith(".py")}

    def read(self, relative: str) -> tuple[Path, bytes]:
        entry = self.manifest["files"].get(relative)
        if entry is None:
            raise ImportError("Resource is absent from the active overlay manifest")
        target = _target(self.folder, relative)
        raw = _read(target, entry["bytes"])
        if len(raw) != entry["bytes"] or _digest(raw) != entry["sha256"]:
            raise ImportError("Active overlay file changed after validation")
        return target, raw

    def find_spec(self, fullname, path=None, target=None):
        relative = self.modules.get(fullname)
        if relative is None:
            return None
        loader = _PinnedLoader(self, relative)
        return importlib.util.spec_from_loader(fullname, loader, origin=str(_target(self.folder, relative)))


def _uninstall() -> None:
    global _ACTIVE
    for finder in tuple(sys.meta_path):
        if isinstance(finder, _OverlayFinder):
            sys.meta_path.remove(finder)
    _ACTIVE = None


def _fallback(runtime: Path, pointer: dict) -> dict:
    previous = pointer["previous"]
    if previous is not None:
        try:
            _verify(runtime, previous)
        except (OSError, ValueError, SyntaxError):
            logger.exception("previous overlay failed validation; using bundled application")
            previous = None
    restored = {"format": FORMAT, "active": previous, "previous": None}
    _atomic(runtime / "active.json", restored)
    return restored


def activate_bootstrap(home: Path) -> bool:
    """Validate all overlay bytes before any selected application module can execute."""
    global _ACTIVE
    _uninstall()
    try:
        runtime = _runtime(home)
        pointer = _pointer(runtime)
        pending = _plain(runtime / "pending.json")
        if pending.exists():
            try:
                marker = json.loads(_read(pending, MAX_MANIFEST_BYTES))
                if not isinstance(marker, dict) or set(marker) != {"active"}:
                    raise ValueError("Invalid pending overlay boot marker")
                unconfirmed = _reference(marker["active"]) == pointer["active"]
            except (OSError, ValueError, RecursionError):
                logger.exception("invalid pending boot marker; recovering previous overlay")
                unconfirmed = True
            if unconfirmed:
                pointer = _fallback(runtime, pointer)
            pending.unlink()
        if pointer["active"] is None:
            return False
        try:
            folder, manifest = _verify(runtime, pointer["active"])
        except (OSError, ValueError, SyntaxError):
            logger.exception("active overlay failed validation; attempting previous version")
            pointer = _fallback(runtime, pointer)
            if pointer["active"] is None:
                return False
            folder, manifest = _verify(runtime, pointer["active"])
        finder = _OverlayFinder(home, folder, manifest, pointer["active"])
        if any(name in sys.modules for name in finder.modules):
            raise ValueError("Bootstrap must activate before importing overlaid application modules")
        _atomic(pending, {"active": pointer["active"]})
        sys.meta_path.insert(0, finder)
        _ACTIVE = finder
        return True
    except (OSError, ValueError, SyntaxError, RecursionError):
        logger.exception("overlay bootstrap refused unsafe state; using bundled application")
        _uninstall()
        return False


def mark_healthy(home: Path) -> None:
    """Called after application readiness, never merely after importing config."""
    if _ACTIVE is None or _ACTIVE.home != _plain(home):
        return
    pending = _plain(_runtime(home) / "pending.json")
    if pending.exists():
        marker = json.loads(_read(pending, MAX_MANIFEST_BYTES))
        if isinstance(marker, dict) and _reference(marker.get("active")) == _ACTIVE.reference:
            pending.unlink()


def overlay_resource(relative: str) -> Path | None:
    """Return a checked static asset from the currently activated overlay, if present."""
    part = _relative(relative)
    if part.parts[:len(STATIC_PREFIX)] != STATIC_PREFIX:
        raise ValueError("Only static overlay resources are available through this helper")
    if _ACTIVE is None or relative not in _ACTIVE.manifest["files"]:
        return None
    return _ACTIVE.read(relative)[0]


def rollback_overlay(home: Path, version: str) -> dict:
    runtime, version = _runtime(home), _version(version)
    pointer = _pointer(runtime)
    if pointer["active"] is None or pointer["active"]["version"] != version:
        raise ValueError("Overlay rollback conflict: version is no longer current")
    restored = _fallback(runtime, pointer)
    pending = _plain(runtime / "pending.json")
    if pending.exists():
        marker = json.loads(_read(pending, MAX_MANIFEST_BYTES))
        if isinstance(marker, dict) and _reference(marker.get("active")) == pointer["active"]:
            pending.unlink()
    return {"status": "overlay_rolled_back", "version": version,
            "active": restored["active"]["version"] if restored["active"] else None, "restart_required": True}
