"""Managed, non-destructive REAPER sessions, allowlisted edits and native renders.

No model response is executed as code. Presets are original synthesized patterns,
not a claim that text notes were interpreted or that generated audio was transcribed.
"""
from __future__ import annotations

from array import array
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import struct
import subprocess
import threading
import time
import uuid
import wave

APP = Path(__file__).resolve().parent
ROOT = APP / "reaper" / "projects"
STUDIO_DATA = APP.parent / "studio" / "data"
RENDERS = APP / "renders"
CONFIG = json.loads((APP / "reaper_config.json").read_text(encoding="utf-8"))
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
STYLES = ("trap", "boom-bap", "four-on-floor")
KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
INSTRUMENTS = ("kick", "snare", "hat", "bass", "keys")
FX = {"ReaEQ": "ReaEQ (Cockos)", "ReaComp": "ReaComp (Cockos)", "ReaVerbate": "ReaVerbate (Cockos)", "ReaLimit": "ReaLimit (Cockos)"}
EQ_TYPES = {"high_pass": 0, "low_shelf": 1, "band": 2, "notch": 3, "high_shelf": 4, "low_pass": 5}
_lock = threading.RLock()
_active = set()
_children = set()
_jobs = {}
_listening = None
_listen_cancel = threading.Event()
_cancelled = set()
_enabled = True


class ReaperError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat()


