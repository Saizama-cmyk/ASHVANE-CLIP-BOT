"""Docker-only evaluation of source snapshots, without production data or tools.

The evaluator owns its containers and staging trees. A missing engine/image is a
setup condition, never permission to execute a candidate on the host.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path

from .util import spawn, terminate

logger = logging.getLogger("clipbot.supervisor_sandbox")
POLICY = "1"
LABEL = "org.ashvane.supervisor.policy"
RESULT_PREFIX = "ASHVANE_SANDBOX_RESULT="
SOURCE_DIRS = frozenset({"clipbot", "tests", "scripts", "art", "assets", "docs", "phone",
                         "integrations", "installer", "tiktok-site"})
SOURCE_SUFFIXES = frozenset({".py", ".js", ".cjs", ".mjs", ".json", ".html", ".css", ".md",
                             ".txt", ".ini", ".toml", ".yaml", ".yml", ".svg", ".iss", ".patch"})
ROOT_FILES = frozenset({"requirements.txt", "pytest.ini", "pyproject.toml", "setup.cfg",
                       "conftest.py", "CLAUDE.md", "AGENTS.md", "LICENSE"})
BLOCKED_PARTS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"})
BLOCKED_NAMES = frozenset({"settings.json", "tokens.json", "tokens-stories.json", "mcp.json",
                           "profiles.json", "sessions.json", ".env"})


def _linked(path: Path) -> bool:
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _plain_dir(path: Path) -> Path:
    """Reject links on every path component before resolving it."""
    absolute = path.absolute()
    for part in (absolute, *absolute.parents):
        try:
            linked = _linked(part)
        except FileNotFoundError:
            continue
        if linked:
            raise ValueError("Snapshot/report paths cannot contain links or junctions")
    return absolute.resolve()


def _copy_snapshot(source: Path, dest: Path, limit: int) -> dict:
    """Copy source formats only; never follow links, read unknown trees or copy data."""
    source = _plain_dir(source)
    if not source.is_dir():
        raise ValueError("Snapshot is not a directory")
    total = 0
    digest = hashlib.sha256()
    for folder, dirs, names in os.walk(source, followlinks=False):
        current = Path(folder)
        kept = []
        for name in sorted(dirs):
            item = current / name
            if _linked(item):
                raise ValueError("Snapshot contains a linked directory")
            if name in BLOCKED_PARTS:
                continue
            if current == source and name not in SOURCE_DIRS:
                continue
            kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            item = current / name
            if _linked(item):
                raise ValueError("Snapshot contains a linked file")
            if not stat.S_ISREG(item.stat().st_mode) or item.stat().st_nlink > 1:
                raise ValueError("Snapshots require regular files without hard links")
            relative = item.relative_to(source)
            if name.casefold() in BLOCKED_NAMES or name.startswith(".env"):
                continue
            if current == source and name not in ROOT_FILES:
                continue
            if current != source and item.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            total += item.stat().st_size
            if total > limit:
                raise ValueError("Snapshot exceeds configured source byte limit")
            data = item.read_bytes()
            total += max(0, len(data) - item.stat().st_size)
            if total > limit:
                raise ValueError("Snapshot exceeds configured source byte limit")
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            digest.update(relative.as_posix().encode())
            digest.update(data)
    return {"bytes": total, "sha256": digest.hexdigest()}


def _protect_tests(candidate: Path, baseline: Path) -> None:
    """Compose the read-only evaluation mount before any candidate is executed."""
    tests = candidate / "tests"
    extra = []
    if tests.is_dir():
        for path in tests.rglob("test_*.py"):
            relative = path.relative_to(tests)
            if not (baseline / "tests" / relative).exists():
                extra.append((relative, path.read_bytes()))
        shutil.rmtree(tests)
    shutil.copytree(baseline / "tests", tests)
    additions = candidate / "_additional_tests"
    if additions.exists():
        shutil.rmtree(additions)
    for relative, content in extra:
        target = additions / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if extra:
        for original in (baseline / "tests").rglob("conftest.py"):
            target = additions / original.relative_to(baseline / "tests")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    for name in ("pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg"):
        target = candidate / name
        if target.exists():
            target.unlink()
        original = baseline / name
        if original.is_file():
            shutil.copyfile(original, target)
    for name in ("sitecustomize.py", "usercustomize.py", "pytest.py"):
        target = candidate / name
        if target.exists():
            target.unlink()


async def _finish_copy(source: Path, dest: Path, limit: int) -> dict:
    task = asyncio.create_task(asyncio.to_thread(_copy_snapshot, source, dest, limit))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Python threads cannot be killed. Finish the bounded copy before deleting staging.
        await task
        raise


class Sandbox:
    def __init__(self, settings, root: Path):
        self.settings, self.root = settings, Path(root)
        self._owned: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    @property
    def cfg(self):
        return self.settings.supervisor

    async def _command(self, args: list[str]) -> tuple[int, str]:
        cfg = self.cfg
        # WSL receives only a fixed CLI argument vector, never a shell/model command.
        docker = ["docker", "--host", "unix:///var/run/docker.sock", *args]
        command = (["wsl.exe", "-d", cfg.docker_distribution, "--", *docker]
                   if os.name == "nt" else docker)
        process = await spawn(*command, stdin=asyncio.subprocess.DEVNULL,
                              stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        chunks = bytearray()

        async def read():
            while data := await process.stdout.read(min(cfg.max_command_bytes, 1024)):
                chunks.extend(data)
                if len(chunks) > cfg.max_command_bytes:
                    raise ValueError("Sandbox command output exceeded configured limit")
            await process.wait()

        try:
            await asyncio.wait_for(read(), cfg.sandbox_timeout_s)
            return process.returncode, chunks.decode("utf-8", errors="replace")
        finally:
            await terminate(process, cfg.sandbox_timeout_s)

    async def readiness(self) -> dict:
        if self._closed:
            return {"ready": False, "status": "closed"}
        try:
            code, version = await self._command(["info", "--format", "{{.ServerVersion}}"])
            if code:
                return {"ready": False, "status": "setup_needed", "error": "Docker engine is unavailable"}
            code, label = await self._command(["image", "inspect", "--format",
                                               '{{index .Config.Labels "' + LABEL + '"}}', self.cfg.sandbox_image])
            if code or label.strip() != POLICY:
                return {"ready": False, "status": "setup_needed", "error": "Trusted evaluation image is missing or has an incompatible policy"}
            return {"ready": True, "status": "ready", "engine": version.strip(), "image": self.cfg.sandbox_image}
        except (OSError, ValueError, TimeoutError) as exc:
            logger.warning("sandbox readiness failed: %s", type(exc).__name__)
            return {"ready": False, "status": "setup_needed", "error": str(exc) or type(exc).__name__}

    def _mount_path(self, path: Path) -> str:
        resolved = path.resolve()
        if os.name == "nt":
            if not re.fullmatch(r"[A-Za-z]:", resolved.drive):
                raise ValueError("Sandbox snapshots need a local Windows drive")
            value = "/mnt/" + resolved.drive[0].lower() + resolved.as_posix()[len(resolved.drive):]
        else:
            value = str(resolved)
        if any(char in value for char in (",", "\n", "\r")):
            raise ValueError("Unsupported mount path")
        return value

    async def _remove(self, name: str) -> None:
        if name not in self._owned:
            return
        code, _ = await self._command(["rm", "--force", name])
        if code:
            logger.error("could not remove owned evaluation container %s", name)
        else:
            self._owned.discard(name)

    async def evaluate(self, candidate: Path, baseline: Path, report_folder: Path) -> dict:
        if self._closed:
            return {"status": "closed", "passed": False}
        task = asyncio.current_task()
        self._tasks.add(task)
        name = "ashvane-eval-" + uuid.uuid4().hex
        stage = None
        report_target = None
        result = {"status": "failed", "passed": False, "tests": 0, "failures": 0,
                  "skipped": 0, "error": "", "evidence": {}}
        try:
            candidate, baseline, report = map(_plain_dir, (Path(candidate), Path(baseline), Path(report_folder)))
            if candidate == baseline or not (candidate.parent == baseline.parent == report.parent):
                raise ValueError("Candidate, baseline and reports must be separate siblings in one job directory")
            if report == candidate or report == baseline or candidate in report.parents or baseline in report.parents:
                raise ValueError("Reports must be separate from source snapshots")
            report.mkdir(parents=True, exist_ok=True)
            if any(report.iterdir()):
                raise ValueError("Use an empty report directory")
            report_target = report / "result.json"
            ready = await self.readiness()
            if not ready["ready"]:
                result.update(status=ready["status"], error=ready.get("error", "Isolation is unavailable"))
            else:
                stage = Path(tempfile.mkdtemp(prefix="ashvane-eval-", dir=report.parent))
                source, original = stage / "candidate", stage / "baseline"
                source.mkdir()
                original.mkdir()
                result["evidence"] = {"candidate": await _finish_copy(candidate, source, self.cfg.max_source_bytes),
                                      "baseline": await _finish_copy(baseline, original, self.cfg.max_source_bytes)}
                if not (original / "tests").is_dir() or not (original / "pytest.ini").is_file():
                    raise ValueError("Baseline tests and pytest.ini are required")
                _protect_tests(source, original)
                cfg = self.cfg
                args = ["run", "--pull", "never", "--name", name, "--label", "org.ashvane.supervisor.owned=" + name,
                        "--network", "none", "--ipc", "none", "--user", "65534:65534", "--cap-drop", "ALL",
                        "--security-opt", "no-new-privileges", "--read-only", "--pids-limit", str(cfg.sandbox_pids),
                        "--memory", str(cfg.sandbox_memory_mb) + "m", "--memory-swap", str(cfg.sandbox_memory_mb) + "m",
                        "--cpus", str(cfg.sandbox_cpus), "--tmpfs", "/tmp:rw,nosuid,nodev,size=" + str(cfg.sandbox_memory_mb) + "m",
                        "--mount", "type=bind,src=" + self._mount_path(source) + ",dst=/workspace,readonly",
                        "--mount", "type=bind,src=" + self._mount_path(original) + ",dst=/baseline,readonly",
                        "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--env", "PYTHONDONTWRITEBYTECODE=1",
                        "--entrypoint", "/usr/local/bin/python", cfg.sandbox_image,
                        "-I", "/opt/ashvane/runner.py", str(cfg.max_command_bytes), str(cfg.sandbox_cpus)]
                self._owned.add(name)
                code, output = await self._command(args)
                lines = [line[len(RESULT_PREFIX):] for line in output.splitlines() if line.startswith(RESULT_PREFIX)]
                if len(lines) != 1:
                    raise ValueError("Evaluation did not produce one trusted result")
                measured = json.loads(lines[0])
                if not isinstance(measured, dict) or measured.get("policy") != POLICY:
                    raise ValueError("Invalid evaluation result")
                counts = {key: measured.get(key) for key in ("tests", "failures", "errors", "skipped")}
                if any(type(value) is not int or value < 0 for value in counts.values()):
                    raise ValueError("Invalid evaluation counts")
                phases = measured.get("phases")
                if (not isinstance(phases, list) or any(not isinstance(phase, dict) for phase in phases)
                        or [phase.get("name") for phase in phases] not in (["baseline"], ["baseline", "additional"])):
                    raise ValueError("Invalid evaluation phase sequence")
                verified_phases = []
                for phase in phases:
                    phase_counts = {key: phase.get(key) for key in counts}
                    if (type(phase.get("exit_code")) is not int
                            or any(type(value) is not int or value < 0 for value in phase_counts.values())
                            or phase_counts["skipped"] > phase_counts["tests"]):
                        raise ValueError("Invalid evaluation phase counts or exit code")
                    verified_phases.append({"name": phase["name"], "exit_code": phase["exit_code"], **phase_counts})
                if any(sum(phase[key] for phase in verified_phases) != value for key, value in counts.items()):
                    raise ValueError("Evaluation phase totals disagree with the result")
                passed = (code == 0 and type(measured.get("exit_code")) is int and measured["exit_code"] == 0
                          and counts["tests"] > counts["skipped"] and counts["failures"] == counts["errors"] == 0
                          and not measured.get("error")
                          and all(phase["exit_code"] == 0 and phase["tests"] > phase["skipped"]
                                  and phase["failures"] == phase["errors"] == 0 for phase in verified_phases))
                result.update(status="passed" if passed else "failed", passed=passed, **counts,
                              error=str(measured.get("error", ""))[:cfg.max_command_bytes])
                result["evidence"].update(exit_code=measured.get("exit_code"), engine=ready["engine"],
                                           baseline_tests_protected=True, phases=verified_phases, output=output[:cfg.max_command_bytes])
            return result
        except asyncio.CancelledError:
            result.update(status="interrupted", passed=False, error="Evaluation was cancelled")
            raise
        except (OSError, ValueError, TimeoutError) as exc:
            logger.warning("isolated evaluation failed: %s", type(exc).__name__)
            result.update(error=str(exc) or type(exc).__name__, status="failed", passed=False)
            return result
        finally:
            try:
                await asyncio.shield(self._remove(name))
                if name in self._owned:
                    result.update(status="failed", passed=False, error="Owned sandbox cleanup failed")
            except (OSError, ValueError, TimeoutError) as exc:
                result.update(status="failed", passed=False, error="Owned sandbox cleanup failed: " + str(exc))
            finally:
                if stage is not None:
                    shutil.rmtree(stage)
                self._tasks.discard(task)
                if report_target is not None:
                    try:
                        result["report"] = str(report_target)
                        # Exclusive creation refuses symlinks or files inserted after validation.
                        with report_target.open("x", encoding="utf-8") as output:
                            json.dump(result, output, ensure_ascii=False, indent=2)
                    except OSError as exc:
                        result.update(status="failed", passed=False, error="Could not save evaluation result: " + str(exc))

    async def close(self) -> None:
        self._closed = True
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for name in tuple(self._owned):
            await self._remove(name)
