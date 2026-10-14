"""Start a dedicated, local ComfyUI process only for requested Hollow renders.

An already-running ComfyUI may be reused, but only children started here are stopped.
The caller retains responsibility for serializing GPU generation itself.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .util import spawn, terminate

logger = logging.getLogger("clipbot.story_visual_service")


class StoryVisualService:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._proc = None
        self._log_task = None
        self._identity = None

    @staticmethod
    def _url(cfg):
        try:
            url = urlsplit(cfg.comfy_url)
            port = url.port
            address = ipaddress.ip_address(url.hostname or "")
        except ValueError as exc:
            raise ValueError("Hollow's managed ComfyUI address is invalid") from exc
        if (url.scheme != "http" or not address.is_loopback or not port
                or url.username is not None or url.password is not None
                or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("Hollow's managed ComfyUI requires HTTP on a literal loopback address with an explicit local port")
        host = f"[{address.compressed}]" if isinstance(address, ipaddress.IPv6Address) else address.compressed
        return f"http://{host}:{port}", port

    @staticmethod
    def _path(raw, label, *, directory):
        if not raw or not isinstance(raw, str):
            raise ValueError(f"Configure {label} in Hollow settings")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{label} must be an absolute local path")
        for component in (path, *path.parents):
            if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
                raise ValueError(f"{label} cannot use symbolic links or directory junctions")
        if str(path).startswith(("\\\\", "//")):
            raise ValueError(f"{label} must be on a local drive")
        if not (path.is_dir() if directory else path.is_file()):
            raise ValueError(f"{label} does not exist: {path}")
        return path.resolve(strict=True)

    @staticmethod
    def _child(root, name, *, directory=True):
        path = root / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(f"Hollow runtime path cannot be a link: {path}")
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError("Hollow runtime path escapes its models folder")
        if directory:
            path.mkdir(parents=True, exist_ok=True)
        elif path.exists() and not path.is_file():
            raise ValueError(f"Hollow runtime file is not a regular file: {path}")
        return path

    async def _healthy(self, cfg, http, base):
        try:
            async with http.stream("GET", base + "/system_stats", timeout=cfg.comfy_probe_timeout_s,
                                   follow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError("The configured Hollow port responds, but is not a ready ComfyUI service")
                body = bytearray()
                async for chunk in response.aiter_bytes(1024):
                    body.extend(chunk)
                    if len(body) > cfg.comfy_metadata_max_bytes:
                        raise ValueError("Hollow ComfyUI health response exceeded its metadata limit")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            return False
        except httpx.HTTPError as exc:
            raise ValueError("Hollow ComfyUI health check failed") from exc
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("The configured Hollow port did not return ComfyUI health data") from exc
        system = data.get("system") if isinstance(data, dict) else None
        devices = data.get("devices") if isinstance(data, dict) else None
        if (not isinstance(system, dict) or not isinstance(system.get("comfyui_version"), str)
                or not system["comfyui_version"].strip() or not isinstance(devices, list) or not devices
                or any(not isinstance(device, dict) or not isinstance(device.get("name"), str)
                       or not isinstance(device.get("type"), str)
                       or not isinstance(device.get("vram_total"), (int, float))
                       or isinstance(device.get("vram_total"), bool) for device in devices)):
            raise ValueError("The configured Hollow port is not a verified ComfyUI service")
        return True

    async def _drain_log(self, proc, target, max_bytes):
        try:
            with target.open("ab") as output:
                while chunk := await proc.stdout.read(1024):
                    if output.tell() + len(chunk) > max_bytes:
                        output.seek(0)
                        output.truncate()
                    output.write(chunk)
                    output.flush()
        except (OSError, ValueError) as exc:
            logger.error("Hollow ComfyUI log could not be written: %s", exc)
            # Keep consuming the pipe so a filesystem failure cannot deadlock the child.
            while await proc.stdout.read(1024):
                pass

    async def _stop(self, settings):
        proc, log_task = self._proc, self._log_task
        self._proc = self._log_task = self._identity = None
        try:
            if proc is not None:
                await terminate(proc, settings.app.shutdown_timeout_s)
                logger.info("Stopped Hollow's owned ComfyUI child")
        finally:
            if log_task is not None:
                try:
                    await asyncio.wait_for(log_task, settings.app.shutdown_timeout_s)
                except asyncio.TimeoutError:
                    log_task.cancel()
                    await asyncio.gather(log_task, return_exceptions=True)

    async def stop(self, settings):
        """Stop only the ComfyUI child that this instance owns."""
        async with self._lock:
            await self._stop(settings)

    async def ensure(self, settings, http):
        """Verify a local ComfyUI or start and health-check an owned dedicated child."""
        cfg = settings.stories
        base, port = self._url(cfg)
        identity = (base, cfg.comfy_root, cfg.comfy_python, cfg.comfy_models_root, cfg.comfy_motion_models_root)
        async with self._lock:
            if self._proc is not None and (self._proc.returncode is not None or self._identity != identity):
                await self._stop(settings)
            if await self._healthy(cfg, http, base):
                return
            if self._proc is not None:
                await self._stop(settings)
            if not cfg.comfy_autostart:
                raise ValueError("Hollow ComfyUI is not running. Enable managed startup or start the configured local service")
            root = self._path(cfg.comfy_root, "Hollow ComfyUI installation", directory=True)
            python = self._path(cfg.comfy_python, "Hollow ComfyUI Python", directory=False)
            models = self._path(cfg.comfy_models_root, "Hollow models folder", directory=True)
            main = self._path(str(root / "main.py"), "ComfyUI main.py", directory=False)
            runtime = self._child(models, ".hollow-runtime")
            directories = {name: self._child(runtime, name) for name in ("output", "input", "temp", "user", "cache")}
            config = self._child(runtime, "extra_model_paths.yaml", directory=False)
            config.write_text("hollow:\n  base_path: " + json.dumps(str(models))
                              + "\n  is_default: true\n  diffusion_models: diffusion_models\n"
                                "  text_encoders: text_encoders\n  clip: text_encoders\n"
                                "  vae: vae\n  loras: loras\n  checkpoints: checkpoints\n", encoding="utf-8")
            if cfg.comfy_motion_models_root:
                motion_models = self._path(cfg.comfy_motion_models_root, "Hollow animation models folder", directory=True)
                with config.open("a", encoding="utf-8") as output:
                    output.write("hollow_motion:\n  base_path: " + json.dumps(str(motion_models))
                                 + "\n  is_default: true\n  diffusion_models: diffusion_models\n"
                                   "  text_encoders: text_encoders\n  clip: text_encoders\n  vae: vae\n")
            log = self._child(runtime, "comfyui.log", directory=False)
            if log.exists() and log.stat().st_size > cfg.comfy_log_max_bytes:
                log.write_bytes(b"")
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                       TEMP=str(directories["temp"]), TMP=str(directories["temp"]), TMPDIR=str(directories["temp"]),
                       HF_HOME=str(directories["cache"] / "huggingface"), TORCH_HOME=str(directories["cache"] / "torch"),
                       XDG_CACHE_HOME=str(directories["cache"]), CUDA_CACHE_PATH=str(directories["cache"] / "cuda"))
            args = [str(python), "-u", str(main), "--listen", urlsplit(base).hostname, "--port", str(port),
                    "--base-directory", str(runtime), "--models-directory", str(models),
                    "--extra-model-paths-config", str(config), "--output-directory", str(directories["output"]),
                    "--input-directory", str(directories["input"]), "--temp-directory", str(directories["temp"]),
                    "--user-directory", str(directories["user"]),
                    "--database-url", "sqlite:///" + str(directories["user"] / "comfyui.db"), "--disable-auto-launch",
                    "--disable-all-custom-nodes", "--disable-api-nodes"]
            try:
                self._proc = await spawn(*args, cwd=str(runtime), env=env,
                                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                self._identity = identity
                self._log_task = asyncio.create_task(self._drain_log(self._proc, log, cfg.comfy_log_max_bytes),
                                                     name="hollow-comfy-log")
                logger.info("Starting Hollow's dedicated ComfyUI on %s; log: %s", base, log)
                deadline = asyncio.get_running_loop().time() + cfg.comfy_startup_timeout_s
                async with asyncio.timeout(cfg.comfy_startup_timeout_s):
                    while True:
                        if self._proc.returncode is not None:
                            raise ValueError(f"Hollow ComfyUI exited during startup; inspect {log}")
                        if await self._healthy(cfg, http, base):
                            logger.info("Hollow's dedicated ComfyUI is ready")
                            return
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError()
                        await asyncio.sleep(min(cfg.comfy_startup_poll_s, remaining))
            except TimeoutError as exc:
                await self._stop(settings)
                raise ValueError(f"Hollow ComfyUI did not start before its deadline; inspect {log}") from exc
            except BaseException:
                await self._stop(settings)
                raise