def _number(value, low, high, label, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ReaperError(f"{label} must be {'an integer ' if integer else ''}from {low} to {high}.")
    return value


def _text(value, limit, label):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ReaperError(f"{label} must be text up to {limit} characters.")
    return value.strip()


def _inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _managed(path, root):
    if not _inside(path, root):
        raise ReaperError("Managed project media is unavailable.", 404)
    cur = path
    while cur != root.parent:
        if cur.is_symlink() or (hasattr(cur, "is_junction") and cur.is_junction()):
            raise ReaperError("Managed project folders cannot be links.", 404)
        if cur == cur.parent:
            break
        cur = cur.parent
    return path


def _folder(ident):
    if not isinstance(ident, str) or not UUID.fullmatch(ident):
        raise ReaperError("That REAPER project was not found.", 404)
    return _managed(ROOT / ident, APP)


def _save(path, value):
    _managed(path, APP)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    _managed(temporary, APP)
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _load(ident):
    path = _folder(ident) / "project.json"
    _managed(path, APP)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ReaperError("That REAPER project was not found.", 404)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReaperError("That REAPER project record cannot be read.", 404) from None
    if result.get("id") != ident:
        raise ReaperError("That REAPER project record is invalid.", 404)
    return result


def get_project(ident):
    with _lock:
        result = _load(ident)
        if ident not in _active:
            changed = False
            for rev in result.get("revisions", []):
                if rev.get("status") in ("queued", "editing", "rendering"):
                    rev.update(status="failed", message="The native job was interrupted; its source session is preserved.")
                    changed = True
            if changed:
                _save(_folder(ident) / "project.json", result)
        return result


def _update(ident, revision_id, **fields):
    with _lock:
        project = _load(ident)
        rev = next(r for r in project["revisions"] if r["id"] == revision_id)
        rev.update(fields)
        project["updated_at"] = _now()
        _save(_folder(ident) / "project.json", project)


def status():
    projects = []
    if ROOT.is_dir():
        for folder in sorted(ROOT.iterdir(), reverse=True):
            if UUID.fullmatch(folder.name):
                try:
                    projects.append(get_project(folder.name))
                except ReaperError:
                    continue
    installed = Path(CONFIG["reaper_executable"]).is_file()
    dry_renders = []
    if RENDERS.is_dir():
        for candidate in RENDERS.iterdir():
            if UUID.fullmatch(candidate.name):
                try:
                    record, paths = _source_render(candidate.name)
                    dry_renders.append({"id": record["id"], "source_song_id": record.get("source_song_id"),
                                        "title": record.get("output", {}).get("title", "Artist render"),
                                        "duration_seconds": record.get("output", {}).get("duration_seconds", 0),
                                        "original_dry_vocal": True, "converted_dry_vocal": True, "backing": True})
                except ReaperError:
                    continue
    with _lock:
        busy = bool(_active)
    health_path = APP / "reaper" / "native-health.json"
    health = {}
    if health_path.is_file() and _inside(health_path, APP):
        try:
            health = json.loads(health_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            health = {}
    return {"installed": installed, "ready": installed and health.get("status") != "blocked", "busy": busy, "projects": projects, "native_health": health or {"status": "unverified"},
            "dry_vocals_available": bool(dry_renders), "dry_vocal_renders": dry_renders,
            "defaults": {"bpm": CONFIG["default_bpm"], "bars": CONFIG["default_bars"], "beat_style": CONFIG["default_style"], "key": CONFIG["default_key"], "seed": 0},
            "options": {"beat_styles": STYLES, "keys": KEYS, "instruments": INSTRUMENTS},
            "limits": {"bpm": [40, 240], "bars": [1, 64], "max_seconds": CONFIG["max_project_seconds"]},
            "message": "Native REAPER available. Preset patterns and saved notes do not interpret a producer brief; request and review an AI plan separately." if installed else "Install REAPER before opening or exporting sessions."}


def _patterns(style, root_note):
    patterns = {"trap": ([0, 6, 10, 14], [8], list(range(0, 16, 2))),
                "boom-bap": ([0, 7, 10], [4, 12], list(range(0, 16, 2))),
                "four-on-floor": ([0, 4, 8, 12], [4, 12], [2, 6, 10, 14])}[style]
    return [{"instrument": name, "steps": steps, "velocity": vel, "note": note}
            for name, steps, vel, note in zip(INSTRUMENTS, (*patterns, [0, 6, 10], [0, 8]), (110, 95, 65, 85, 65), (36, 38, 42, root_note, root_note + 24))]


def validate_tracks(tracks):
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 12:
        raise ReaperError("Choose 1 to 12 instrument patterns.")
    result = []
    for t in tracks:
        if not isinstance(t, dict) or set(t) - {"instrument", "steps", "velocity", "note", "notes"} or t.get("instrument") not in INSTRUMENTS:
            raise ReaperError("Use only kick, snare, hat, bass or keys patterns.")
        if "notes" in t:
            if "steps" in t or not isinstance(t["notes"], list) or not 1 <= len(t["notes"]) <= 256:
                raise ReaperError("Use either steps or 1 to 256 individual notes per bar.")
            notes = []
            for note in t["notes"]:
                if not isinstance(note, dict) or set(note) - {"step", "note", "velocity", "length_steps"}:
                    raise ReaperError("Each note contains a step, MIDI pitch, velocity and length in steps.")
                notes.append({"step": _number(note.get("step"), 0, 15.999, "Note step"), "note": _number(note.get("note"), 24, 96, "MIDI note", True),
                              "velocity": _number(note.get("velocity", 90), 1, 127, "Note velocity", True),
                              "length_steps": _number(note.get("length_steps", 1), .125, 16, "Note length")})
            result.append({"instrument": t["instrument"], "notes": notes})
            continue
        steps = t.get("steps")
        if not isinstance(steps, list) or len(steps) > 16:
            raise ReaperError("Each pattern uses unique sixteenth-note steps from 0 to 15.")
        steps = [_number(s, 0, 15, "Pattern step", True) for s in steps]
        if len(set(steps)) != len(steps):
            raise ReaperError("Pattern steps cannot repeat.")
        result.append({"instrument": t["instrument"], "steps": sorted(steps), "velocity": _number(t.get("velocity", 90), 1, 127, "Velocity", True), "note": _number(t.get("note", 36), 24, 96, "MIDI note", True)})
    return result


def validate_create(payload):
    allowed = {"song_id", "render_id", "title", "bpm", "bars", "beat_style", "key", "seed", "producer_brief", "replace_backing", "tracks"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ReaperError("Use the displayed music source and beat controls.")
    p = {"title": _text(payload.get("title", "Original beat session"), 120, "Title") or "Original beat session",
         "producer_brief": _text(payload.get("producer_brief", ""), 2000, "Producer brief"),
         "bpm": _number(payload.get("bpm", CONFIG["default_bpm"]), 40, 240, "Tempo"),
         "bars": _number(payload.get("bars", CONFIG["default_bars"]), 1, 64, "Bars", True),
         "seed": _number(payload.get("seed", 0), 0, 2147483647, "Seed", True),
         "beat_style": payload.get("beat_style", CONFIG["default_style"]), "key": payload.get("key", CONFIG["default_key"]),
         "replace_backing": payload.get("replace_backing", False)}
    if p["beat_style"] not in STYLES or p["key"] not in KEYS or type(p["replace_backing"]) is not bool:
        raise ReaperError("Choose an available style/key and a boolean backing-replacement control.")
    for field in ("song_id", "render_id"):
        ident = payload.get(field)
        if ident is not None:
            if not isinstance(ident, str) or not UUID.fullmatch(ident):
                raise ReaperError("Choose an owned saved take or artist render.")
            p[field] = ident
    p["tracks"] = validate_tracks(payload["tracks"]) if "tracks" in payload else _patterns(p["beat_style"], 36 + KEYS.index(p["key"]))
    if p["bars"] * 240 / p["bpm"] > CONFIG["max_project_seconds"]:
        raise ReaperError("This beat exceeds the configured project-duration limit.")
    return p


def _source_song(ident):
    database = STUDIO_DATA / "library.sqlite"
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM songs WHERE id=? AND source='local_generation'", (ident,)).fetchone()
        if row is None:
            raise ReaperError("That owned generated take was not found.", 404)
        result = dict(row)
        audio = Path(result["audio_path"])
        if not audio.is_file() or not _inside(audio, STUDIO_DATA / "media"):
            raise ReaperError("That take's retained master is unavailable.", 404)
        replay = json.loads(result.get("replay_request_json") or "{}") or {}
        settings = json.loads(result.get("generation_settings_json") or "{}") or {}
        meta = json.loads(result.get("metadata_json") or "{}") or {}
        return audio, result["title"], replay.get("abc") or settings.get("abc") or "", meta.get("duration_seconds", 0)
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise ReaperError("The retained local song library cannot be read.", 503) from None


def retained_songs(ident=None):
    """Read-only projection keeps owned masters readable while Studio is stopped."""
    database = STUDIO_DATA / "library.sqlite"
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            sql = "SELECT id,title,audio_path,caption,lyrics,metadata_json,generation_settings_json,replay_request_json,created_at FROM songs WHERE source='local_generation'"
            rows = con.execute(sql + (" AND id=?" if ident else " ORDER BY created_at DESC"), (ident,) if ident else ()).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            audio = Path(r.pop("audio_path"))
            if not audio.is_file() or not _inside(audio, STUDIO_DATA / "media"):
                continue
            for original, name in (("metadata_json", "metadata"), ("generation_settings_json", "generation_settings"), ("replay_request_json", "replay_request")):
                r[name] = json.loads(r.pop(original) or "{}") or {}
            result.append(r)
        return result
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise ReaperError("The retained local song library cannot be read.", 503) from None


def retained_audio(ident):
    if not isinstance(ident, str) or not UUID.fullmatch(ident):
        raise ReaperError("That retained generated take was not found.", 404)
    return _source_song(ident)[0]


def _source_render(ident):
    folder = _managed(RENDERS / ident, APP)
    try:
        record_path = _managed(folder / "job.json", APP)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") != "completed" or record.get("id") != ident:
            raise ReaperError("Choose a completed artist render.", 409)
        paths = {"Artist master reference": folder / "master.wav", "Original dry vocal": folder / "stems/htdemucs/source/vocals.wav",
                 "Converted dry vocal": folder / "converted-vocal.wav", "Generated backing": folder / "stems/htdemucs/source/no_vocals.wav"}
        if not all(_managed(p, APP).is_file() for p in paths.values()):
            raise ReaperError("This artist render is missing its retained dry vocal or backing.", 409)
        return record, paths
    except (OSError, ValueError):
        raise ReaperError("That retained artist render is unavailable.", 404) from None


def _rpp_quote(value):
    return '"' + str(value).replace('\\', '/').replace('"', "'").replace('\n', ' ').replace('\r', ' ') + '"'


def _synth(instrument, note, velocity, rng, length_seconds=None):
    rate = CONFIG["sample_rate"]
    seconds = CONFIG.get("synth_" + instrument + "_seconds", CONFIG["synth_note_seconds"])
    if length_seconds is not None and instrument in ("bass", "keys"):
        seconds = length_seconds
    freq = 440 * 2 ** ((note - 69) / 12)
    result = array("f")
    phase = 0.0
    for i in range(int(rate * seconds)):
        t = i / rate
        env = math.exp(-t * (9 if instrument == "bass" else 20))
        if instrument == "kick":
            phase += 2 * math.pi * (45 + 105 * math.exp(-t * 35)) / rate
            value = math.sin(phase) * math.exp(-t * 17)
        elif instrument == "snare":
            value = (rng.uniform(-1, 1) * .75 + math.sin(t * 2 * math.pi * 180) * .25) * math.exp(-t * 28)
        elif instrument == "hat":
            value = rng.uniform(-1, 1) * math.exp(-t * 70) * .45
        else:
            value = (math.sin(t * 2 * math.pi * freq) + .2 * math.sin(t * 4 * math.pi * freq)) * env * min(1, t * 300) * .65
        result.append(value * velocity / 127)
    return result


def _vlq(value):
    data = [value & 127]
    while value >> 7:
        value >>= 7
        data.insert(0, (value & 127) | 128)
    return bytes(data)


def _write_pattern(folder, index, track, parameters, duration, prefix=None):
    rate = CONFIG["sample_rate"]
    audio = array("f", [0]) * int(duration * rate)
    rng = random.Random(parameters["seed"] + index)
    beat_seconds = 60 / parameters["bpm"]
    notes = track.get("notes") or [{"step": step, "note": track["note"], "velocity": track["velocity"], "length_steps": 1} for step in track["steps"]]
    sounds = [_synth(track["instrument"], note["note"], note["velocity"], rng, note["length_steps"] * beat_seconds / 4) for note in notes]
    bar_count = math.ceil(duration / (beat_seconds * 4))
    events = []
    for bar in range(bar_count):
        for note, sound in zip(notes, sounds):
            start = int((bar * 4 + note["step"] / 4) * beat_seconds * rate)
            for j in range(min(len(sound), len(audio) - start)):
                audio[start + j] += sound[j]
            tick = int(bar * 1920 + note["step"] * 120)
            events.extend([(tick, bytes([0x90, note["note"], note["velocity"]])), (tick + int(note["length_steps"] * 120), bytes([0x80, note["note"], 0]))])
    stem = prefix or f"beat-{index + 1}-{track['instrument']}"
    wav_path = folder / "media" / (stem + ".wav")
    with wave.open(str(wav_path), "wb") as w:
        w.setparams((1, 2, rate, len(audio), "NONE", "not compressed"))
        w.writeframes(array("h", (int(max(-.98, min(.98, v)) * 32767) for v in audio)).tobytes())
    midi = b"\x00\xff\x51\x03" + int(60_000_000 / parameters["bpm"]).to_bytes(3, "big")
    last = 0
    for tick, event in sorted(events, key=lambda e: e[0]):
        midi += _vlq(tick - last) + event
        last = tick
    midi += b"\x00\xff\x2f\x00"
    (wav_path.with_suffix(".mid")).write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(midi)) + midi)
    return wav_path


def create_project(payload):
    p = validate_create(payload)
    retained = None
    sources = []
    duration = p["bars"] * 240 / p["bpm"]
    score = ""
    if p.get("song_id"):
        audio, title, score, source_duration = _source_song(p["song_id"])
        duration = max(duration, source_duration)
        sources.append(("Original master reference", audio, bool(p.get("render_id")), 0))
    if p.get("render_id"):
        retained, paths = _source_render(p["render_id"])
        if p.get("song_id") and retained.get("source_song_id") != p["song_id"]:
            raise ReaperError("Choose an artist render of the selected take.", 409)
        duration = max(duration, retained.get("output", {}).get("duration_seconds", 0))
        sources.extend((name, path, name in ("Artist master reference", "Original dry vocal") or (name == "Generated backing" and p["replace_backing"]), CONFIG["default_vocal_gain_db"] if "vocal" in name else 0) for name, path in paths.items())
    if p["replace_backing"] and retained is None:
        raise ReaperError("Replacing backing needs a completed artist render with real separated dry vocals. A full mix cannot supply an isolated vocal.", 409)
    if duration > CONFIG["max_project_seconds"]:
        raise ReaperError("Source audio exceeds the configured project-duration limit.")
    ident = str(uuid.uuid4())
    folder = _folder(ident)
    (folder / "media").mkdir(parents=True)
    tracks = []
    for n, (name, source, muted, gain_db) in enumerate(sources):
        path = folder / "media" / (f"source-{n}" + source.suffix.lower())
        shutil.copyfile(source, path)
        tracks.append({"name": name, "file": str(path.relative_to(folder)), "mute": muted, "volume_db": gain_db})
    for index, track in enumerate(p["tracks"]):
        path = _write_pattern(folder, index, track, p, duration)
        tracks.append({"name": f"Beat {index + 1} - {track['instrument']}", "file": str(path.relative_to(folder)), "mute": False, "volume_db": CONFIG["default_beat_gain_db"]})
    lines = ['<REAPER_PROJECT 0.1 7.82 1', f'  TEMPO {p["bpm"]} 4 4', '  SAMPLERATE 48000', '  MASTER_VOLUME 0.8', '  TIMEMODE 1 0 -1', '  LOCK 0']
    for t in tracks:
        source_type = {".flac": "FLAC", ".mp3": "MP3", ".ogg": "VORBIS"}.get(Path(t["file"]).suffix.lower(), "WAVE")
        lines.extend(['  <TRACK', '    NAME ' + _rpp_quote(t["name"]), f'    VOLPAN {10 ** (t["volume_db"] / 20)} 0', f'    MUTESOLO {int(t["mute"])} 0 0', '    <ITEM', '      POSITION 0', f'      LENGTH {duration}', '      VOLPAN 1 0 1 -1', '      SOFFS 0', '      PLAYRATE 1 1 0 -1 0 0.0025', '      <SOURCE ' + source_type, '        FILE ' + _rpp_quote(t["file"]), '      >', '    >', '  >'])
    lines.append('>')
    (folder / "session.rpp").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if score:
        (folder / "score.abc").write_text(score, encoding="utf-8")
    record = {"id": ident, "title": p["title"], "created_at": _now(), "updated_at": _now(), "duration_seconds": duration,
              "parameters": p, "tracks": tracks, "revisions": [], "current_revision_id": None,
              "notes": "Original synthesized preset patterns; producer brief retained as notes until a reviewed AI plan is applied. MIDI pattern files accompany the separate audio tracks. Separated vocals can retain bleed; score tempo is planning data, not verified beat alignment."}
    _save(folder / "project.json", record)
    return record


def open_project(ident):
    record = get_project(ident)
    executable = Path(CONFIG["reaper_executable"])
    if not executable.is_file():
        raise ReaperError("REAPER is not installed.", 503)
    path = _session_path(record)
    # Opening the editor is explicit. A new instance never replaces an unsaved editor.
    subprocess.Popen([str(executable), "-newinst", str(path)], cwd=path.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"opened": True, "project_id": ident, "message": "Opened a separate REAPER instance on this PC; phone playback uses exported revisions."}


def _session_path(record):
    rev = record.get("current_revision_id")
    name = f"revision-{rev}.rpp" if rev else "session.rpp"
    return _managed(_folder(record["id"]) / name, APP)


def validate_plan(ident, payload):
    project = get_project(ident)
    if not isinstance(payload, dict) or set(payload) - {"summary", "actions", "validated", "requires_review", "limits"}:
        raise ReaperError("An edit plan contains only summary and allowlisted actions.")
    summary = _text(payload.get("summary", ""), 2000, "Plan summary")
    actions = payload.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 100:
        raise ReaperError("An edit plan needs 1 to 100 actions.")
    track_names = {t["name"] for t in project["tracks"]}
    output = []
    for action in actions:
        if not isinstance(action, dict):
            raise ReaperError("Each edit action must be an object.")
        kind = action.get("type")
        keys = {"set_track": {"type", "track", "volume_db", "pan", "mute"},
                "set_tempo": {"type", "bpm"}, "arrange_item": {"type", "track", "item_index", "start_seconds", "length_seconds", "fade_in_seconds", "fade_out_seconds"},
                "add_stock_fx": {"type", "track", "fx", "parameters"}, "eq_band": {"type", "track", "band_type", "band_index", "frequency_hz", "gain_db", "q"},
                "replace_pattern": {"type", "track", "instrument", "steps", "notes", "velocity", "note"}}
        if kind not in keys or set(action) - keys[kind]:
            raise ReaperError("Unsupported edit action. Use track level/pan/mute, tempo, item arrangement, stock FX, EQ or a managed beat pattern.")
        if kind != "set_tempo" and action.get("track") not in track_names:
            raise ReaperError("An edit plan must name an existing project track.")
        a = deepcopy(action)
        if kind == "replace_pattern":
            generated = {f"Beat {i + 1} - {pattern['instrument']}": pattern["instrument"] for i, pattern in enumerate(project["parameters"]["tracks"])}
            if a["track"] not in generated or a.get("instrument") != generated[a["track"]]:
                raise ReaperError("Pattern replacement may only target the matching managed generated-instrument track.")
            pattern = validate_tracks([{k: v for k, v in a.items() if k not in ("type", "track")}])[0]
            a = {"type": kind, "track": a["track"], **pattern}
        elif kind == "set_track":
            if not set(a) & {"volume_db", "pan", "mute"}:
                raise ReaperError("Choose a track level, pan or mute change.")
            for name, low, high in (("volume_db", -60, 12), ("pan", -1, 1)):
                if name in a:
                    _number(a[name], low, high, name)
            if "mute" in a and type(a["mute"]) is not bool:
                raise ReaperError("Track mute must be a boolean.")
        elif kind == "set_tempo":
            _number(a.get("bpm"), 40, 240, "Tempo")
        elif kind == "arrange_item":
            _number(a.get("item_index", 0), 0, 999, "Item index", True)
            _number(a.get("start_seconds"), 0, CONFIG["max_project_seconds"], "Item start")
            _number(a.get("length_seconds"), .01, CONFIG["max_project_seconds"], "Item length")
            if a["start_seconds"] + a["length_seconds"] > CONFIG["max_project_seconds"]:
                raise ReaperError("The arranged item exceeds the project-duration limit.")
            for name in ("fade_in_seconds", "fade_out_seconds"):
                if name in a:
                    _number(a[name], 0, a["length_seconds"], name)
        elif kind == "add_stock_fx":
            if a.get("fx") not in FX:
                raise ReaperError("Choose ReaEQ, ReaComp, ReaVerbate or ReaLimit.")
            params = a.get("parameters", [])
            if not isinstance(params, list) or len(params) > 32:
                raise ReaperError("Choose at most 32 normalized stock-FX parameters.")
            for param in params:
                if not isinstance(param, dict) or set(param) != {"name", "value"}:
                    raise ReaperError("FX parameters contain only an exact native parameter name and normalized value.")
                _text(param["name"], 100, "FX parameter name")
                _number(param["value"], 0, 1, "Normalized FX value")
        elif kind == "eq_band":
            if a.get("band_type") not in EQ_TYPES:
                raise ReaperError("Choose an available EQ band type.")
            _number(a.get("band_index", 0), 0, 7, "EQ band index", True)
            _number(a.get("frequency_hz"), 20, 20000, "EQ frequency")
            _number(a.get("gain_db", 0), -24, 24, "EQ gain")
            _number(a.get("q", 1), .1, 20, "EQ Q")
        output.append(a)
    return {"summary": summary, "actions": output, "validated": True, "requires_review": True,
            "limits": "These actions change the saved session in native REAPER. Unsaved editor changes must be saved first. Audio metrics cannot establish creative quality."}


def _lua(value):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + ''.join('\\%03d' % b for b in value.encode('utf-8')) + '"'
    if isinstance(value, list):
        return "{" + ",".join(_lua(x) for x in value) + "}"
    return "{" + ",".join("[" + _lua(k) + "]=" + _lua(v) for k, v in value.items()) + "}"


def _script(actions, session, output, result_path):
    # All instructions are trusted code; model/user data enter only through _lua.
    return "local actions=" + _lua(actions) + "\nlocal fxnames=" + _lua(FX) + "\nlocal eqtypes=" + _lua(EQ_TYPES) + "\n" + r'''
local function track(name)
  for i=0,reaper.CountTracks(0)-1 do
    local t=reaper.GetTrack(0,i); local _,n=reaper.GetTrackName(t)
    if n==name then return t end
  end
  error("Requested track is absent from saved session")
end
local function stock(t,name)
  local i=reaper.TrackFX_AddByName(t,fxnames[name],false,1)
  if i<0 then error("Requested stock FX is unavailable") end
  return i
end
local ok,err=xpcall(function()
  for _,a in ipairs(actions) do
    local t=a.track and track(a.track) or nil
    if a.type=="set_track" then
      if a.volume_db then reaper.SetMediaTrackInfo_Value(t,"D_VOL",10^(a.volume_db/20)) end
      if a.pan then reaper.SetMediaTrackInfo_Value(t,"D_PAN",a.pan) end
      if a.mute~=nil then reaper.SetMediaTrackInfo_Value(t,"B_MUTE",a.mute and 1 or 0) end
    elseif a.type=="set_tempo" then reaper.SetCurrentBPM(0,a.bpm,true)
    elseif a.type=="arrange_item" then
      local item=reaper.GetTrackMediaItem(t,a.item_index or 0)
      if not item then error("Requested item is absent from saved session") end
      reaper.SetMediaItemInfo_Value(item,"D_POSITION",a.start_seconds)
      reaper.SetMediaItemInfo_Value(item,"D_LENGTH",a.length_seconds)
      if a.fade_in_seconds then reaper.SetMediaItemInfo_Value(item,"D_FADEINLEN",a.fade_in_seconds) end
      if a.fade_out_seconds then reaper.SetMediaItemInfo_Value(item,"D_FADEOUTLEN",a.fade_out_seconds) end
    elseif a.type=="replace_pattern" then
      local item=reaper.GetTrackMediaItem(t,0)
      if not item then error("Managed pattern item is absent") end
      local take=reaper.GetActiveTake(item)
      if not take then error("Managed pattern take is absent") end
      local source=reaper.PCM_Source_CreateFromFile(a._source)
      if not source then error("Revision-owned pattern source is unavailable") end
      reaper.SetMediaItemTake_Source(take,source)
    elseif a.type=="add_stock_fx" then
      local fx=stock(t,a.fx)
      for _,p in ipairs(a.parameters or {}) do
        local found=false
        for i=0,reaper.TrackFX_GetNumParams(t,fx)-1 do
          local _,name=reaper.TrackFX_GetParamName(t,fx,i)
          if name==p.name then
            assert(reaper.TrackFX_SetParamNormalized(t,fx,i,p.value),"Stock FX parameter write failed")
            found=true; break
          end
        end
        if not found then error("Unknown native stock FX parameter: "..p.name) end
      end
    elseif a.type=="eq_band" then
      local fx=stock(t,"ReaEQ"); local bt=eqtypes[a.band_type]; local bi=a.band_index or 0
      assert(reaper.TrackFX_SetEQParam(t,fx,bt,bi,0,a.frequency_hz,false),"EQ band type/index is unavailable")
      assert(reaper.TrackFX_SetEQParam(t,fx,bt,bi,1,a.gain_db or 0,false),"EQ gain write failed")
      assert(reaper.TrackFX_SetEQParam(t,fx,bt,bi,2,a.q or 1,false),"EQ Q write failed")
      reaper.TrackFX_SetEQBandEnabled(t,fx,bt,bi,true)
    end
  end
  reaper.UpdateArrange()
''' + f'''
  reaper.GetSetProjectInfo(0,"RENDER_BOUNDSFLAG",1,true)
  reaper.GetSetProjectInfo(0,"RENDER_SETTINGS",0,true)
  reaper.GetSetProjectInfo(0,"RENDER_SRATE",{CONFIG['render_sample_rate']},true)
  reaper.GetSetProjectInfo(0,"RENDER_CHANNELS",2,true)
  reaper.GetSetProjectInfo_String(0,"RENDER_FILE",{_lua(str(output.parent))},true)
  reaper.GetSetProjectInfo_String(0,"RENDER_PATTERN",{_lua(output.stem)},true)
  reaper.GetSetProjectInfo_String(0,"RENDER_FORMAT","ZXZhdxgAAA==",true)
  reaper.Main_SaveProject(0,false)
  local function q(s)
    local out=string.char(34)
    for i=1,#s do
      local b=s:byte(i)
      if b==34 then out=out..string.char(92,34)
      elseif b==92 then out=out..string.char(92,92)
      elseif b<32 then out=out..string.char(92).."u"..string.format("%04x",b)
      else out=out..string.char(b) end
    end
    return out..string.char(34)
  end
  local rows={{}}
  for i=0,reaper.CountTracks(0)-1 do
    local t=reaper.GetTrack(0,i); local _,name=reaper.GetTrackName(t)
    local volume=reaper.GetMediaTrackInfo_Value(t,"D_VOL")
    local fxrows={{}}
    for fx=0,reaper.TrackFX_GetCount(t)-1 do
      local _,fxname=reaper.TrackFX_GetFXName(t,fx); local params={{}}
      for pi=0,reaper.TrackFX_GetNumParams(t,fx)-1 do
        local _,pn=reaper.TrackFX_GetParamName(t,fx,pi)
        table.insert(params,'{{"name":'..q(pn)..',"value":'..tostring(reaper.TrackFX_GetParamNormalized(t,fx,pi))..'}}')
      end
      table.insert(fxrows,'{{"name":'..q(fxname)..',"parameters":['..table.concat(params,',')..']}}')
    end
    table.insert(rows,'{{"name":'..q(name)..',"volume_db":'..tostring(volume>0 and 20*math.log(volume)/math.log(10) or -150)..',"pan":'..tostring(reaper.GetMediaTrackInfo_Value(t,"D_PAN"))..',"mute":'..tostring(reaper.GetMediaTrackInfo_Value(t,"B_MUTE")>0)..',"fx":['..table.concat(fxrows,',')..']}}')
  end
  local inventory=assert(io.open({_lua(str(result_path.with_suffix('.json')))},"wb"))
  inventory:write('{{"bpm":'..tostring(reaper.Master_GetTempo())..',"tracks":['..table.concat(rows,',')..']}}'); inventory:close()
end,debug.traceback)
local f=assert(io.open({_lua(str(result_path))},"wb"))
f:write(ok and "OK" or ("ERROR: "..tostring(err))); f:close()
'''


def _native(arguments, folder, timeout, sentinel=None):
    # A separate INI in the installed resource directory preserves stock plugins
    # and the user's existing license without reading or copying license files.
    resource = Path(CONFIG["reaper_resource_dir"]) if CONFIG.get("reaper_resource_dir") else Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "REAPER"
    if not resource.is_dir():
        raise ReaperError("The installed REAPER resource directory is unavailable.", 503)
    config = resource / ("resonance-native-" + str(uuid.uuid4()) + ".ini")
    config.write_text("[REAPER]\nshowpeaks=0\nnewprojdo=0\naudio_driver=3\nwasapi_mode=0\nwasapi_srate=48000\nwasapi_bps=24\nwasapi_blocksize=512\n", encoding="utf-8")
    options = {}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options = {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}
    with (folder / "native.log").open("ab") as log:
        proc = subprocess.Popen([CONFIG["reaper_executable"], "-newinst", "-nosplash", "-noactivate", "-splashlog", str(folder / "startup.log"), "-cfgfile", str(config), *arguments], cwd=folder, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        with _lock:
            _children.add(proc)
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None and time.monotonic() < deadline:
                with _lock:
                    if folder.name in _cancelled:
                        raise ReaperError("The owned native REAPER job was cancelled.", 409)
                if sentinel and sentinel.is_file():
                    break
                time.sleep(.1)
            if sentinel:
                if not sentinel.is_file():
                    raise ReaperError("Native REAPER edit did not finish; check the retained native log or any license/audio dialog.", 503)
                result = sentinel.read_text(encoding="utf-8")
                if result != "OK":
                    raise ReaperError("Native REAPER rejected the requested edit. " + result[:400], 422)
            elif proc.poll() is None:
                raise ReaperError("Native REAPER render timed out; its source session is preserved.", 503)
            elif proc.returncode != 0:
                raise ReaperError("Native REAPER render failed; inspect its retained log.", 503)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            with _lock:
                _children.discard(proc)
            config.unlink(missing_ok=True)
            config.with_name(config.stem + "-wndpos.ini").unlink(missing_ok=True)


def _qc(path):
    probe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not probe or not ffmpeg:
        raise ReaperError("FFmpeg/ffprobe are required to verify a native render.", 503)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    raw = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)], capture_output=True, timeout=30, check=True, **options)
    info = json.loads(raw.stdout)
    duration = float(info["format"]["duration"])
    if not .01 < duration <= CONFIG["max_project_seconds"] + 5:
        raise ReaperError("Native render duration exceeded the project bounds.", 422)
    # PCM24 output is decoded for measured peaks/RMS/clipping without changing it.
    pcm = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "pipe:1"], capture_output=True, timeout=60, check=True, **options).stdout
    samples = array("f")
    samples.frombytes(pcm)
    peak = max((abs(x) for x in samples), default=0)
    rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))
    stream = info["streams"][0]
    return {"duration_seconds": duration, "codec": stream["codec_name"], "sample_rate": int(stream["sample_rate"]), "channels": stream["channels"],
            "peak": peak, "rms": rms, "clipped_samples": sum(abs(x) >= .999 for x in samples), "non_silent": rms > .00001, "measurement_channels": "all original decoded channels",
            "review_required": True, "note": "Technical measurements only; listen for musical fit, vocal bleed, timing and artifacts."}


