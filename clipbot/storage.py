"""Move Ashvane's data when you pick a new folder.

Choosing a new location on the Storage page updates the setting and records a pending move
in ``<profile home>/pending_moves.json``. Nothing is moved while Ashvane is running (the
database and capture files are open); the move happens at the next start, before anything
opens them. Files that already exist at the destination are never overwritten.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import AppPaths, Settings, atomic_write, home_dir, resolve_paths, storage_role_folder
from .db import SQLITE_BUSY_TIMEOUT_S
from .models import ID_LEN

logger = logging.getLogger("clipbot.storage")

GB = 1024 ** 3
KINDS = {"data": "data_dir", "buffer": "buffer_dir", "work": "work_dir", "clips": "clips_dir",
         "logs": "logs_dir", "models": "models_dir"}
# never moved with the data folder: these belong to the profile / app, not the data
_STAY = {"settings.json", "profiles.json", "sessions.json", "pending_moves.json", "profiles",
         "webview"}
DATA_FILES = ("clipbot.db", "clipbot.db-wal", "clipbot.db-shm", "tokens.json", "analytics.json",
              "facecams.json", "research.json", "trends.json", "pet.json", "themes.json")


class StorageMoveIncomplete(RuntimeError):
    """Startup must not open an empty database while the original DB is still pending."""


def pending_path() -> Path:
    return home_dir() / "pending_moves.json"


def current_folder(paths: AppPaths, kind: str) -> Path | None:
    return {"data": paths.data, "buffer": paths.buffer, "work": paths.work, "clips": paths.clips,
            "logs": paths.logs, "models": paths.models}.get(kind)


def _checked_move(kind: str, src: Path, dest: Path) -> tuple[Path, Path]:
    if kind not in KINDS:
        raise ValueError("Unknown storage role")
    src, dest = Path(src), storage_role_folder(dest, kind)
    if not src.is_absolute() or not dest.is_absolute():
        raise ValueError("Storage moves require absolute folders")
    if src.is_symlink() or src.is_junction() or dest.is_symlink() or dest.is_junction():
        raise ValueError("Storage moves cannot use linked folders")
    src, dest = src.resolve(), dest.resolve()
    if src == Path(src.anchor):
        raise ValueError("A drive root cannot be a storage move source")
    if src != dest and (src.is_relative_to(dest) or dest.is_relative_to(src)):
        raise ValueError("Storage source and destination cannot overlap")
    return src, dest


def _save_pending(moves: list[dict]) -> None:
    if moves:
        atomic_write(pending_path(), json.dumps(moves, indent=2))
    else:
        pending_path().unlink(missing_ok=True)


def queue_move(kind: str, src: Path, dest: Path) -> None:
    src, dest = _checked_move(kind, src, dest)
    moves = [move for move in load_pending() if move.get("kind") != kind]
    if src != dest:
        moves.append({"kind": kind, "from": str(src), "to": str(dest)})
    _save_pending(moves)


def load_pending() -> list[dict]:
    p = pending_path()
    if not p.exists():
        return []
    try:
        moves = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(moves, list) or any(not isinstance(move, dict) for move in moves):
            raise ValueError("Expected a list of storage moves")
        return moves
    except (ValueError, OSError) as exc:
        logger.error("pending moves file unreadable: %s", exc)
        return []


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _candidate_files(db: Path) -> set[str]:
    if not db.is_file():
        return set()
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=SQLITE_BUSY_TIMEOUT_S)) as conn:
        rows = conn.execute("SELECT json FROM candidates").fetchall()
    files = set()
    for (raw,) in rows:
        record = json.loads(raw)
        for field in ("raw_path", "final_path"):
            value = record.get(field)
            if isinstance(value, str) and value:
                files.add(_path_key(value))
    return files


def _known_file(path: Path, src: Path, kind: str, referenced: set[str], settings: Settings) -> bool:
    relative = path.relative_to(src)
    if any(part in _STAY for part in relative.parts):
        return False
    if kind == "data":
        if len(relative.parts) == 1:
            return path.name in DATA_FILES or _path_key(path) in referenced
        role = relative.parts[0]
        attr = KINDS.get(role)
        if role in ("buffer", "work", "clips", "logs") and attr:
            return bool(not getattr(settings.app, attr)
                        and _known_file(path, src / role, role, referenced, settings))
        return _path_key(path) in referenced
    if _path_key(path) in referenced and kind in ("clips", "work"):
        return True
    if kind == "clips":
        return bool(re.fullmatch(rf".+_[0-9a-f]{{{ID_LEN}}}(?:\.studio)?\.mp4", path.name))
    if kind == "work":
        candidate = rf"(?:[0-9a-f]{{{ID_LEN}}}|.+_[0-9a-f]{{{ID_LEN}}})"
        return bool(re.fullmatch(candidate + r"(?:_raw|_main)?\.(?:mp4|ass)", path.name)
                    or re.fullmatch(r"clip_[A-Za-z0-9_-]+\.mp4", path.name)
                    or (relative.parts[0] in ("posters", "frames", "thumbs", "live", "studio")
                        and path.suffix.lower() in (".jpg", ".mp4")))
    if kind == "buffer":
        return bool(relative.parts[0].startswith(("twitch_", "kick_"))
                    and re.fullmatch(r"seg_[0-9]+\.ts", path.name))
    if kind == "logs":
        return bool(re.fullmatch(r"clipbot\.log(?:\.[0-9]+)?", path.name))
    if kind == "models":
        return bool(relative.parts[0] in ("blobs", "manifests"))
    return False


def _role_files(src: Path, kind: str, referenced: set[str], settings: Settings):
    for folder, directories, names in os.walk(src, followlinks=False):
        parent = Path(folder)
        directories[:] = [name for name in directories if name not in _STAY
                          and not (parent / name).is_symlink() and not (parent / name).is_junction()]
        for name in names:
            path = parent / name
            if path.is_symlink() or path.is_junction() or not path.is_file():
                continue
            if _known_file(path, src, kind, referenced, settings):
                yield path


def _rewrite_candidate_paths(db: Path, moved: dict[str, str]) -> int:
    """Repair exact successfully moved files, never a broad prefix replacement."""
    if not moved or not db.is_file():
        return 0
    changed = 0
    with closing(sqlite3.connect(db, timeout=SQLITE_BUSY_TIMEOUT_S)) as conn, conn:
        for cid, raw in conn.execute("SELECT id, json FROM candidates").fetchall():
            record = json.loads(raw)
            dirty = False
            for field in ("raw_path", "final_path"):
                value = record.get(field)
                if isinstance(value, str) and value and _path_key(value) in moved:
                    record[field] = moved[_path_key(value)]
                    dirty = True
            if dirty:
                conn.execute("UPDATE candidates SET json=? WHERE id=?", (json.dumps(record), cid))
                changed += 1
    return changed


def apply_pending(settings: Settings) -> list[str]:
    """Move known app files and repair saved candidates before Store opens."""
    # The selected active DB may not exist until the queued data transfer runs.
    # Repair media paths against that DB regardless of the order folders were queued.
    moves = sorted(load_pending(), key=lambda move: move.get("kind") != "data")
    if not moves:
        return []
    notes = []
    active_db = resolve_paths(settings).db.resolve()
    for move in list(moves):
        kind = move.get("kind", "unknown")
        try:
            src, dest = _checked_move(kind, Path(move["from"]), Path(move["to"]))
            move["from"], move["to"] = str(src), str(dest)
            if src == dest:
                moves.remove(move)
                _save_pending(moves)
                continue
            # When data itself is moving, read its closed database before the transfer.
            source_db = active_db
            if not source_db.is_file():
                data_move = next((row for row in moves if row.get("kind") == "data"), None)
                if data_move:
                    old_data, _ = _checked_move("data", Path(data_move["from"]), Path(data_move["to"]))
                    source_db = old_data / "clipbot.db"
            referenced = _candidate_files(source_db)
            if kind == "data" and (src / "clipbot.db").is_file():
                # Flush a crashed session's WAL before transferring the database file.
                with closing(sqlite3.connect(src / "clipbot.db", timeout=SQLITE_BUSY_TIMEOUT_S)) as conn:
                    result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if result and result[0]:
                        raise sqlite3.OperationalError("Source database is still in use")
            completed = move.setdefault("moved_files", [])
            moved = {}
            for item in completed:
                old, new = Path(item["from"]), Path(item["to"])
                if (old.is_relative_to(src) and new == dest / old.relative_to(src)
                        and not old.exists() and new.is_file()):
                    moved[_path_key(old)] = str(new)
            if not src.is_dir() and not completed:
                raise OSError("Source folder is missing or unavailable")
            failed = False
            count = 0
            for file in list(_role_files(src, kind, referenced, settings)) if src.is_dir() else []:
                target = dest / file.relative_to(src)
                if not target.resolve().is_relative_to(dest):
                    logger.error("not moving %s: destination escapes the selected folder", file)
                    failed = True
                    continue
                if target.exists():
                    logger.warning("not moving %s: %s already exists", file, target)
                    failed = True
                    continue
                transfer = {"from": str(file), "to": str(target)}
                # Record before transfer: after an interruption, a missing old file and
                # present new file establish completion without guessing from a prefix.
                completed.append(transfer)
                _save_pending(moves)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(file), str(target))
                except OSError as exc:
                    completed.remove(transfer)
                    _save_pending(moves)
                    logger.error("could not move %s: %s", file, exc)
                    failed = True
                    continue
                moved[_path_key(file)] = str(target)
                count += 1
            if moved and referenced and not active_db.is_file():
                raise OSError("Active database is unavailable; saved file mappings remain pending")
            repaired = _rewrite_candidate_paths(active_db, moved)
            notes.append(f"moved {count} file(s) of {kind} to {dest}; repaired {repaired} candidate(s)"
                         + ("; some files remain pending" if failed else ""))
            logger.info(notes[-1])
            if not failed:
                moves.remove(move)
            _save_pending(moves)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            notes.append(f"could not move {kind}: {exc}")
            logger.error(notes[-1])
            _save_pending(moves)
    if not active_db.is_file():
        for move in moves:
            if move.get("kind") == "data" and (Path(move["from"]) / "clipbot.db").is_file():
                raise StorageMoveIncomplete(
                    "The data-folder move did not transfer the original database. "
                    "Startup stopped to preserve the saved queue; restore access to the folders and restart.")
    return notes


def free_gb(path: Path) -> float:
    """Free space on the drive holding ``path``.

    Returns 0 when the folder cannot be reached at all - an unplugged USB stick, a network
    share that is down, a drive letter that no longer exists. A drive with no room and a drive
    that is not there both mean the same thing to the caller: do not write here."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free / GB
    except OSError as exc:
        logger.debug("cannot use %s: %s", path, exc)
        return 0.0


