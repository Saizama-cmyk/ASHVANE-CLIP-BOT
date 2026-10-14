"""Start installed local prerequisites without duplicating existing services."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .util import spawn, terminate

logger = logging.getLogger("clipbot.dependencies")


class LocalDependencies:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = asyncio.Lock()
        self.process = None
        self.task = None
        self.message = "Not needed"

    def request(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.ensure(), name="local-dependencies")

    async def _ready(self, client, base):
        try:
            response = await client.get(base + "/api/tags")
            response.raise_for_status()
            return isinstance(response.json().get("models"), list)
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    async def ensure(self):
        async with self.lock:
            cfg = self.ctx.settings.ai
            businesses = self.ctx.settings.businesses
            if not cfg.auto_start or not any((businesses.surge_enabled, businesses.hollow_enabled,
                                              businesses.resonance_enabled, businesses.social_enabled,
                                              self.ctx.settings.supervisor.enabled)):
                return
            base = cfg.ollama_url.rstrip("/")
            url = urlsplit(base)
            local = url.hostname == "localhost"
            try:
                local = local or ip_address(url.hostname or "").is_loopback
            except ValueError:
                pass  # Named non-local hosts are externally managed.
            if (url.scheme != "http" or not local
                    or url.username or url.password or url.path or url.query or url.fragment):
                self.message = "Configured AI server is managed externally"
                return
            try:
                async with httpx.AsyncClient(trust_env=False, timeout=cfg.startup_poll_s) as client:
                    if await self._ready(client, base):
                        self.message = "Local AI ready"
                        return
                    if self.process is None or self.process.returncode is not None:
                        installed = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Ollama" / "ollama.exe"
                        executable = cfg.executable.strip() or shutil.which("ollama") or (str(installed) if installed.is_file() else "")
                        if not executable:
                            raise FileNotFoundError("Ollama is not installed; choose its executable in AI settings")
                        env = os.environ.copy()
                        env["OLLAMA_HOST"] = url.netloc
                        self.process = await spawn(executable, "serve", env=env,
                                                   stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    self.message = "Starting local AI"
                    deadline = asyncio.get_running_loop().time() + cfg.startup_timeout_s
                    while True:
                        if await self._ready(client, base):
                            self.message = "Local AI ready"
                            logger.info(self.message)
                            return
                        if self.process.returncode is not None:
                            raise RuntimeError("Ollama exited before becoming ready")
                        if asyncio.get_running_loop().time() >= deadline:
                            raise TimeoutError("Ollama startup timed out; check AI settings")
                        await asyncio.sleep(cfg.startup_poll_s)
            except (OSError, RuntimeError, ValueError) as exc:
                self.message = str(exc)
                logger.warning("Local dependency startup: %s", exc)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.process:
            await terminate(self.process, self.ctx.settings.app.shutdown_timeout_s)