def start_revision(ident, payload=None, edit=False):
    payload = payload or {}
    if not isinstance(payload, dict) or set(payload) - ({"plan", "render"} if edit else set()) or ("render" in payload and type(payload["render"]) is not bool):
        raise ReaperError("Use a validated plan for editing, or an empty export request.")
    plan = validate_plan(ident, payload.get("plan", {})) if edit else {"summary": "Export saved REAPER session", "actions": []}
    if not Path(CONFIG["reaper_executable"]).is_file():
        raise ReaperError("REAPER is not installed.", 503)
    with _lock:
        if not _enabled:
            raise ReaperError("The music business is stopped. Start it before editing or exporting.", 409)
        if ident in _active:
            raise ReaperError("This project already has a native edit/render running.", 409)
        project = _load(ident)
        revision_id = str(uuid.uuid4())
        revision = {"id": revision_id, "created_at": _now(), "status": "queued", "plan": plan, "message": "Queued for native REAPER editing and export."}
        project["revisions"].append(revision)
        _save(_folder(ident) / "project.json", project)
        _active.add(ident)
        _cancelled.discard(ident)
        thread = threading.Thread(target=_revision_worker, args=(ident, revision_id, deepcopy(project), plan, payload.get("render", True)), daemon=True)
        thread.start()
        return deepcopy(project)


