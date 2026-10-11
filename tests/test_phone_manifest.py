"""Inspect real artifact structures, including negative controls for missing/malformed data."""
import hashlib
import plistlib
import struct
from zipfile import ZipFile

import pytest

from installer.phone_manifest import ManifestError, inspect_ipa, macho_entitlements


def signature(entitlements, *, der_only=False):
    payload = b"DER" if der_only else plistlib.dumps(entitlements)
    child = struct.pack(">II", 0xFADE7172 if der_only else 0xFADE7171, len(payload) + 8) + payload
    return struct.pack(">III", 0xFADE0CC0, 20 + len(child), 1) + struct.pack(">II", 7 if der_only else 5, 20) + child


def thin(entitlements=None, *, endian="<", wide=True, der_only=False):
    magic = 0xFEEDFACF if wide else 0xFEEDFACE
    blob = signature(entitlements, der_only=der_only) if entitlements is not None or der_only else b""
    header_size = 32 if wide else 28
    header = struct.pack(endian + "IIIIIII", magic, 0x100000C, 0, 2, int(bool(blob)), 16 if blob else 0, 0)
    if wide:
        header += struct.pack(endian + "I", 0)
    command = struct.pack(endian + "IIII", 0x1D, 16, header_size + 16, len(blob)) if blob else b""
    return header + command + blob


def fat(slices, *, endian=">", wide=False):
    stride = 32 if wide else 20
    offset = 8 + len(slices) * stride
    entries = []
    for content in slices:
        entries.append(struct.pack(endian + ("IIQQII" if wide else "IIIII"),
                                   0x100000C, 0, offset, len(content), 0, *([0] if wide else [])))
        offset += len(content)
    return struct.pack(endian + "II", 0xCAFEBABF if wide else 0xCAFEBABE, len(slices)) + b"".join(entries + slices)


def info(**extra):
    return {"CFBundleIdentifier": "app.ashvane.mobile", "CFBundleExecutable": "Ashvane", "CFBundleShortVersionString": "1.0.21",
            "CFBundleVersion": "21", "MinimumOSVersion": "15.1", "NSLocalNetworkUsageDescription": "Connect to your PC.", **extra}


def ipa(tmp_path, main_info=None, binary=None, extension=None):
    output = tmp_path / "Ashvane.ipa"
    with ZipFile(output, "w") as archive:
        archive.writestr("Payload/Ashvane.app/Info.plist", plistlib.dumps(main_info or info(), fmt=plistlib.FMT_BINARY))
        archive.writestr("Payload/Ashvane.app/Ashvane", binary if binary is not None else thin())
        if extension:
            archive.writestr("Payload/Ashvane.app/PlugIns/Share.appex/Info.plist", plistlib.dumps(extension[0]))
            archive.writestr("Payload/Ashvane.app/PlugIns/Share.appex/Share", extension[1])
    return output


@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("wide", [False, True])
def test_thin_embedded_entitlements(endian, wide):
    values = {"com.apple.developer.kernel.increased-memory-limit": True, "keychain-access-groups": ["TEAM.app.ashvane.mobile"]}
    assert macho_entitlements(thin(values, endian=endian, wide=wide)) == (values, True)
    assert macho_entitlements(thin(endian=endian, wide=wide)) == ({}, False)


@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("wide", [False, True])
def test_fat_embedded_entitlements(endian, wide):
    values = {"memory": True}
    assert macho_entitlements(fat([thin(values), thin(values, endian=">")], endian=endian, wide=wide)) == (values, True)


def test_unsigned_ipa_does_not_invent_config_entitlements(tmp_path):
    path = ipa(tmp_path)
    manifest = inspect_ipa(path)
    assert manifest["bundleIdentifier"] == "app.ashvane.mobile"
    assert manifest["version"] == "1.0.21" and manifest["buildVersion"] == "21"
    assert manifest["minOSVersion"] == "15.1"
    assert manifest["size"] == path.stat().st_size
    assert manifest["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["components"][0]["entitlementsPresent"] is False
    assert manifest["appPermissions"] == {"entitlements": [], "privacy": {"NSLocalNetworkUsageDescription": "Connect to your PC."}}


def test_signed_ipa_collects_extension_permissions_and_types(tmp_path):
    memory = "com.apple.developer.kernel.increased-memory-limit"
    extension = (info(CFBundleIdentifier="app.ashvane.mobile.share", CFBundleExecutable="Share",
                      NSLocalNetworkUsageDescription="Share with the PC.", NSPhotoLibraryUsageDescription="Choose a photo."),
                 thin({"com.apple.security.application-groups": ["group.app.ashvane"]}))
    path = ipa(tmp_path, binary=thin({memory: True, "application-identifier": "TEAM.app", "com.apple.developer.team-identifier": "TEAM"}), extension=extension)
    manifest = inspect_ipa(path)
    assert manifest["appPermissions"]["entitlements"] == [memory, "com.apple.security.application-groups"]
    assert manifest["appPermissions"]["privacy"]["NSPhotoLibraryUsageDescription"] == "Choose a photo."
    assert "Share with the PC." in manifest["appPermissions"]["privacy"]["NSLocalNetworkUsageDescription"]
    assert manifest["entitlementTypes"][memory] == ["bool"]
    assert len(manifest["components"]) == 2 and all(component["entitlementsPresent"] for component in manifest["components"])


def test_malformed_and_der_only_signatures_fail_explicitly():
    with pytest.raises(ManifestError, match="DER-only"):
        macho_entitlements(thin(der_only=True))
    with pytest.raises(ManifestError, match="inconsistent"):
        macho_entitlements(fat([thin({"memory": True}), thin()]))
    corrupt = bytearray(thin({"memory": True}))
    struct.pack_into("<I", corrupt, 40, 999999)  # Signature offset outside executable.
    with pytest.raises(ManifestError, match="outside"):
        macho_entitlements(bytes(corrupt))
    with pytest.raises(ManifestError, match="Mach-O"):
        macho_entitlements(b"not an executable")


def test_missing_installation_metadata_and_unsafe_executable_fail(tmp_path):
    broken = info()
    del broken["CFBundleVersion"]
    with pytest.raises(ManifestError, match="required installation metadata"):
        inspect_ipa(ipa(tmp_path, main_info=broken))
    with pytest.raises(ManifestError, match="CFBundleExecutable"):
        inspect_ipa(ipa(tmp_path, main_info=info(CFBundleExecutable="../elsewhere")))


def test_ipa_rejects_ambiguous_main_apps(tmp_path):
    path = ipa(tmp_path)
    with ZipFile(path, "a") as archive:
        archive.writestr("Payload/Other.app/Info.plist", plistlib.dumps(info()))
    with pytest.raises(ManifestError, match="exactly one"):
        inspect_ipa(path)
