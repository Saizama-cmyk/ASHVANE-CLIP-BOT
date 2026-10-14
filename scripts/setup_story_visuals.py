"""Install verified open model weights for Hollow into an operator-selected folder.

Uses the existing ComfyUI Python environment; never installs packages or paid APIs.
Downloads are resumable and SHA-256 verified against the primary model repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx

MODELS = {
    "illustrations": [
        ("black-forest-labs/FLUX.2-klein-4b-fp8", "flux-2-klein-4b-fp8.safetensors", "diffusion_models"),
        ("Comfy-Org/vae-text-encorder-for-flux-klein-4b", "split_files/text_encoders/qwen_3_4b.safetensors", "text_encoders"),
        ("Comfy-Org/vae-text-encorder-for-flux-klein-4b", "split_files/vae/flux2-vae.safetensors", "vae"),
    ],
    "motion": [
        ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", "diffusion_models"),
        ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders"),
        ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/vae/wan2.2_vae.safetensors", "vae"),
    ],
}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def download(root, spec, connections):
    repo, source, category = spec
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(f"https://huggingface.co/api/models/{repo}/tree/main", params={"recursive": "true", "expand": "true"})
        response.raise_for_status()
        metadata = next(row for row in response.json() if row["path"] == source)
        size, expected = metadata["size"], metadata["lfs"]["oid"]
        target = root / category / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_size == size and digest(target) == expected:
            print(f"Verified existing {target.name}", flush=True)
        else:
            partial = target.with_suffix(target.suffix + ".part")
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > size:
                raise ValueError(f"Oversized partial download: {partial}")
            url = f"https://huggingface.co/{repo}/resolve/main/{source}"
            if offset < size and connections > 1:
                # Independent, verified byte ranges accelerate public model downloads.
                # Keep the original contiguous prefix intact so interrupted installs resume.
                start = offset
                span = (size - start + connections - 1) // connections
                ranges = [(a, min(size - 1, a + span - 1)) for a in range(start, size, span)]

                def fetch_range(bounds):
                    first, last = bounds
                    chunk_path = partial.with_name(partial.name + f".{first}-{last}")
                    length = last - first + 1
                    have = chunk_path.stat().st_size if chunk_path.exists() else 0
                    if have > length:
                        raise ValueError("Oversized range download")
                    if have < length:
                        with httpx.stream("GET", url, headers={"Range": f"bytes={first + have}-{last}"}, follow_redirects=True, timeout=120) as media:
                            media.raise_for_status()
                            expected_range = f"bytes {first + have}-{last}/{size}"
                            if media.status_code != 206 or media.headers.get("content-range") != expected_range:
                                raise ValueError("Model host did not honor the requested byte range")
                            with chunk_path.open("ab") as output:
                                for chunk in media.iter_bytes(1024 * 1024):
                                    have += len(chunk)
                                    if have > length:
                                        raise ValueError("Model range exceeds expected size")
                                    output.write(chunk)
                    if have != length:
                        raise ValueError("Incomplete model range")
                    print(f"{target.name}: range {first}-{last} complete", flush=True)
                    return chunk_path

                print(f"Downloading {target.name}: {size / 1e9:.2f} GB, {connections} ranges", flush=True)
                with ThreadPoolExecutor(max_workers=connections) as ranges_pool:
                    chunks = list(ranges_pool.map(fetch_range, ranges))
                with partial.open("ab") as output:
                    for chunk_path in chunks:
                        with chunk_path.open("rb") as chunk_file:
                            for chunk in iter(lambda: chunk_file.read(8 * 1024 * 1024), b""):
                                output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                        chunk_path.unlink()
            elif offset < size:
                with client.stream("GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}) as media:
                    media.raise_for_status()
                    if offset and media.status_code != 206:
                        offset = 0
                    print(f"Downloading {target.name}: {size / 1e9:.2f} GB", flush=True)
                    report = offset // 1_000_000_000
                    with partial.open("ab" if offset else "wb") as output:
                        for chunk in media.iter_bytes(1024 * 1024):
                            output.write(chunk)
                            offset += len(chunk)
                            if offset > size:
                                raise ValueError("Download exceeds primary repository size")
                            if offset // 1_000_000_000 > report:
                                report = offset // 1_000_000_000
                                print(f"{target.name}: {offset / size:.0%}", flush=True)
            if partial.stat().st_size != size or digest(partial) != expected:
                raise ValueError(f"Model integrity check failed: {partial}")
            partial.replace(target)
            print(f"Verified {target.name}", flush=True)
        return {"repository": repo, "source": source, "path": str(target), "bytes": size, "sha256": expected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--mode", choices=["illustrations", "motion", "both"], default="illustrations")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--connections", type=int, default=8)
    args = parser.parse_args()
    root = args.models.resolve()
    specs = sum((value for key, value in MODELS.items() if args.mode in (key, "both")), [])
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda spec: download(root, spec, args.connections), specs))
    (root / f"hollow-{args.mode}-models.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("Model installation verified.", flush=True)


if __name__ == "__main__":
    main()
