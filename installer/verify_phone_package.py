"""Check an iPhone sideload package before exposing it as a downloadable build."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import zipfile


def _has_arm64(header: bytes) -> bool:
    if len(header) < 8:
        return False
    if header[:4] == b"\xcf\xfa\xed\xfe":
        return struct.unpack_from("<I", header, 4)[0] == 0x0100000C
    if header[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        count = struct.unpack_from(">I", header, 4)[0]
        stride = 32 if header[:4] == b"\xca\xfe\xba\xbf" else 20
        return any(offset + 4 <= len(header) and struct.unpack_from(">I", header, offset)[0] == 0x0100000C
                   for offset in range(8, 8 + count * stride, stride))
    return False


def verify_ipa(path: Path, version: str, build_number: str, bundle_id: str = "app.ashvane.mobile") -> dict:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Corrupt package member: {bad_member}")
        infos = [name for name in archive.namelist()
                 if name.startswith("Payload/") and name.endswith(".app/Info.plist") and name.count("/") == 2]
        if len(infos) != 1:
            raise ValueError("Package must contain exactly one root iPhone app")
        info = plistlib.loads(archive.read(infos[0]))
        expected = {"CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": version,
                    "CFBundleVersion": build_number}
        for key, value in expected.items():
            if info.get(key) != value:
                raise ValueError(f"{key} differs from the advertised build: {info.get(key)!r} != {value!r}")
        if "iPhoneOS" not in info.get("CFBundleSupportedPlatforms", []):
            raise ValueError("Package is not an iPhone device build")
        executable = info.get("CFBundleExecutable")
        if not isinstance(executable, str) or not executable or "/" in executable or "\\" in executable:
            raise ValueError("Package has no valid app executable")
        binary = infos[0].rsplit("/", 1)[0] + "/" + executable
        if binary not in archive.namelist():
            raise ValueError("App executable is missing")
        bundle = infos[0].rsplit("/", 1)[0] + "/main.jsbundle"
        if bundle not in archive.namelist() or archive.getinfo(bundle).file_size == 0:
            raise ValueError("Release JavaScript bundle is missing or empty")
        with archive.open(binary) as stream:
            if not _has_arm64(stream.read(4096)):
                raise ValueError("App executable has no arm64 device architecture")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": path.name, "size": path.stat().st_size,
            "sha256": digest,
            "bundle_id": bundle_id, "version": version, "build_number": build_number,
            "minimum_ios": info.get("MinimumOSVersion"), "arm64": True, "javascript_bundle": True,
            "installation": "Unsigned package; sign with your existing sideloader before installing."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-number", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify_ipa(args.ipa, args.version, args.build_number)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