def _revision_worker(ident, revision_id, project, plan, render):
    folder = _folder(ident)
    snapshot = folder / f"revision-{revision_id}.rpp"
    output = folder / f"revision-{revision_id}.wav"
    result = folder / f"native-{revision_id}.txt"
    script = folder / f"edit-{revision_id}.lua"
    try:
        _update(ident, revision_id, status="editing", message="Applying the reviewed allowlisted plan in native REAPER.")
        shutil.copyfile(_session_path(project), snapshot)
        actions = deepcopy(plan["actions"])
        pattern_parameters = deepcopy(project["parameters"])
        for index, action in enumerate(actions):
            if action["type"] == "set_tempo":
                pattern_parameters["bpm"] = action["bpm"]
            if action["type"] == "replace_pattern":
                pattern = {k: v for k, v in action.items() if k not in ("type", "track")}
                path = _write_pattern(folder, index, pattern, pattern_parameters, project["duration_seconds"], prefix=f"revision-{revision_id}-pattern-{index}-{action['instrument']}")
                action["_source"] = str(path)
        script.write_text(_script(actions, snapshot, output, result), encoding="utf-8")
        _native([str(snapshot), str(script)], folder, CONFIG["native_edit_timeout_seconds"], result)
        if render:
            _update(ident, revision_id, status="rendering", message="Rendering the saved native REAPER session.")
            _native(["-renderproject", str(snapshot)], folder, CONFIG["render_timeout_seconds"])
            if not output.is_file() or output.stat().st_size < 44:
                raise ReaperError("Native REAPER produced no verified WAV. Its saved session remains available.", 503)
            qc = _qc(output)
        else:
            qc = None
        with _lock:
            if ident in _cancelled:
                raise ReaperError("The owned native REAPER job was cancelled.", 409)
            current = _load(ident)
            current["current_revision_id"] = revision_id
            inventory_path = result.with_suffix(".json")
            if inventory_path.is_file():
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                current["tracks"] = inventory["tracks"]
                current["parameters"]["bpm"] = inventory["bpm"]
            _save(folder / "project.json", current)
        _update(ident, revision_id, status="completed", message="Native revision saved; audition before release.", qc=qc,
                audio_url=f"/reaper/media/{ident}/{revision_id}" if render else None,
                download_url=f"/reaper/download/{ident}/{revision_id}" if render else None)
        _save(APP / "reaper/native-health.json", {"status": "verified", "checked_at": _now(), "message": "A native REAPER session edit completed."})
    except Exception as error:
        message = str(error) if isinstance(error, ReaperError) else "Native REAPER revision failed. Check this project's retained logs; the previous session is preserved."
        with _lock:
            cancelled = ident in _cancelled
        _update(ident, revision_id, status="cancelled" if cancelled else "failed", message="The owned native REAPER job was cancelled; the previous session is preserved." if cancelled else message)
        if isinstance(error, ReaperError) and error.status == 503:
            _save(APP / "reaper/native-health.json", {"status": "blocked", "checked_at": _now(), "message": message})
        print("REAPER revision failure:", type(error).__name__, str(error)[:400], flush=True)
    finally:
        with _lock:
            _active.discard(ident)


