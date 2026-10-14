"""Bounded runtime evidence. Log contents and account/media identifiers never enter Core."""
from __future__ import annotations

from collections import Counter, deque
import logging
import math
import time


# Source identifiers, not an allowlist of private data or user-defined logger names.
SOURCES = frozenset("account_profiles auth assembler autostart checklist business_runtime app capture analytics chat clipability clip_import copywriter config detector discovery editor dependencies growth media hardware ollama_setup server desktop pets music_api pipeline review remote_check research scheduler secure storage social_api story_api stories oauth story_comfy story_voice studio story_visual_service story_render story_publishing supervisor_extensions supervisor_bootstrap supervisor supervisor_sandbox transcribe sweeper trends updater util main vision publishers agent.models agent.mcp agent.watch agent.skills agent.tools".split())
EXCEPTIONS = frozenset("OSError FileNotFoundError PermissionError TimeoutError ConnectionError RuntimeError ValueError TypeError KeyError IndexError HTTPStatusError ReadTimeout ConnectTimeout ConnectError CmdTimeout RenderError AssembleError AIUnavailable".split())
PHASES = frozenset("queued assemble assemble_wait qc transcribe transcribe_wait transcribe_including_wait clipability clipability_wait copywriter copywriter_wait edit edit_wait review review_wait final_review".split())


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


class RuntimeObservations(logging.Handler):
    def __init__(self, settings):
        super().__init__(logging.WARNING)
        self.settings = settings
        self.events = deque(maxlen=settings.supervisor.diagnostic_event_limit)
        self.dropped = 0
        self.started_at = None
        self.attached = False

    def start(self):
        if not self.attached:
            logging.getLogger("clipbot").addHandler(self)
            self.attached = True
            self.started_at = time.time()

    def stop(self):
        logging.getLogger("clipbot").removeHandler(self)
        self.attached = False

    def reconfigure(self, settings):
        with self.lock:
            self.settings = settings
            limit = settings.supervisor.diagnostic_event_limit
            self.dropped += max(0, len(self.events) - limit)
            self.events = deque(self.events, maxlen=limit)

    def emit(self, record):
        if not self.attached or not self.settings.supervisor.enabled or record.levelno < logging.WARNING:
            return
        source = record.name.removeprefix("clipbot.")
        if source not in SOURCES or type(record.lineno) is not int or record.lineno <= 0:
            return
        exception = ""
        if record.exc_info and isinstance(record.exc_info, tuple) and record.exc_info[0]:
            name = getattr(record.exc_info[0], "__name__", "")
            exception = name if name in EXCEPTIONS else "Exception"
        # Never call getMessage(), format(), str(exc), or inspect the traceback/locals.
        severity = "error" if record.levelno >= logging.ERROR else "warning"
        if len(self.events) == self.events.maxlen:
            self.dropped += 1
        self.events.append((time.time(), source, record.lineno, severity, exception))

    def snapshot(self, pipeline, business_busy):
        now = time.time()
        cfg = self.settings.supervisor
        cutoff = now - cfg.diagnostic_window_min * 60
        with self.lock:
            events = [row for row in self.events if row[0] >= cutoff]
            dropped = self.dropped
        groups = {}
        for at, source, line, severity, exception in events:
            key = (source, line, severity, exception)
            group = groups.setdefault(key, {"source": source, "line": line, "severity": severity,
                                           "exception": exception, "count": 0, "first_at": at, "last_at": at})
            group["count"] += 1
            group["last_at"] = at
        faults = sorted(groups.values(), key=lambda row: (-row["count"], -row["last_at"]))[:cfg.source_limit]
        # The engine already owns these in-memory measurements. Do not call pipeline.snapshot,
        # read log files, enumerate capture storage, or copy identifiers/transcripts/paths.
        active = [row for row in getattr(pipeline, "_latency", {}).values() if "finished_at" not in row]
        phase_counts = Counter(row.get("phase") if row.get("phase") in PHASES else "other" for row in active)
        ages = [max(0, now - value) for row in active if (value := number(row.get("created_at"))) is not None]
        waits = [max(0, now - value) for row in active
                 if str(row.get("phase", "")).endswith("_wait")
                 and (value := number(row.get("phase_started_at"))) is not None]
        gpu = getattr(pipeline, "gpu", None)
        resources = {key: number(gpu.get(key)) if isinstance(gpu, dict) else None
                     for key in ("util", "mem_used", "mem_total", "temp")}
        slots = {}
        for name, attr in (("ai", "_ai_limit"), ("assembly", "_assemble_limit"), ("edit", "_edit_limit")):
            limiter = getattr(pipeline, attr, None)
            slots[name] = {key: number(getattr(limiter, key, None)) for key in ("active", "limit")}
        return {"collecting": self.attached, "observed_at": now, "started_at": self.started_at,
                "window_min": cfg.diagnostic_window_min, "faults": faults, "fault_events": len(events),
                "discarded_events": dropped, "bounded_sample": dropped > 0,
                "business_generation_active": bool(business_busy),
                "inference_deferred": cfg.idle_only and bool(business_busy),
                "queue": {"active": len(active), "phases": dict(phase_counts),
                          "oldest_age_s": round(max(ages), 2) if ages else None,
                          "longest_wait_s": round(max(waits), 2) if waits else None},
                "resources": {"gpu": resources, "slots": slots}}
