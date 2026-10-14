"""Atomically update installed static assets, retain originals and verify served bytes.

Does not restart Ashvane or touch any business, publishing record or account.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from clipbot.config import load_settings, resolve_paths
from fingerprint_dashboard_assets import fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("assets", nargs="+", help="Relative paths within dashboard/static")
    args = parser.parse_args()
    source = ROOT / "clipbot" / "dashboard" / "static"
    target = ROOT / "artifacts" / "windows-revamp" / "Ashvane" / "_internal" / "clipbot" / "dashboard" / "static"
    settings = load_settings()
    if (resolve_paths(settings).data / "supervisor" / "runtime" / "active.json").exists():
        raise RuntimeError("A runtime overlay is active; inspect its static pins before deployment")
    if not target.is_dir():
        raise RuntimeError("Installed dashboard directory is missing")
    fingerprint(source)
    names = list(dict.fromkeys([*args.assets, "index.html"]))
    changes = []
    for name in names:
        src, dst = source / name, target / name
        if not src.resolve().is_relative_to(source.resolve()) or not dst.resolve().is_relative_to(target.resolve()):
            raise ValueError("Asset escapes dashboard static directory")
        if not src.is_file() or src.is_symlink() or dst.is_symlink():
            raise ValueError("Expected ordinary static asset: " + name)
        changes.append((name, src, dst))
    backup = ROOT / "artifacts" / ("dashboard-backup-" + str(time.time_ns()))
    report = {"backup": str(backup), "assets": []}
    # index.html is last so all its fingerprinted dependencies are installed first.
    changes.sort(key=lambda change: change[0] == "index.html")
    for name, src, dst in changes:
        if dst.exists():
            original = backup / name
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dst, original)
        dst.parent.mkdir(parents=True, exist_ok=True)
        temp = dst.with_name(dst.name + ".ashvane-update")
        temp.write_bytes(src.read_bytes())
        temp.replace(dst)
    with httpx.Client(base_url=f"http://127.0.0.1:{settings.dashboard.port}", trust_env=False, timeout=15) as client:
        for name, src, dst in changes:
            digest = sha256(src.read_bytes()).hexdigest()
            response = client.get("/" if name == "index.html" else f"/static/{name}?v={digest[:16]}")
            response.raise_for_status()
            verified = sha256(response.content).hexdigest() == digest == sha256(dst.read_bytes()).hexdigest()
            report["assets"].append({"path": name, "sha256": digest, "served_verified": verified})
            if not verified:
                raise RuntimeError("Running app is not serving the installed bytes: " + name)
    (ROOT / "artifacts" / "dashboard-deployment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
