"""Prerequisites respect disabled businesses, external servers and process ownership."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from clipbot.config import Settings
from clipbot.dependencies import LocalDependencies


def test_dependencies_skip_disabled_and_external_servers(monkeypatch):
    async def run():
        settings = Settings()
        service = LocalDependencies(SimpleNamespace(settings=settings))
        service._ready = AsyncMock(return_value=False)
        spawn = AsyncMock()
        monkeypatch.setattr("clipbot.dependencies.spawn", spawn)
        for field in type(settings.businesses).model_fields:
            setattr(settings.businesses, field, False)
        await service.ensure()
        settings.businesses.social_enabled = True
        settings.ai.ollama_url = "http://another-pc:11434"
        await service.ensure()
        settings.ai.ollama_url = "http://127.0.0.1:11434"
        settings.ai.auto_start = False
        await service.ensure()
        service._ready.assert_not_awaited()
        spawn.assert_not_awaited()
    asyncio.run(run())


def test_existing_ollama_is_reused_and_never_terminated(monkeypatch):
    async def run():
        service = LocalDependencies(SimpleNamespace(settings=Settings()))
        service._ready = AsyncMock(return_value=True)
        spawn, terminate = AsyncMock(), AsyncMock()
        monkeypatch.setattr("clipbot.dependencies.spawn", spawn)
        monkeypatch.setattr("clipbot.dependencies.terminate", terminate)
        await service.ensure()
        await service.close()
        assert service.message == "Local AI ready"
        spawn.assert_not_awaited()
        terminate.assert_not_awaited()
    asyncio.run(run())


def test_core_alone_starts_local_dependencies(monkeypatch):
    async def run():
        settings = Settings()
        for field in type(settings.businesses).model_fields:
            setattr(settings.businesses, field, False)
        settings.supervisor.enabled = True
        service = LocalDependencies(SimpleNamespace(settings=settings))
        service._ready = AsyncMock(return_value=True)
        spawn = AsyncMock()
        monkeypatch.setattr("clipbot.dependencies.spawn", spawn)
        await service.ensure()
        service._ready.assert_awaited_once()
        assert service.message == "Local AI ready"
        spawn.assert_not_awaited()
    asyncio.run(run())


def test_owned_ollama_starts_once_with_configured_host_and_closes(monkeypatch):
    async def run():
        settings = Settings()
        settings.ai.executable = "installed-ollama.exe"
        settings.ai.ollama_url = "http://127.0.0.1:11500"
        service = LocalDependencies(SimpleNamespace(settings=settings))
        service._ready = AsyncMock(side_effect=[False, True, True])
        process = SimpleNamespace(returncode=None)
        spawn, terminate = AsyncMock(return_value=process), AsyncMock()
        monkeypatch.setattr("clipbot.dependencies.spawn", spawn)
        monkeypatch.setattr("clipbot.dependencies.terminate", terminate)
        await service.ensure()
        await service.ensure()
        spawn.assert_awaited_once()
        assert spawn.call_args.args == ("installed-ollama.exe", "serve")
        assert spawn.call_args.kwargs["env"]["OLLAMA_HOST"] == "127.0.0.1:11500"
        await service.close()
        terminate.assert_awaited_once_with(process, settings.app.shutdown_timeout_s)
    asyncio.run(run())


def test_missing_ollama_reports_failure_without_breaking_app(monkeypatch):
    async def run():
        service = LocalDependencies(SimpleNamespace(settings=Settings()))
        service._ready = AsyncMock(return_value=False)
        monkeypatch.setattr("clipbot.dependencies.shutil.which", lambda _: None)
        monkeypatch.setattr("clipbot.dependencies.Path.is_file", lambda _: False)
        await service.ensure()
        assert "not installed" in service.message
        assert service.process is None
    asyncio.run(run())
