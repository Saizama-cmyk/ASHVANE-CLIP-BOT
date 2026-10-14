"""Bounded evidence ledger and provenance-linked training examples, never weight claims."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path

from .config import atomic_write

HEX_RADIX = 16
SECRET_PATTERN = re.compile(r'''(?i)(?:bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]+|(?:access_token|refresh_token|api_key|password)["']?\s*[:=]\s*["']?[^\s,"'}]+)''')
SECRET_KEYS = {"access_token", "refresh_token", "api_key", "password", "authorization", "secret"}


def clean(value, limit):
    return SECRET_PATTERN.sub("[redacted]", str(value))[:limit]


def scrub(value, limit):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if str(key).casefold() in SECRET_KEYS else scrub(item, limit)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item, limit) for item in value]
    if isinstance(value, str):
        return clean(value, limit)
    return value


class SupervisorMemory:
    def __init__(self, settings, root: Path):
        self.settings, self.root = settings, root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "ledger.json"
        self.data = {"version": 1, "events": [], "jobs": [], "sources": [], "examples": [],
                     "goals": [], "learning": [], "agents": []}
        if self.path.exists():
            if self.path.stat().st_size > settings.supervisor.store_max_bytes:
                raise ValueError("Supervisor ledger exceeds its storage budget")
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            for key in self.data:
                if key == "version":
                    continue
                if not isinstance(saved.get(key, []), list):
                    raise ValueError("Invalid supervisor ledger")
                self.data[key] = saved.get(key, [])
        for job in self.data["jobs"]:
            if job.get("status") in {"running", "evaluating", "applying"}:
                job.update(status="interrupted", error="Application stopped before completion")

    def save(self):
        cfg = self.settings.supervisor
        for key in ("events", "jobs", "sources", "goals", "learning"):
            self.data[key] = self.data[key][-cfg.max_history:]
        self.data["examples"] = self.data["examples"][-cfg.dataset_limit:]
        self.data["agents"] = self.data["agents"][:cfg.max_agents]
        raw = json.dumps(scrub(self.data, cfg.max_text_chars), ensure_ascii=False)
        if len(raw.encode()) > cfg.store_max_bytes:
            raise ValueError("Supervisor evidence exceeds its storage budget")
        atomic_write(self.path, raw)

    def event(self, role, kind, summary, **extra):
        row = {"id": hashlib.sha256(f"{time.time_ns()}:{role}".encode()).hexdigest(),
               "at": time.time(), "role": role, "kind": kind,
               "summary": clean(summary, self.settings.supervisor.max_text_chars), **scrub(extra, self.settings.supervisor.max_text_chars)}
        self.data["events"].append(row)
        self.save()
        return row

    def example(self, instruction, response, provenance, *, verified=False, rights="unknown"):
        cfg = self.settings.supervisor
        instruction, response = clean(instruction, cfg.max_text_chars), clean(response, cfg.max_text_chars)
        key = hashlib.sha256((instruction + "\n" + response).encode()).hexdigest()
        if any(row["id"] == key for row in self.data["examples"]):
            return next(row for row in self.data["examples"] if row["id"] == key)
        eligible = verified is True and bool(provenance) and rights in {"owner_code", "original_synthetic", "permitted_public"}
        row = {"id": key, "created_at": time.time(), "instruction": instruction, "response": response,
               "provenance": scrub(copy.deepcopy(provenance), cfg.max_text_chars), "verified": verified is True, "rights": rights,
               "eligible": eligible, "split": "evaluation" if int(key, HEX_RADIX) % 100 < cfg.dataset_eval_percent else "training"}
        self.data["examples"].append(row)
        self.save()
        return row

    def export(self, split):
        if split not in {"training", "evaluation"}:
            raise ValueError("Choose training or evaluation")
        return "\n".join(json.dumps({"messages": [{"role": "user", "content": row["instruction"]},
                                                        {"role": "assistant", "content": row["response"]}],
                                     "provenance": row["provenance"], "id": row["id"]}, ensure_ascii=False)
                         for row in self.data["examples"] if row["eligible"] and row["split"] == split)
