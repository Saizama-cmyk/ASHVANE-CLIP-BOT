"""Start the Windows package against isolated disabled-capture data and verify its desk/API."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from clipbot.config import Settings, merge_incoming, save_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neural", action="store_true", help="Also run the frozen local neural narration worker")
    args = parser.parse_args()
    data = ROOT / "artifacts" / "packaged-preview-data"
    os.environ["CLIPBOT_HOME"] = str(data)
    settings = merge_incoming(Settings(), {
        "app": {"single_instance": False, "start_with_windows": False},
        "dashboard": {"port": 8790, "open_browser": False},
        "twitch": {"enabled": False}, "kick": {"enabled": False},
        "clip_import": {"enabled": False}, "trends": {"enabled": False},
        "research": {"enabled": False}, "analytics": {"enabled": False},
        "ai": {"auto_pull": False},
        "businesses": {"surge_enabled": False, "hollow_enabled": False,
                       "resonance_enabled": False, "social_enabled": False},
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
                # Exercise the compatibility form before the new profile panel
                # initializes anything. This uses isolated, stopped test data.
                legacy_account = client.put("/api/stories/accounts", headers={"X-ClipBot": "1"},
                                            json={"youtube_client_id": "packaged-preview-client"})
                legacy_account.raise_for_status()
                report["checks"]["legacy_account_save_before_profile_panel"] = True
                for route in ("/api/state", "/api/research", "/api/setup", "/api/settings/schema", "/api/publishing/batch", "/api/stories", "/api/stories/publishing", "/api/stories/accounts", "/api/businesses", "/api/social/clients", "/api/account-profiles/clips", "/api/account-profiles/stories", "/api/account-profiles/music", "/api/creative-memory/stories", "/api/creative-memory/music"):
                    response = client.get(route)
                    response.raise_for_status()
                    response.json()
                    report["checks"][route] = True
                research = client.get("/api/research").json()
                report["sources"], report["ideas"] = len(research["sources"]), len(research["ideas"])
                runtime = client.get("/api/businesses").json()["businesses"]
                report["checks"]["independent_stopped_businesses"] = len(runtime) == 4 and not any(row["enabled"] for row in runtime)
                readiness = client.get("/api/setup").json()["businesses"]
                report["checks"]["four_business_readiness"] = len(readiness) == 4 and all(row["status"] == "stopped" for row in readiness)
                for name in ("index.html", "desk.js", "desk.css", "stories.js", "stories.css", "cosmic.js", "cosmic.css", "business.js", "business.css", "music.js", "music.css", "social.js", "social.css", "creative.js", "creative.css", "accounts.js", "accounts.css"):
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
    if args.neural:
        folder = ROOT / "artifacts" / "packaged-neural-check"
        folder.mkdir(parents=True, exist_ok=True)
        models = Path(os.environ["LOCALAPPDATA"]) / "Ashvane" / "models" / "stories"
        audio = folder / "narration.wav"
        audio.unlink(missing_ok=True)
        plan = {"root": str(folder), "model_path": str(models / "kokoro.onnx"),
                "voices_path": str(models / "voices.bin"), "voice": "am_adam",
                "speed": .92, "lang": "en-us", "threads": 2,
                "scenes": [{"path": str(audio), "text": "Behind the sealed door, my own voice asked to come inside."}]}
        plan_path = folder / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result = subprocess.run([str(executable), "--story-voice", str(plan_path)], cwd=package,
                                capture_output=True, timeout=180,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not audio.is_file():
            raise RuntimeError(f"Frozen neural narrator failed ({result.returncode}): {result.stderr[-1000:]!r}")
        with wave.open(str(audio)) as wav:
            samples = wav.readframes(wav.getnframes())
            if not samples or not any(samples):
                raise RuntimeError("Frozen narrator produced silence")
            report["checks"]["frozen_neural_narrator"] = True
            report["narration_duration_s"] = wav.getnframes() / wav.getframerate()
        (ROOT / "artifacts" / "packaged-smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