def media_path(ident, revision_id):
    if not isinstance(revision_id, str) or not UUID.fullmatch(revision_id):
        raise ReaperError("That exported revision was not found.", 404)
    project = get_project(ident)
    revision = next((r for r in project["revisions"] if r["id"] == revision_id and r["status"] == "completed" and r.get("audio_url")), None)
    path = _managed(_folder(ident) / f"revision-{revision_id}.wav", APP)
    if not revision or not path.is_file():
        raise ReaperError("That completed exported revision was not found.", 404)
    return path


def shutdown():
    _listen_cancel.set()
    with _lock:
        children = list(_children)
        _cancelled.update(_active)
    for child in children:
        if child.poll() is None:
            child.terminate()


def set_enabled(enabled):
    global _enabled
    with _lock:
        _enabled = enabled
    if not enabled:
        shutdown()


def cancel_project(ident):
    with _lock:
        project = _load(ident)
        if ident in _active:
            _cancelled.add(ident)
            for revision in project["revisions"]:
                if revision["status"] in ("queued", "editing", "rendering"):
                    revision["message"] = "Cancelling the owned native REAPER worker."
            _save(_folder(ident) / "project.json", project)
        return project


def any_gpu_busy():
    with _lock:
        return _listening is not None


def get_listening(ident):
    if not isinstance(ident, str) or not UUID.fullmatch(ident):
        raise ReaperError("That listening job was not found.", 404)
    path = _managed(APP / "reaper/listening" / (ident + ".json"), APP)
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ReaperError("That listening job was not found.", 404)
    with _lock:
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] in ("queued", "running") and _listening != ident:
            job.update(status="failed", message="The local listening job was interrupted.")
            _save(path, job)
    return job


