"""Real local-model repair trial against a disposable, non-production checkout."""
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipbot.config import Settings
from clipbot.supervisor import Supervisor
from clipbot.supervisor_changes import digest


async def main():
    with tempfile.TemporaryDirectory(prefix="ashvane-supervisor-local-") as folder:
        root = Path(folder)
        checkout, home = root / "checkout", root / "home"
        os.environ["CLIPBOT_HOME"] = str(home)
        (checkout / "clipbot").mkdir(parents=True)
        (checkout / "tests").mkdir()
        (checkout / "clipbot" / "__init__.py").write_text("")
        source = b"import uuid\n\ndef new_id():\n    return uuid.uuid4().hex\n"
        (checkout / "clipbot" / "example.py").write_bytes(source)
        (checkout / "tests" / "conftest.py").write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n")
        (checkout / "tests" / "test_original.py").write_text("from clipbot.example import new_id\ndef test_type():\n    assert isinstance(new_id(), str)\n")
        (checkout / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
        settings = Settings()
        settings.supervisor.enabled = True
        settings.supervisor.source_root = str(checkout)
        # Use the installed engineering specialist, then a fresh small reviewer.
        settings.supervisor.max_turns = 4
        settings.supervisor.restart_after_repair = False
        ctx = SimpleNamespace(settings=settings, paths=SimpleNamespace(data=home),
                              pipeline=SimpleNamespace(gpu_lock=asyncio.Lock()))
        supervisor = Supervisor(ctx)
        supervisor._remaining = settings.supervisor.max_turns
        supervisor._active = {"id": "synthetic", "status": "running"}
        supervisor.memory.data["jobs"].append(supervisor._active)
        try:
            result = await supervisor._agent("engineer", {
                "task": "Fix new_id() to return canonical LOWERCASE HYPHENATED UUID strings. Source and hash are already supplied below. Use propose_change directly, with a pytest assertion that canonical uuid.UUID normalization equals the original string and that length is 36. Reserve a reviewer turn. Do not remove hyphens.",
                "path": "clipbot/example.py", "before_sha256": digest(source), "source": source.decode()})
            report = {"result": result, "snapshot": supervisor.snapshot(),
                      "updated_source": (checkout / "clipbot" / "example.py").read_text()}
            output = Path(__file__).resolve().parent.parent / "artifacts" / "supervisor-local-repair.json"
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(output), "updated_source": report["updated_source"],
                              "change": supervisor._active.get("change")}, indent=2))
        finally:
            settings.supervisor.enabled = False
            await supervisor.close()
            # Overlay files are deliberately read-only; this is our disposable trial.
            for item in root.rglob("*"):
                if item.is_file():
                    item.chmod(stat.S_IWRITE | stat.S_IREAD)


if __name__ == "__main__":
    asyncio.run(main())
