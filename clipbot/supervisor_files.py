"""Bounded local file discovery/read access; repairs use the source change gate."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .supervisor_memory import clean

PRIVATE_DIRS = {".ssh", ".aws", ".azure", ".gnupg", "credentials", "vault", "wallets",
                "google", "mozilla", "microsoftedge", "user data", "passwords", ".git", ".kube"}
PRIVATE_FILES = {".env", "settings.json", "profiles.json", "sessions.json", "mcp.json",
                 "tokens.json", "tokens-stories.json", "credentials.json", "auth.json", "login data", "cookies", ".netrc", ".pypirc"}
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".mjs", ".html", ".css", ".svg", ".md", ".txt",
                 ".toml", ".ini", ".yaml", ".yml", ".log", ".json"}


class LocalFiles:
    def __init__(self, settings, private_root: Path):
        self.settings, self.private_root = settings, private_root.resolve()

    def path(self, raw):
        if not isinstance(raw, str):
            raise ValueError("Use an absolute local file path")
        path = Path(raw)
        if not path.is_absolute() or (os.name == "nt" and not path.drive.endswith(":")):
            raise ValueError("Only absolute paths on local drives are supported")
        folded = [part.casefold() for part in path.parts]
        codex_private = ".codex" in folded and not any(part in {"skills", "plugins"} for part in folded[folded.index(".codex") + 1:])
        if codex_private or any(part in PRIVATE_DIRS for part in folded) or path.name.casefold() in PRIVATE_FILES or path.name.casefold().startswith(".env"):
            raise ValueError("This is a private credential or account location")
        for parent in (path, *path.parents):
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ValueError("Linked file paths are excluded")
        path = path.resolve()
        if path.is_file() and path.stat().st_nlink > 1:
            raise ValueError("Hard-linked files are excluded")
        if path.is_relative_to(self.private_root):
            raise ValueError("Ashvane account/runtime data is excluded from file discovery")
        return path

    def browse(self, raw, pattern="*", recursive=False):
        root = self.path(raw)
        if not root.is_dir() or not isinstance(pattern, str) or len(pattern) > self.settings.supervisor.max_text_chars:
            raise ValueError("Choose a local folder and filename pattern")
        found, examined, denied = [], 0, 0
        limit, cap = self.settings.supervisor.file_scan_limit, self.settings.supervisor.max_history
        pending = [root]
        while pending and examined < limit and len(found) < cap:
            folder = pending.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        examined += 1
                        if examined > limit or len(found) >= cap:
                            break
                        try:
                            path = self.path(entry.path)
                            directory = entry.is_dir(follow_symlinks=False)
                            if recursive and directory:
                                pending.append(path)
                            if fnmatch.fnmatch(entry.name.casefold(), pattern.casefold()):
                                stat = entry.stat(follow_symlinks=False)
                                found.append({"path": str(path), "kind": "folder" if directory else "file",
                                              "bytes": stat.st_size, "modified_at": stat.st_mtime})
                        except (OSError, ValueError):
                            denied += 1
            except OSError:
                denied += 1
        return {"entries": found, "examined": examined, "excluded": denied,
                "truncated": bool(pending) or examined >= limit or len(found) >= cap}

    def read(self, raw, offset=0):
        path = self.path(raw)
        if path.suffix.casefold() not in TEXT_SUFFIXES or not path.is_file():
            raise ValueError("Local reads support text/source/configuration files, not private databases or media")
        if path.stat().st_size > self.settings.supervisor.response_max_bytes:
            raise ValueError("File exceeds the bounded local-read size limit")
        if type(offset) is not int or offset < 0:
            raise ValueError("Offset must be non-negative")
        text = clean(path.read_text(encoding="utf-8"), self.settings.supervisor.response_max_bytes)
        return {"path": str(path), "characters": len(text), "offset": offset,
                "text": clean(text[offset:offset + self.settings.supervisor.max_text_chars], self.settings.supervisor.max_text_chars)}