def listener_song_ids():
    result = set()
    folder = APP / "reaper/listening"
    if folder.is_dir():
        for file in folder.glob("*.json"):
            if UUID.fullmatch(file.stem):
                try:
                    ident = get_listening(file.stem).get("studio_song_id")
                    if ident:
                        result.add(ident)
                except (ReaperError, OSError, ValueError):
                    continue
    return result


def start_listening(project_id, revision_id):
    global _listening
    audio = media_path(project_id, revision_id)
    import rap_assistant
    try:
        rap_assistant._require_managed()
    except (OSError, RuntimeError, ValueError):
        raise ReaperError("The installed managed local listener/writer is unavailable. Start YuE2 Studio and retry; no listening has occurred.", 503) from None
    with _lock:
        if _listening is not None:
            raise ReaperError("A rendered-revision listening job is already running.", 409)
        ident = str(uuid.uuid4())
        job = {"id": ident, "project_id": project_id, "revision_id": revision_id, "status": "queued", "created_at": _now(), "approved": False,
               "message": "Queued for the installed local MOSS-Music listener. Observations need review."}
        _save(APP / "reaper/listening" / (ident + ".json"), job)
        _listen_cancel.clear()
        _listening = ident
        threading.Thread(target=_listen_worker, args=(deepcopy(job), audio), daemon=True).start()
        return job