def clip_drives(settings: Settings, paths: AppPaths) -> list[Path]:
    """Every folder clips may be written to, in the order they should be tried: the main one
    first, then each drive added on the Storage page."""
    out = [paths.clips]
    for entry in settings.app.overflow_dirs:
        entry = entry.strip()
        if not entry:
            continue
        folder = Path(os.path.expandvars(entry))
        if folder not in out:
            out.append(folder)
    return out


def clips_target(settings: Settings, paths: AppPaths) -> Path:
    """Pick the drive to write the next clip to.

    The drives you list are a pool, not a chain: the first one with room wins, and any that is
    missing or full is skipped. That is what makes pulling a USB stick harmless - it simply
    stops being chosen, and the next clip lands on a drive that is actually there.

    When none has the free space you asked for, the roomiest reachable drive is used rather than
    insisting on the main one: a little tight beats writing to a folder that is not mounted. Only
    if nothing at all can be reached does it fall back to the main folder, so the caller always
    gets a path and the failure surfaces as one clear error instead of a missing attribute."""
    want = settings.app.overflow_free_gb
    space = [(folder, free_gb(folder)) for folder in clip_drives(settings, paths)]

    for folder, free in space:
        if free >= want:
            if folder != paths.clips:
                logger.info("clips going to %s (%.0f GB free; earlier drives are full or gone)",
                            folder, free)
            return folder

    reachable = [(folder, free) for folder, free in space if free > 0]
    if reachable:
        folder, free = max(reachable, key=lambda pair: pair[1])
        logger.warning("every clip drive is under %.0f GB free; using the roomiest, %s (%.1f GB)",
                       want, folder, free)
        return folder

    logger.error("no clip drive can be reached; still writing to %s", paths.clips)
    return paths.clips
