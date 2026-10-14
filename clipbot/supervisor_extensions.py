"""Public extensions acquired as evidence, or executed in disposable offline containers.

No discovered instructions may grant authority. The only executable format is a pinned
public PyPI distribution in a generated image; the host never imports that package.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import stat
import tarfile
import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx

from .research import fetch_feed, public_url
from .util import spawn, terminate

logger = logging.getLogger("clipbot.supervisor_extensions")
JSONRPC_METHOD_NOT_FOUND = -32601
PROTOCOL = "2024-11-05"
PROTOCOLS = frozenset({PROTOCOL, "2025-03-26", "2025-06-18"})
FREE_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
                           "MPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only",
                           "GPL-3.0-or-later", "AGPL-3.0-only", "AGPL-3.0-or-later",
                           "Unlicense", "CC0-1.0", "PSF-2.0", "0BSD"})
PACKAGE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc|post|dev)[0-9]+)?")
EXECUTABLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
IDENTIFIER = re.compile(r"ext-[a-f0-9]{32}")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
BASE_IMAGE = re.compile(r"python(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?(?:@sha256:[a-f0-9]{64})?")
FORBIDDEN = re.compile(r"(?:token|secret|password|credential|api[_-]?key|authorization)", re.I)


def _plain_path(path: Path) -> Path:
    absolute = path.absolute()
    for part in (absolute, *absolute.parents):
        if part.exists() or part.is_symlink():
            attrs = getattr(part.lstat(), "st_file_attributes", 0)
            if part.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Extension storage cannot contain links or junctions")
    return absolute.resolve()


def _json(value, limit: int) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Extension payload must be finite JSON") from exc
    if len(encoded) > limit:
        raise ValueError("Extension JSON exceeds configured byte limit")
    return encoded


def _host_environment() -> dict[str, str]:
    """Only operating-system bootstrap variables; no account, proxy or Docker env."""
    if os.name == "nt":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return {"SystemRoot": root, "WINDIR": root, "PATH": str(Path(root) / "System32")}
    return {"PATH": "/usr/bin:/bin"}


def _validate_spec(spec: dict, cfg) -> dict:
    _json(spec, cfg.response_max_bytes)
    if not isinstance(spec, dict):
        raise ValueError("Extension specification must be an object")
    kind = spec.get("kind", "mcp")
    allowed = {"mcp": {"kind", "ecosystem", "package", "version", "executable", "args"},
               "skill": {"kind", "url"}, "connector": {"kind", "url"}}
    if not isinstance(kind, str) or kind not in allowed or set(spec) - allowed[kind]:
        raise ValueError("Unsupported extension fields; host commands, paths, environment and Dockerfiles are forbidden")
    if kind in {"skill", "connector"}:
        return {"kind": kind, "url": public_url(spec.get("url", ""))}
    if spec.get("ecosystem", "pip") != "pip":
        raise ValueError("Only pinned public PyPI MCP packages are currently executable")
    result = {"kind": kind, "ecosystem": "pip"}
    for key, regex in (("package", PACKAGE), ("version", VERSION), ("executable", EXECUTABLE)):
        value = spec.get(key)
        if not isinstance(value, str) or not regex.fullmatch(value) or len(value) > cfg.max_text_chars:
            raise ValueError("Invalid pinned package/version/executable")
        result[key] = value
    args = spec.get("args", [])
    if not isinstance(args, list) or len(args) > cfg.source_limit:
        raise ValueError("Invalid or excessive extension arguments")
    for arg in args:
        if (not isinstance(arg, str) or len(arg) > cfg.max_text_chars or "\x00" in arg
                or "\n" in arg or "\r" in arg or FORBIDDEN.search(arg)
                or (not arg.startswith("--") and arg != "/workspace")):
            raise ValueError("Arguments may only be public option flags or the isolated /workspace")
    result["args"] = args
    return result


def _license(info: dict) -> str:
    expression = info.get("license_expression") or info.get("license")
    if isinstance(expression, str) and expression.strip() in FREE_LICENSES:
        return expression.strip()
    classifiers = info.get("classifiers", [])
    known = {"License :: OSI Approved :: MIT License": "MIT",
             "License :: OSI Approved :: Apache Software License": "Apache-2.0",
             "License :: OSI Approved :: ISC License (ISCL)": "ISC",
             "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0"}
    for classifier in classifiers if isinstance(classifiers, list) else []:
        if isinstance(classifier, str) and classifier in known:
            return known[classifier]
    raise ValueError("Public registry does not identify a supported free software license")


class Extensions:
    def __init__(self, settings, workspace: Path):
        self.settings = settings
        self.root = _plain_path(Path(workspace) / "extensions")
        self.root.mkdir(parents=True, exist_ok=True)
        self._owned: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._lock = asyncio.Lock()
        # An empty, unique Docker CLI config path prevents inherited registry logins/proxies.
        self._docker_config = "/tmp/ashvane-docker-config-" + uuid.uuid4().hex

    @property
    def cfg(self):
        return self.settings.supervisor

    def _folder(self, extension_id: str) -> Path:
        if not isinstance(extension_id, str) or not IDENTIFIER.fullmatch(extension_id):
            raise ValueError("Invalid extension identifier")
        return _plain_path(self.root / extension_id)

    def _save(self, manifest: dict) -> None:
        folder = self._folder(manifest["id"])
        folder.mkdir(exist_ok=True)
        target = _plain_path(folder / "manifest.json")
        encoded = _json(manifest, self.cfg.max_command_bytes)
        temporary = _plain_path(folder / "manifest.tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)

    def inventory(self) -> list[dict]:
        records = []
        for folder in sorted(self.root.iterdir()):
            if not IDENTIFIER.fullmatch(folder.name):
                continue
            try:
                target = _plain_path(folder / "manifest.json")
                if target.stat().st_size > self.cfg.max_command_bytes:
                    raise ValueError("Oversized extension manifest")
                manifest = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict) or manifest.get("id") != folder.name:
                    raise ValueError("Invalid extension manifest")
                records.append(manifest)
            except (OSError, ValueError) as exc:
                logger.warning("extension manifest rejected: %s", type(exc).__name__)
            if len(records) >= self.cfg.source_limit:
                break
        return copy.deepcopy(records)

    def _argv(self, args: list[str]) -> list[str]:
        cli = ["docker", "--config", self._docker_config, *args]
        if os.name == "nt":
            root = _host_environment()["SystemRoot"]
            return [str(Path(root) / "System32" / "wsl.exe"), "-d", self.cfg.docker_distribution, "--cd", "/", "--", *cli]
        return cli

    def _cli_cwd(self) -> str:
        return _host_environment()["SystemRoot"] if os.name == "nt" else "/"

    async def _command(self, args: list[str], payload: bytes | None = None, *, build=False) -> tuple[int, str]:
        cfg = self.cfg
        process = await spawn(*self._argv(args), cwd=self._cli_cwd(), env=_host_environment(),
            stdin=asyncio.subprocess.PIPE if payload is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output = bytearray()

        async def consume():
            async def write():
                if payload is not None:
                    process.stdin.write(payload)
                    await process.stdin.drain()
                    process.stdin.close()
            writer = asyncio.create_task(write())
            try:
                while chunk := await process.stdout.read(min(cfg.max_command_bytes, 1024)):
                    output.extend(chunk)
                    if len(output) > cfg.max_command_bytes:
                        raise ValueError("Extension command output exceeds configured limit")
                await writer
                await process.wait()
            finally:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
        try:
            await asyncio.wait_for(consume(), cfg.extension_build_timeout_s if build else cfg.sandbox_timeout_s)
            return process.returncode, output.decode("utf-8", errors="replace")
        finally:
            await terminate(process, cfg.sandbox_timeout_s)

    async def _fetch(self, url: str) -> bytes:
        return await fetch_feed(public_url(url), SimpleNamespace(request_max_bytes=self.cfg.response_max_bytes),
                                self.cfg.fetch_timeout_s)

    async def _base(self) -> str:
        configured = self.cfg.extension_python_image
        if not isinstance(configured, str) or not BASE_IMAGE.fullmatch(configured) or configured == "python":
            raise ValueError("Configure an official versioned Python base image")
        args = ["image", "inspect", "--format", "{{json .RepoDigests}}", configured]
        code, output = await self._command(args)
        if code:
            code, _ = await self._command(["pull", configured], build=True)
            if code:
                raise RuntimeError("Official Python image could not be acquired")
            code, output = await self._command(args)
        if code:
            raise RuntimeError("Official Python image could not be inspected")
        digests = json.loads(output)
        for ref in digests if isinstance(digests, list) else []:
            if isinstance(ref, str) and ref.startswith(("python@sha256:", "docker.io/library/python@sha256:")):
                digest = ref.split("@", 1)[1]
                if IMAGE_ID.fullmatch(digest):
                    return "python@" + digest
        raise ValueError("Python image needs a verified registry digest")

    @staticmethod
    def _context(spec: dict, base: str, artifacts: list[dict]) -> bytes:
        # Only generated bytes enter the build. No host directory, user Dockerfile or env.
        check = ("import importlib.metadata as m; d=m.distribution(" + repr(spec["package"]) + "); "
                 "assert any(e.group=='console_scripts' and e.name==" + repr(spec["executable"]) +
                 " for e in d.entry_points), 'Executable is not this package console entrypoint'")
        requirement = spec["package"] + "==" + spec["version"] + " " + " ".join(
            "--hash=sha256:" + item["sha256"] for item in artifacts) + "\n"
        dockerfile = ("FROM " + base + "\nCOPY pinned.txt /opt/ashvane-pinned.txt\n" +
            "RUN " + json.dumps(["python", "-I", "-m", "pip", "install", "--no-deps", "--require-hashes",
                "--only-binary=:all:", "--disable-pip-version-check", "--no-cache-dir", "--no-input",
                "--index-url", "https://pypi.org/simple", "-r", "/opt/ashvane-pinned.txt"]) + "\n" +
            "RUN " + json.dumps(["python", "-I", "-m", "pip", "install", "--only-binary=:all:",
                "--disable-pip-version-check", "--no-cache-dir", "--no-input", "--index-url", "https://pypi.org/simple",
                spec["package"] + "==" + spec["version"]]) + "\n" +
            "RUN " + json.dumps(["python", "-I", "-c", check]) + "\n" +
            "ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nUSER nobody\nWORKDIR /workspace\n")
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for name, text in (("Dockerfile", dockerfile), ("pinned.txt", requirement)):
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return stream.getvalue()

    async def _build(self, spec: dict, extension_id: str, artifacts: list[dict]) -> dict:
        base = await self._base()
        image = "ashvane-extension:" + extension_id
        context = self._context(spec, base, artifacts)
        code, output = await self._command(["build", "--force-rm", "--tag", image, "--label",
            "org.ashvane.supervisor.extension=" + extension_id, "--file", "Dockerfile", "-"], context, build=True)
        if code:
            raise RuntimeError("Isolated package image build failed: " + output[-self.cfg.max_text_chars:])
        code, actual = await self._command(["image", "inspect", "--format", "{{.Id}}", image])
        if code or not IMAGE_ID.fullmatch(actual.strip()):
            raise RuntimeError("Extension image digest could not be verified")
        return {"image": actual.strip(), "image_tag": image, "base_image": base,
                "generated_context_sha256": hashlib.sha256(context).hexdigest()}

    async def _remove(self, name: str) -> None:
        if name not in self._owned:
            return
        code, _ = await self._command(["rm", "--force", name])
        if code:
            raise RuntimeError("Owned extension container cleanup failed")
        self._owned.discard(name)

    def _run_args(self, manifest: dict, name: str) -> list[str]:
        spec = _validate_spec(manifest["spec"], self.cfg)
        image = manifest["image"]
        if not isinstance(image, str) or not IMAGE_ID.fullmatch(image):
            raise ValueError("Invalid immutable extension image")
        cfg = self.cfg
        return ["run", "--interactive", "--name", name, "--label", "org.ashvane.supervisor.extension=" + name,
            "--network", "none", "--user", "65534:65534", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", str(cfg.sandbox_pids),
            "--memory", str(cfg.sandbox_memory_mb) + "m", "--memory-swap", str(cfg.sandbox_memory_mb) + "m",
            "--cpus", str(cfg.sandbox_cpus), "--tmpfs", "/tmp:rw,nosuid,nodev,size=" + str(cfg.sandbox_memory_mb) + "m",
            "--tmpfs", "/workspace:rw,nosuid,nodev,size=" + str(cfg.sandbox_memory_mb) + "m",
            "--workdir", "/workspace", "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint", "/usr/local/bin/" + spec["executable"], image, *spec["args"]]

    @asynccontextmanager
    async def _session(self, manifest: dict):
        name = "ashvane-mcp-" + uuid.uuid4().hex
        args = self._run_args(manifest, name)
        self._owned.add(name)
        process = None
        stderr_task = None
        try:
            process = await spawn(*self._argv(args), cwd=self._cli_cwd(), env=_host_environment(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=self.cfg.response_max_bytes + 1)
            async def drain():
                total = 0
                while chunk := await process.stderr.read(min(self.cfg.max_command_bytes, 1024)):
                    total += len(chunk)
                    if total > self.cfg.max_command_bytes:
                        raise ValueError("Extension stderr exceeded configured limit")
            stderr_task = asyncio.create_task(drain())
            yield process, stderr_task
        finally:
            if process is not None:
                await terminate(process, self.cfg.sandbox_timeout_s)
            if stderr_task is not None:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
            await asyncio.shield(self._remove(name))

    async def _mcp(self, manifest: dict, tool_name: str | None = None, arguments: dict | None = None) -> dict:
        cfg = self.cfg
        async with self._session(manifest) as (process, stderr_task):
            sequence = 0
            received = 0

            async def send(message):
                encoded = _json(message, cfg.response_max_bytes)
                process.stdin.write(encoded + b"\n")
                await process.stdin.drain()

            async def request(method, params):
                nonlocal sequence, received
                sequence += 1
                await send({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params})
                while True:
                    if stderr_task.done():
                        stderr_task.result()
                    line = await process.stdout.readline()
                    received += len(line)
                    if received > cfg.max_command_bytes or len(line) > cfg.response_max_bytes:
                        raise ValueError("MCP output exceeded configured limit")
                    if not line:
                        raise RuntimeError("MCP server stopped responding")
                    reply = json.loads(line)
                    if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0":
                        raise ValueError("Invalid MCP JSON-RPC reply")
                    if "method" in reply:
                        # Discovered servers cannot request filesystem roots, secrets, sampling or login.
                        if "id" in reply:
                            await send({"jsonrpc": "2.0", "id": reply["id"], "error": {
                                "code": JSONRPC_METHOD_NOT_FOUND, "message": "Client capabilities are disabled"}})
                        continue
                    if type(reply.get("id")) is not int or reply["id"] != sequence:
                        raise ValueError("Unexpected MCP response identifier")
                    if "error" in reply or not isinstance(reply.get("result"), dict):
                        raise RuntimeError("MCP request failed: " + method)
                    return reply["result"]

            async def execute():
                initialized = await request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                    "clientInfo": {"name": "Ashvane-isolated", "version": "1"}})
                if (initialized.get("protocolVersion") not in PROTOCOLS
                        or not isinstance(initialized.get("capabilities"), dict)
                        or "tools" not in initialized["capabilities"]):
                    raise ValueError("MCP initialize did not establish tool capability")
                await send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                tools = []
                params = {}
                for _ in range(cfg.source_limit):
                    listed = await request("tools/list", params)
                    page = listed.get("tools")
                    if not isinstance(page, list):
                        raise ValueError("MCP tools/list did not return tools")
                    tools.extend(page)
                    if len(tools) > cfg.source_limit:
                        raise ValueError("MCP inventory exceeds configured tool limit")
                    cursor = listed.get("nextCursor")
                    if not cursor:
                        break
                    if not isinstance(cursor, str):
                        raise ValueError("Invalid MCP pagination cursor")
                    params = {"cursor": cursor}
                else:
                    raise ValueError("MCP pagination exceeds configured limit")
                names = set()
                for tool in tools:
                    if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                            or not tool["name"] or len(tool["name"]) > cfg.max_text_chars
                            or tool["name"] in names or not isinstance(tool.get("inputSchema"), dict)):
                        raise ValueError("Invalid MCP tool description")
                    names.add(tool["name"])
                if not tools:
                    raise ValueError("MCP server supplied no callable tools")
                measured = {"tools": tools, "initialize": initialized,
                            "smoke": {"passed": True, "check": "initialize_and_tools_list", "tool_count": len(tools)}}
                if tool_name is not None:
                    if tool_name not in names:
                        raise ValueError("Tool is absent from current isolated MCP inventory")
                    measured["result"] = await request("tools/call", {"name": tool_name, "arguments": arguments})
                if stderr_task.done():
                    stderr_task.result()
                return measured
            return await asyncio.wait_for(execute(), cfg.sandbox_timeout_s)

    async def install(self, spec: dict) -> dict:
        if self._closed:
            return {"status": "closed", "callable": False}
        task = asyncio.current_task()
        self._tasks.add(task)
        manifest = None
        try:
            validated = _validate_spec(spec, self.cfg)
            async with self._lock:
                if self._closed:
                    return {"status": "closed", "callable": False}
                if len(self.inventory()) >= self.cfg.source_limit:
                    raise ValueError("Extension inventory is at its configured limit")
                extension_id = "ext-" + uuid.uuid4().hex
                manifest = {"id": extension_id, "spec": validated, "status": "acquiring", "callable": False}
                if validated["kind"] == "connector":
                    manifest.update(status="needs_connection", provenance={"url": validated["url"]},
                                    reason="Private account connections require the owner's connection flow")
                elif validated["kind"] == "skill":
                    data = await self._fetch(validated["url"])
                    text = data.decode("utf-8")
                    if "\x00" in text:
                        raise ValueError("Skill must be UTF-8 public text")
                    folder = self._folder(extension_id)
                    folder.mkdir()
                    (folder / "SKILL.md").write_text(text[:self.cfg.max_text_chars], encoding="utf-8")
                    manifest.update(status="knowledge_only", provenance={"url": validated["url"],
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
                        truncated=len(text) > self.cfg.max_text_chars,
                        authority="Untrusted reference text; no executable permission or account access")
                else:
                    url = "https://pypi.org/pypi/" + validated["package"] + "/" + validated["version"] + "/json"
                    data = await self._fetch(url)
                    metadata = json.loads(data)
                    info = metadata.get("info") if isinstance(metadata, dict) else None
                    if (not isinstance(info, dict) or info.get("version") != validated["version"]
                            or re.sub(r"[-_.]+", "-", str(info.get("name", ""))).lower()
                            != re.sub(r"[-_.]+", "-", validated["package"]).lower()):
                        raise ValueError("Registry did not confirm the requested package pin")
                    license_name = _license(info)
                    files = metadata.get("urls")
                    artifacts = []
                    for item in files if isinstance(files, list) else []:
                        if isinstance(item, dict) and item.get("packagetype") == "bdist_wheel" and not item.get("yanked"):
                            digests = item.get("digests")
                            sha = digests.get("sha256", "") if isinstance(digests, dict) else ""
                            if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha):
                                artifacts.append({"filename": item.get("filename"), "sha256": sha})
                    if not artifacts:
                        raise ValueError("Pinned package has no non-yanked hashed public wheel")
                    manifest.update(license=license_name, provenance={"registry": url,
                        "metadata_sha256": hashlib.sha256(data).hexdigest(), "wheels": artifacts})
                    manifest.update(await self._build(validated, extension_id, artifacts))
                    self._save(manifest)
                    manifest.update(await self._mcp(manifest))
                    manifest.update(status="ready", callable=True)
                self._save(manifest)
                return copy.deepcopy(manifest)
        except asyncio.CancelledError:
            if manifest is not None:
                manifest.update(status="cancelled", callable=False)
                self._save(manifest)
            raise
        except (OSError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as exc:
            logger.warning("extension acquisition failed: %s", type(exc).__name__)
            failure = {"status": "failed", "callable": False, "error": str(exc)[:self.cfg.max_text_chars]}
            if manifest is not None:
                manifest.update(failure)
                self._save(manifest)
                return copy.deepcopy(manifest)
            return failure
        finally:
            self._tasks.discard(task)

    async def call(self, extension_id: str, tool_name: str, arguments: dict) -> dict:
        if self._closed:
            return {"status": "closed"}
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if not isinstance(tool_name, str) or not tool_name or len(tool_name) > self.cfg.max_text_chars:
                raise ValueError("Invalid MCP tool name")
            if not isinstance(arguments, dict):
                raise ValueError("MCP tool arguments must be an object")
            _json(arguments, self.cfg.response_max_bytes)
            target = _plain_path(self._folder(extension_id) / "manifest.json")
            if target.stat().st_size > self.cfg.max_command_bytes:
                raise ValueError("Oversized extension manifest")
            manifest = json.loads(target.read_text(encoding="utf-8"))
            if (not isinstance(manifest, dict) or manifest.get("id") != extension_id or manifest.get("status") != "ready"
                    or not isinstance(manifest.get("spec"), dict)
                    or manifest["spec"].get("kind") != "mcp" or not manifest.get("callable")):
                raise ValueError("Extension has not passed isolated MCP initialization")
            measured = await self._mcp(manifest, tool_name, arguments)
            result = measured["result"]
            return {"status": "failed" if result.get("isError") else "completed", "result": result,
                    "extension_id": extension_id, "tool": tool_name, "image": manifest["image"]}
        except (OSError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as exc:
            logger.warning("extension call failed: %s", type(exc).__name__)
            return {"status": "failed", "error": str(exc)[:self.cfg.max_text_chars]}
        finally:
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        pending = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for name in tuple(self._owned):
            await self._remove(name)