def cancel_listening(ident):
    job = get_listening(ident)
    with _lock:
        if _listening == ident:
            _listen_cancel.set()
            job.update(status="cancelled", approved=False, message="Cancellation requested; no observation will be accepted.")
            _save(APP / "reaper/listening" / (ident + ".json"), job)
    if job["status"] == "cancelled":
        import rap_assistant
        try:
            rap_assistant._rpc("assistant_stop", timeout=5)
        except (OSError, ValueError, RuntimeError):
            print("REAPER listener cancellation: native assistant did not confirm unloading", flush=True)
    return job


def _listen_worker(job, audio):
    global _listening
    import rap_assistant
    path = APP / "reaper/listening" / (job["id"] + ".json")
    try:
        job.update(status="running", message="The local MOSS-Music model is analyzing the actual native-rendered revision.")
        _save(path, job)
        rap_assistant._require_managed()
        if _listen_cancel.is_set():
            raise InterruptedError()
        imported = rap_assistant._rpc("library_import_audio", {"path": str(audio), "title": "Resonance revision observation " + job["revision_id"]}, timeout=90)
        song_id = imported.get("id") or imported.get("song_id") or (imported.get("song") or {}).get("id")
        if not isinstance(song_id, str) or not UUID.fullmatch(song_id):
            raise RuntimeError("Native listener import produced no owned song identifier")
        job["studio_song_id"] = song_id
        _save(path, job)
        if _listen_cancel.is_set():
            raise InterruptedError()
        heard = rap_assistant._rpc("library_song_describe_style", {"song_id": song_id}, timeout=1200)
        if _listen_cancel.is_set():
            raise InterruptedError()
        song = rap_assistant._rpc("library_song_get", {"song_id": song_id})
        caption = song.get("caption") or heard.get("style") or heard.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            raise RuntimeError("The local listener returned no observation")
        job.update(status="completed", listener_observation=caption[:4000], approved=False, completed_at=_now(),
                   message="Local model observation of the actual revision; musical quality and correctness remain unapproved.")
    except Exception as error:
        cancelled = _listen_cancel.is_set()
        job.update(status="cancelled" if cancelled else "failed", message="The local revision listener was cancelled." if cancelled else "The local revision listener failed. No listening result or quality approval is available.")
        if not cancelled:
            print("REAPER listener failure:", type(error).__name__, str(error)[:300], flush=True)
    finally:
        try:
            rap_assistant._rpc("assistant_stop")
        except (OSError, ValueError, RuntimeError):
            print("REAPER listener: local assistant did not confirm unloading", flush=True)
        with _lock:
            if _listen_cancel.is_set():
                job.update(status="cancelled", approved=False, message="The local revision listener was cancelled.")
                job.pop("listener_observation", None)
            _save(path, job)
            _listening = None
