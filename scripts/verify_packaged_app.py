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
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from clipbot.config import Settings, merge_incoming, save_settings, resolve_paths, ffmpeg_exe
from clipbot.db import Store
from clipbot.models import Candidate, StreamTarget, SpikeEvent, Platform, Stage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neural", action="store_true", help="Also run the frozen local neural narration worker")
    parser.add_argument("--overlay", action="store_true", help="Verify real frozen module/static overlays in isolated preview data")
    parser.add_argument("--package", type=Path, help="Verify a staged Windows package before replacing the installed folder")
    parser.add_argument("--compilation", action="store_true", help="Assemble two synthetic AV fixtures through the frozen Hollow API")
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
    compilation_ids = []
    if args.compilation:
        from clipbot.stories import StoryStudio
        fixture_studio = StoryStudio(settings, None, resolve_paths(settings))
        for index, color in enumerate(("red", "blue")):
            pid = uuid.uuid4().hex
            folder = fixture_studio._directory(pid)
            folder.mkdir(parents=True)
            video, audio = folder / "fixture.mp4", folder / "fixture.m4a"
            subprocess.run([ffmpeg_exe(settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-f", "lavfi", "-i", f"color={color}:s=320x180:r=24:d=1",
                            "-f", "lavfi", "-i", f"sine=frequency={440 + index * 220}:sample_rate=48000:duration=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)],
                           check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            subprocess.run([ffmpeg_exe(settings), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-i", str(video), "-vn", "-c:a", "copy", str(audio)],
                           check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            row = {"id": pid, "title": f"Synthetic story {index + 1}", "topic": "Isolated AV fixture",
                   "genre": "paranormal", "format": "still", "duration_s": 1, "voice": "Fixture tone",
                   "script": "Synthetic fixture. No production story or creative review is claimed.", "scenes": [],
                   "public_copy": {"youtube": {"title": f"Synthetic story {index + 1}", "description": "Original fiction. Test fixture.", "tags": [], "hashtags": []}},
                   "account_profile_id": "default", "status": "ready", "progress": 1, "created_at": time.time(),
                   "updated_at": time.time(), "revision": 0, "publishing": {}, "agents": [], "error": "",
                   "output": {"video_path": str(video), "audio_path": str(audio), "duration_s": 1, "width": 320, "height": 180}}
            fixture_studio.projects.append(row)
            row["review"] = {"passed": True, "scope": "synthetic_fixture", "content_hash": fixture_studio.content_fingerprint(pid)}
            compilation_ids.append(pid)
        fixture_studio._save()
    # Synthetic isolated evidence; never seed or modify the owner's production data.
    sample_id = "feedbacc12345"
    target = StreamTarget(Platform.TWITCH, "preview", "Preview", "Fixture", 0)
    event = SpikeEvent(target=target, t_wall=1, kind="chat", score=0, chat_rate=0, baseline=0)
    sample = Candidate(sample_id, event, "", 0, 20, stage=Stage.REJECTED,
                       verdict={"passed": False, "reason": "Synthetic preview fixture"})
    store = Store(resolve_paths(settings).db)
    try:
        store.upsert_candidate(sample)
    finally:
        store.close()
    research_cache = ROOT / "artifacts" / "research-validation" / "research.json"
    if research_cache.is_file():
        shutil.copyfile(research_cache, data / "research.json")
    package = args.package.resolve() if args.package else ROOT / "artifacts" / "windows-revamp" / "Ashvane"
    executable = package / "Ashvane.exe"
    output = ROOT / "artifacts" / "packaged-smoke.log"
    report = {"checks": {}, "executable": str(executable), "data": str(data)}
    overlay_version = None
    if args.overlay:
        from clipbot.supervisor_bootstrap import stage_overlay
        from clipbot.supervisor_changes import digest
        candidate = ROOT / "artifacts" / ("overlay-probe-" + uuid.uuid4().hex)
        module = candidate / "clipbot" / "growth.py"
        module.parent.mkdir(parents=True)
        source = (ROOT / "clipbot" / "growth.py").read_text(encoding="utf-8")
        needle = 'return {"analytics": analytics,'
        if source.count(needle) != 1:
            raise RuntimeError("Growth overlay probe no longer matches the verified source")
        module.write_bytes(source.replace(needle, 'return {"overlay_probe": "verified", "analytics": analytics,', 1).encode())
        asset = candidate / "clipbot" / "dashboard" / "static" / "overlay-probe.txt"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b"hash-pinned overlay verified")
        changes = [{"path": path.relative_to(candidate).as_posix(), "after_sha256": digest(path.read_bytes())}
                   for path in (module, asset)]
        overlay_version = "smoke-" + uuid.uuid4().hex
        stage_overlay(candidate, changes, data, overlay_version)
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
                runtime_js = client.get("/ui-runtime.js")
                report["checks"]["anonymous_configured_ui_deadline"] = (
                    runtime_js.status_code == 200 and "growth_request_timeout_s" in runtime_js.text
                    and runtime_js.headers.get("cache-control") == "no-store")
                report["checks"]["anonymous_private_data_locked"] = client.get("/api/growth").status_code == 401
                action = "/api/auth/setup" if status.json().get("setup") else "/api/auth/login"
                login = client.post(action, headers={"X-ClipBot": "1"},
                                    json={"name": "Packaged preview", "password": "packaged-preview-2026"})
                login.raise_for_status()
                report["checks"]["sign_in"] = True
                rejected = client.get("/api/clips").json()["rejected_cleanup"]
                report["checks"]["rejected_cleanup_cadence"] = rejected["interval_min"] == 20
                cleanup = client.post("/api/clips/rejected/delete-media", headers={"X-ClipBot": "1"},
                                      json={"confirm": "delete-rejected-media"})
                cleanup.raise_for_status()
                cleaned = cleanup.json()
                report["checks"]["empty_rejected_cleanup"] = cleaned["files_deleted"] == 0 and cleaned["bytes_freed"] == 0
                reference_options = client.get("/api/music/references/options")
                reference_options.raise_for_status()
                report["checks"]["reference_upload_limits"] = reference_options.json()["max_upload_bytes"] == settings.music.reference_upload_max_bytes
                stopped_upload = client.post("/api/music/references/upload", content=b"verification", headers={"X-ClipBot": "1", "X-File-Name": "verification.wav"})
                report["checks"]["reference_upload_stopped_gate"] = stopped_upload.status_code == 409
                # Exercise the compatibility form before the new profile panel
                # initializes anything. This uses isolated, stopped test data.
                legacy_account = client.put("/api/stories/accounts", headers={"X-ClipBot": "1"},
                                            json={"youtube_client_id": "packaged-preview-client"})
                legacy_account.raise_for_status()
                report["checks"]["legacy_account_save_before_profile_panel"] = True
                for route in ("/api/state", "/api/research", "/api/setup", "/api/settings/schema", "/api/publishing/batch", "/api/stories", "/api/stories/publishing", "/api/stories/accounts", "/api/businesses", "/api/social/clients", "/api/account-profiles/clips", "/api/account-profiles/stories", "/api/account-profiles/music", "/api/creative-memory/stories", "/api/creative-memory/music", "/api/supervisor", "/api/growth"):
                    response = client.get(route)
                    response.raise_for_status()
                    response.json()
                    report["checks"][route] = True
                stopped_core = client.post("/api/supervisor/master", headers={"X-ClipBot": "1"}, json={"enabled": False})
                stopped_core.raise_for_status()
                report["checks"]["supervisor_master_off"] = stopped_core.json()["state"] == "off" and not stopped_core.json()["enabled"]
                observations = stopped_core.json()["observations"]
                report["checks"]["runtime_observation_stop"] = not observations["collecting"] and observations["fault_events"] == 0
                report["checks"]["runtime_observation_metrics"] = set(observations["resources"]["gpu"]) == {"util", "mem_used", "mem_total", "temp"}
                analytics = client.get("/api/analytics").json()
                report["checks"]["analytics_profile_owned"] = analytics["account_profile_id"] == "default" and "youtube_outcomes" in analytics
                stale_refresh = client.post("/api/growth/outcomes/refresh", headers={"X-ClipBot": "1", "X-Account-Profile": "a" * 32}, json={})
                report["checks"]["outcome_stale_profile_rejected"] = stale_refresh.status_code == 409
                runtime_js = client.get("/ui-runtime.js")
                report["checks"]["configured_ui_deadline"] = runtime_js.status_code == 200 and "growth_request_timeout_s" in runtime_js.text
                capacity = client.get("/api/state").json()["capture_storage"]
                report["checks"]["separate_capture_storage_budget"] = capacity == {"active": 0, "waiting": 0, "limit": settings.capture.storage_workers, "reason": ""}
                feedback = client.put("/api/clip-feedback/" + sample_id, headers={"X-ClipBot": "1", "X-Account-Profile": "default"},
                                      json={"label": "good", "note": "Synthetic owner correction", "preview_s": 1})
                feedback.raise_for_status()
                report["checks"]["clip_correction_saved"] = feedback.json()["record"]["label"] == "good"
                saved_feedback = client.get("/api/clip-feedback/" + sample_id, headers={"X-Account-Profile": "default"}).json()
                report["checks"]["clip_correction_private_no_auto_tuning"] = saved_feedback["record"]["note"] == "Synthetic owner correction" and not saved_feedback["summary"]["automatic_tuning"]
                if args.overlay:
                    report["checks"]["frozen_module_overlay"] = client.get("/api/growth").json().get("overlay_probe") == "verified"
                    report["checks"]["frozen_static_overlay"] = client.get("/static/overlay-probe.txt").content == b"hash-pinned overlay verified"
                    report["checks"]["frozen_overlay_boot_confirmed"] = not (data / "supervisor" / "runtime" / "pending.json").exists()
                research = client.get("/api/research").json()
                report["sources"], report["ideas"] = len(research["sources"]), len(research["ideas"])
                runtime = client.get("/api/businesses").json()["businesses"]
                report["checks"]["independent_stopped_businesses"] = len(runtime) == 4 and not any(row["enabled"] for row in runtime)
                readiness = client.get("/api/setup").json()["businesses"]
                report["checks"]["four_business_readiness"] = len(readiness) == 4 and all(row["status"] == "stopped" for row in readiness)
                for name in ("index.html", "desk.js", "desk.css", "clip-feedback.js", "stories.js", "stories.css", "cosmic.js", "cosmic.css", "business.js", "business.css", "music.js", "music.css", "social.js", "social.css", "creative.js", "creative.css", "accounts.js", "accounts.css", "supervisor.js", "supervisor.css", "growth.js", "growth.css", "simplification.js", "simplification.css", "observatory.css", "observatory.js", "supervisor-neural.js", "supervisor-horizon.js", "supervisor-phone.html"):
                    route = "/" if name == "index.html" else f"/static/{name}"
                    response = client.get(route)
                    response.raise_for_status()
                    source = ROOT / "clipbot" / "dashboard" / "static" / name
                    report["checks"]["asset:" + name] = response.content == source.read_bytes()
                if args.compilation:
                    client.post("/api/businesses/stories", headers={"X-ClipBot": "1"}, json={"enabled": True}).raise_for_status()
                    try:
                        state = client.get("/api/stories").json()
                        response = client.post("/api/stories/compilations", headers={"X-ClipBot": "1"},
                            json={"title": "Frozen compilation fixture", "project_ids": compilation_ids,
                                  "landscape": True, "account_profile_id": state["account_profile_id"]})
                        response.raise_for_status()
                        pid = response.json()["id"]
                        deadline = time.monotonic() + 120
                        while True:
                            result = client.get(f"/api/stories/projects/{pid}").json()
                            if result["status"] not in {"queued", "rendering"}:
                                break
                            if time.monotonic() >= deadline:
                                raise RuntimeError("Frozen compilation did not finish before its deadline")
                            time.sleep(.5)
                        report["checks"]["frozen_real_av_compilation"] = result["status"] == "ready"
                        report["checks"]["frozen_measured_compilation_chapters"] = len(result["compilation"].get("chapters", [])) == 3
                        report["checks"]["frozen_compilation_source_snapshots"] = len(result["compilation"].get("snapshots", [])) == 2
                        report["checks"]["frozen_compilation_private_review_excluded"] = "technical checks" not in result["public_copy"]["youtube"]["description"]
                        report["compilation"] = {"synthetic_av": True, "status": result["status"],
                                                 "duration_s": result.get("output", {}).get("duration_s"), "error": result.get("error", "")}
                    finally:
                        client.post("/api/businesses/stories", headers={"X-ClipBot": "1"}, json={"enabled": False}).raise_for_status()
                if not all(report["checks"].values()):
                    raise RuntimeError("Packaged desk assets differ from the verified source")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if overlay_version:
                from clipbot.supervisor_bootstrap import rollback_overlay
                rollback_overlay(data, overlay_version)
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
