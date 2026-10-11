"""Start the Windows package against isolated disabled-capture data and verify its desk/API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from clipbot.config import Settings, merge_incoming, save_settings


def main():
    data = ROOT / "artifacts" / "packaged-preview-data"
    os.environ["CLIPBOT_HOME"] = str(data)
    settings = merge_incoming(Settings(), {
        "app": {"single_instance": False, "start_with_windows": False},
        "dashboard": {"port": 8790, "open_browser": False},
        "twitch": {"enabled": False}, "kick": {"enabled": False},
        "clip_import": {"enabled": False}, "trends": {"enabled": False},
        "research": {"enabled": False}, "analytics": {"enabled": False},
        "ai": {"auto_pull": False},
    })
    save_settings(settings)
    research_cache = ROOT / "artifacts" / "research-validation" / "research.json"
    if research_cache.is_file():
        shutil.copyfile(research_cache, data / "research.json")
    package = ROOT / "artifacts" / "windows-revamp" / "Ashvane"
    executable = package / "Ashvane.exe"
    output = ROOT / "artifacts" / "packaged-smoke.log"
    report = {"checks": {}, "executable": str(executable), "data": str(data)}
    with output.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable), "--headless"], cwd=package,
                                   env=os.environ.copy(), stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with httpx.Client(base_url="http://127.0.0.1:8790", timeout=10, trust_env=False) as client:
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"Package exited during startup: {process.returncode}; see {output}")
                    try:
                        status = client.get("/api/auth/status")
                        status.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Package did not serve its isolated dashboard before the deadline")
                        time.sleep(1)
                report["checks"]["startup"] = True
                action = "/api/auth/setup" if status.json().get("setup") else "/api/auth/login"
                login = client.post(action, headers={"X-ClipBot": "1"},
                                    json={"name": "Packaged preview", "password": "packaged-preview-2026"})
                login.raise_for_status()
                report["checks"]["sign_in"] = True
                for route in ("/api/state", "/api/research", "/api/setup", "/api/settings/schema", "/api/publishing/batch"):
                    response = client.get(route)
                    response.raise_for_status()
                    response.json()
                    report["checks"][route] = True
                research = client.get("/api/research").json()
                report["sources"], report["ideas"] = len(research["sources"]), len(research["ideas"])
                for name in ("index.html", "desk.js", "desk.css"):
                    route = "/" if name == "index.html" else f"/static/{name}"
                    response = client.get(route)
                    response.raise_for_status()
                    source = ROOT / "clipbot" / "dashboard" / "static" / name
                    report["checks"]["asset:" + name] = response.content == source.read_bytes()
                if not all(report["checks"].values()):
                    raise RuntimeError("Packaged desk assets differ from the verified source")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            (ROOT / "artifacts" / "packaged-smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
