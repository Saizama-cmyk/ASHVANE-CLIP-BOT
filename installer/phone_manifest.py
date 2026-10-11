"""Read an IPA's installation and AltStore metadata without extracting or signing it.

XML code-signing entitlements are supported in thin/fat, little/big-endian Mach-O.
DER-only entitlements fail explicitly rather than being reported as absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import struct
from pathlib import Path
from zipfile import ZipFile


class ManifestError(ValueError):
    """An IPA is malformed or cannot be inspected reliably."""


def _bounds(data: bytes, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise ManifestError("Mach-O data extends outside its file")
    return data[offset:offset + length]


def _signature_entitlements(blob: bytes) -> tuple[dict, bool]:
    if len(blob) < 12:
        raise ManifestError("Truncated code signature")
    magic, length, count = struct.unpack_from(">III", blob)
    if magic != 0xFADE0CC0 or length > len(blob) or length < 12 + count * 8:
        raise ManifestError("Invalid embedded code-signature container")
    blob = blob[:length]
    found = None
    der = False
    for index in range(count):
        kind, offset = struct.unpack_from(">II", blob, 12 + index * 8)
        header = _bounds(blob, offset, 8)
        child_magic, child_length = struct.unpack(">II", header)
        if child_length < 8:
            raise ManifestError("Invalid code-signature child length")
        child = _bounds(blob, offset, child_length)
        if kind == 5 or child_magic == 0xFADE7171:
            if child_magic != 0xFADE7171:
                raise ManifestError("Unexpected XML entitlement blob type")
            try:
                value = plistlib.loads(child[8:])
            except Exception as exc:
                raise ManifestError("Invalid embedded entitlement plist") from exc
            if not isinstance(value, dict):
                raise ManifestError("Entitlements must be a dictionary")
            if found is not None and found != value:
                raise ManifestError("Conflicting embedded entitlement dictionaries")
            found = value
        if kind == 7 or child_magic == 0xFADE7172:
            der = True
    if found is None and der:
        raise ManifestError("DER-only entitlements are unsupported; inspect with codesign on macOS")
    return (found or {}), found is not None


def macho_entitlements(data: bytes) -> tuple[dict, bool]:
    """Return (entitlement values, entitlement blob present); unsigned is ({}, False)."""
    magic = _bounds(data, 0, 4)
    fat_formats = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
                   b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    if magic in fat_formats:
        endian, wide = fat_formats[magic]
        count = struct.unpack(endian + "I", _bounds(data, 4, 4))[0]
        stride = 32 if wide else 20
        _bounds(data, 8, count * stride)
        results = []
        for index in range(count):
            entry = 8 + index * stride
            offset, length = struct.unpack_from(endian + ("QQ" if wide else "II"), data, entry + 8)
            results.append(macho_entitlements(_bounds(data, offset, length)))
        if not results or any(result != results[0] for result in results[1:]):
            raise ManifestError("Fat Mach-O has no slices or inconsistent slice entitlements")
        return results[0]
    thin_formats = {b"\xce\xfa\xed\xfe": ("<", 28), b"\xcf\xfa\xed\xfe": ("<", 32),
                    b"\xfe\xed\xfa\xce": (">", 28), b"\xfe\xed\xfa\xcf": (">", 32)}
    if magic not in thin_formats:
        raise ManifestError("Executable is not Mach-O")
    endian, header_size = thin_formats[magic]
    _bounds(data, 0, header_size)
    count, commands_size = struct.unpack_from(endian + "II", data, 16)
    _bounds(data, header_size, commands_size)
    offset = header_size
    signatures = []
    for _ in range(count):
        command, size = struct.unpack(endian + "II", _bounds(data, offset, 8))
        if size < 8 or offset + size > header_size + commands_size:
            raise ManifestError("Invalid Mach-O load-command size")
        if command == 0x1D:  # LC_CODE_SIGNATURE
            if size < 16:
                raise ManifestError("Truncated LC_CODE_SIGNATURE")
            start, length = struct.unpack_from(endian + "II", data, offset + 8)
            signatures.append(_signature_entitlements(_bounds(data, start, length)))
        offset += size
    if offset != header_size + commands_size or len(signatures) > 1:
        raise ManifestError("Inconsistent Mach-O load-command table")
    return signatures[0] if signatures else ({}, False)


def _read(archive: ZipFile, name: str, maximum: int) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ManifestError(f"Missing IPA member: {name}") from exc
    if info.file_size > maximum:
        raise ManifestError(f"IPA member is too large to inspect: {name}")
    return archive.read(info)


def inspect_ipa(path: str | Path) -> dict:
    """Return artifact-derived metadata, component entitlements and appPermissions."""
    path = Path(path)
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ManifestError("IPA contains duplicate member names")
        main = [name for name in names if name.startswith("Payload/") and name.endswith(".app/Info.plist")
                and len(name.split("/")) == 3]
        if len(main) != 1:
            raise ManifestError("IPA must contain exactly one main Payload app")
        root = main[0].rsplit("/", 1)[0]
        components = [main[0]] + sorted(name for name in names if name.startswith(root + "/PlugIns/")
                                      and name.endswith(".appex/Info.plist"))
        privacy: dict[str, str] = {}
        all_entitlements: dict[str, list] = {}
        records = []
        main_info = None
        for member in components:
            try:
                info = plistlib.loads(_read(archive, member, 4 * 1024 * 1024))
            except ManifestError:
                raise
            except Exception as exc:
                raise ManifestError(f"Invalid plist: {member}") from exc
            if not isinstance(info, dict):
                raise ManifestError(f"Info.plist must be a dictionary: {member}")
            if main_info is None:
                main_info = info
            executable = info.get("CFBundleExecutable")
            if not isinstance(executable, str) or not executable or "/" in executable or "\\" in executable or executable in (".", ".."):
                raise ManifestError(f"Invalid CFBundleExecutable: {member}")
            entitlements, present = macho_entitlements(_read(archive, member.rsplit("/", 1)[0] + "/" + executable,
                                                           256 * 1024 * 1024))
            for key, value in info.items():
                if key.startswith("NS") and "UsageDescription" in key:
                    if not isinstance(value, str):
                        raise ManifestError(f"Privacy usage description is not text: {key}")
                    if key in privacy and privacy[key] != value:
                        privacy[key] = privacy[key] + "\n" + value
                    else:
                        privacy[key] = value
            for key, value in entitlements.items():
                all_entitlements.setdefault(key, []).append(value)
            records.append({"path": member.rsplit("/", 1)[0], "bundleIdentifier": info.get("CFBundleIdentifier"),
                            "entitlementsPresent": present, "entitlements": entitlements,
                            "privacy": {key: value for key, value in info.items()
                                        if key.startswith("NS") and "UsageDescription" in key}})
        required = ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion", "MinimumOSVersion")
        if any(not isinstance(main_info.get(key), str) or not main_info[key] for key in required):
            raise ManifestError("IPA main Info.plist is missing required installation metadata")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    standard = {"application-identifier", "com.apple.developer.team-identifier"}
    return {"bundleIdentifier": main_info["CFBundleIdentifier"], "version": main_info["CFBundleShortVersionString"],
            "buildVersion": main_info["CFBundleVersion"], "minOSVersion": main_info["MinimumOSVersion"],
            "size": path.stat().st_size, "sha256": digest, "components": records,
            "entitlementTypes": {key: sorted({type(value).__name__ for value in values})
                                 for key, values in sorted(all_entitlements.items())},
            "appPermissions": {"entitlements": sorted(set(all_entitlements) - standard),
                               "privacy": dict(sorted(privacy.items()))}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path, nargs="?")
    parser.add_argument("--ipa", type=Path, dest="ipa_option")
    parser.add_argument("--output", "--report", type=Path, dest="output")
    args = parser.parse_args()
    if bool(args.ipa) == bool(args.ipa_option):
        parser.error("provide one IPA path, either positional or --ipa")
    output = json.dumps(inspect_ipa(args.ipa or args.ipa_option), indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
