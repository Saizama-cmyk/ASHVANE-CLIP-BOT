"""Install only the two official, digest-pinned Kokoro assets into the external cache.

Sources: github.com/thewh1teagle/kokoro-onnx release model-files-v1.1;
model and voices Apache-2.0; runtime MIT; bundled phonemizer/eSpeak GPL-3.0.
Models are downloaded once, never committed or silently replaced by another release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipbot.config import load_settings, resolve_paths

RELEASE = "https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases/tags/model-files-v1.1"
ASSETS = {
    "kokoro-v1.0.int8.onnx": (114119327, "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c"),
    "voices-v1.0.bin": (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}
CANONICAL = {"kokoro-v1.0.int8.onnx": "kokoro.onnx", "voices-v1.0.bin": "voices.bin"}
NOTICES = {
    "KOKORO-ONNX-MIT-LICENSE.txt": "https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/LICENSE",
    "KOKORO-MODEL-APACHE-LICENSE.txt": "https://raw.githubusercontent.com/hexgrad/kokoro/main/LICENSE",
    "KOKORO-MODEL-CARD.md": "https://huggingface.co/hexgrad/Kokoro-82M/raw/main/README.md",
    "ESPEAK-NG-GPL-LICENSE.txt": "https://raw.githubusercontent.com/espeak-ng/espeak-ng/master/COPYING",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def setup(target: Path) -> dict:
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(RELEASE)
        response.raise_for_status()
        assets = {item["name"]: item for item in response.json()["assets"]}
        for name, (size, expected) in ASSETS.items():
            asset = assets[name]
            if asset["size"] != size or asset.get("digest") != "sha256:" + expected:
                raise ValueError("Official release metadata changed; refusing unverified assets")
            url = asset["browser_download_url"]
            if not url.startswith("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"):
                raise ValueError("Unexpected model download origin")
            output = target / CANONICAL[name]
            if output.is_file() and output.stat().st_size == size and digest(output) == expected:
                continue
            temporary = output.with_suffix(output.suffix + ".part")
            try:
                received = 0
                with client.stream("GET", url) as download, temporary.open("wb") as stream:
                    download.raise_for_status()
                    for chunk in download.iter_bytes(1024 * 1024):
                        received += len(chunk)
                        if received > size:
                            raise ValueError("Model exceeds its verified release size")
                        stream.write(chunk)
                if received != size or digest(temporary) != expected:
                    raise ValueError("Model download checksum verification failed")
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
        for name, url in NOTICES.items():
            notice = client.get(url)
            notice.raise_for_status()
            (target / name).write_text(notice.text, encoding="utf-8")
    result = {"release": RELEASE, "model_path": str(target / "kokoro.onnx"),
              "voices_path": str(target / "voices.bin"),
              "sha256": {name: expected for name, (_, expected) in ASSETS.items()}}
    (target / "verified-assets.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (target / "SOURCES.txt").write_text(
        "Model and voice assets: " + RELEASE + "\n"
        "Kokoro runtime: https://github.com/thewh1teagle/kokoro-onnx/tree/v0.6.1\n"
        "Phonemizer: https://github.com/bootphon/phonemizer/tree/v3.4.0\n"
        "eSpeak loader: https://github.com/thewh1teagle/espeakng-loader\n"
        "eSpeak NG: https://github.com/espeak-ng/espeak-ng\n"
        "SoundFile: https://github.com/bastibe/python-soundfile\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    paths = resolve_paths(load_settings())
    target = args.target or (paths.models or paths.data / "models") / "stories"
    print(json.dumps(setup(target), indent=2))
