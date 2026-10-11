import plistlib
import struct
import zipfile

import pytest

from installer.verify_phone_package import verify_ipa
from installer.altstore_source import source


def package(tmp_path, *, javascript=b"bundled app", **changes):
    path = tmp_path / "Ashvane.ipa"
    info = {"CFBundleIdentifier": "app.ashvane.mobile", "CFBundleShortVersionString": "1.0.21",
            "CFBundleVersion": "21", "CFBundleExecutable": "Ashvane",
            "CFBundleSupportedPlatforms": ["iPhoneOS"], "MinimumOSVersion": "15.1", **changes}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Payload/Ashvane.app/Info.plist", plistlib.dumps(info))
        archive.writestr("Payload/Ashvane.app/Ashvane", b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + b"\0" * 32)
        if javascript is not None:
            archive.writestr("Payload/Ashvane.app/main.jsbundle", javascript)
    return path


def test_phone_package_matches_feed_and_device(tmp_path):
    result = verify_ipa(package(tmp_path), "1.0.21", "21")
    assert result["arm64"] and result["minimum_ios"] == "15.1" and len(result["sha256"]) == 64


@pytest.mark.parametrize("changes", [{"CFBundleShortVersionString": "1.0.20"},
                                    {"CFBundleVersion": "20"}, {"CFBundleIdentifier": "wrong.app"},
                                    {"CFBundleSupportedPlatforms": ["iPhoneSimulator"]},
                                    {"CFBundleExecutable": "Missing"}])
def test_wrong_or_uninstallable_phone_package_is_held(tmp_path, changes):
    with pytest.raises(ValueError):
        verify_ipa(package(tmp_path, **changes), "1.0.21", "21")


@pytest.mark.parametrize("javascript", [None, b""])
def test_phone_package_without_release_javascript_is_held(tmp_path, javascript):
    with pytest.raises(ValueError, match="JavaScript bundle"):
        verify_ipa(package(tmp_path, javascript=javascript), "1.0.21", "21")


def test_altstore_feed_matches_real_package_and_permissions():
    permissions = {"entitlements": [], "privacy": {"NSLocalNetworkUsageDescription": "Connect to your PC."}}
    manifest = {"version": "1.0.21", "bundleIdentifier": "app.ashvane.mobile", "size": 123,
                "buildVersion": "21", "minOSVersion": "15.1", "appPermissions": permissions}
    url = "https://github.com/example/repo/releases/download/phone-v1.0.21/Ashvane.ipa"
    app = source("example/repo", "phone-v1.0.21", url, 123, manifest)["apps"][0]
    assert app["versions"][0]["buildVersion"] == "21"
    assert app["versions"][0]["downloadURL"] == url and app["appPermissions"] == permissions
    with pytest.raises(ValueError):
        source("example/repo", "phone-v1.0.22", url, 123, manifest)
    with pytest.raises(ValueError):
        source("example/repo", "phone-v1.0.21", url, 124, manifest)
