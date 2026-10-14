"""Frozen/source-overlay validation, import isolation, crash recovery and rollback."""
import hashlib
import importlib
import json
import stat
import sys
from pathlib import Path

import pytest

from clipbot import supervisor_bootstrap as B


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def reset_finder():
    B._uninstall()
    yield
    B._uninstall()
    for name in tuple(sys.modules):
        if name.startswith("clipbot.bootstrap_probe"):
            del sys.modules[name]


def candidate(tmp_path, files=None, name="candidate"):
    root = tmp_path / name
    files = files or {"clipbot/bootstrap_probe.py": b"value = 'verified'\n"}
    changes = []
    for relative, raw in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        changes.append({"path": relative, "after_sha256": digest(raw), "before_sha256": digest(b"")})
    return root, changes


def stage(tmp_path, files=None, version="v1", name="candidate"):
    root, changes = candidate(tmp_path, files, name)
    home = tmp_path / "home"
    result = B.stage_overlay(root, changes, home, version)
    return home, result


def pointer(home):
    return json.loads((home / "supervisor/runtime/active.json").read_text())


def make_writable(path):
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_stage_and_activation_never_execute_candidate_before_import(tmp_path):
    sentinel = tmp_path / "executed.txt"
    source = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\nvalue = 'verified'\n".encode()
    home, result = stage(tmp_path, {"clipbot/bootstrap_probe.py": source})
    assert result["status"] == "overlay_staged" and result["restart_required"]
    assert not sentinel.exists()
    paths = list(sys.path)
    assert B.activate_bootstrap(home)
    assert not sentinel.exists() and sys.path == paths
    module = importlib.import_module("clipbot.bootstrap_probe")
    assert module.value == "verified" and sentinel.read_text() == "executed"
    assert module.__file__ == str(Path(result["overlay"]) / "clipbot/bootstrap_probe.py")
    assert not (Path(result["overlay"]) / "clipbot/__pycache__").exists()
    B.mark_healthy(home)
    assert not (home / "supervisor/runtime/pending.json").exists()


def test_cumulative_snapshots_preserve_previous_modules_and_static_assets(tmp_path):
    home, first = stage(tmp_path, {"clipbot/bootstrap_probe_a.py": b"value='first'\n",
                                  "clipbot/dashboard/static/probe.css": b"body{color:red}"})
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe_b.py": b"value='second'\n"}, "second")
    second = B.stage_overlay(root, changes, home, "v2")
    assert second["files"] == 3 and pointer(home)["previous"]["version"] == "v1"
    assert B.activate_bootstrap(home)
    assert importlib.import_module("clipbot.bootstrap_probe_a").value == "first"
    assert importlib.import_module("clipbot.bootstrap_probe_b").value == "second"
    asset = B.overlay_resource("clipbot/dashboard/static/probe.css")
    assert asset.read_bytes() == b"body{color:red}" and str(asset).startswith(second["overlay"])
    assert B.overlay_resource("clipbot/dashboard/static/absent.css") is None
    assert Path(first["overlay"]).exists()


@pytest.mark.parametrize("relative", ["../private.py", "clipbot/../private.py", "clipbot//test.py",
    "C:/private.py", "clipbot\\secret.py", "clipbot/__init__.py", "clipbot/__main__.py",
    "clipbot/auth.py", "clipbot/Auth.py", "clipbot/secure.py", "clipbot/publishers/oauth.py",
    "clipbot/supervisor_changes.py", "clipbot/supervisor_sandbox.py", "clipbot/supervisor_bootstrap.py",
    "clipbot/supervisor_files.py", "clipbot/supervisor_extensions.py", "clipbot/supervisor_memory.py",
    "clipbot/settings.json", "clipbot/.env", "clipbot/dashboard/static/evil.py",
    "tests/test_skip.py", "clipbot/CON.py", "clipbot/probe.py.", "clipbot/probe.py "])
def test_private_protected_and_escaping_paths_cannot_stage(tmp_path, relative):
    root, _ = candidate(tmp_path)
    home = tmp_path / "home"
    with pytest.raises((ValueError, OSError)):
        B.stage_overlay(root, [{"path": relative, "after_sha256": digest(b"anything")}], home, "v1")
    assert not (home / "supervisor/runtime/active.json").exists()


@pytest.mark.parametrize("version", ["../escape", "/absolute", ".", "..", "v1/evil", "v1\\evil", "CON", "v1.", "v1:evil", "active.json", "pending.json", "manifest.json"])
def test_version_cannot_escape_runtime_storage(tmp_path, version):
    root, changes = candidate(tmp_path)
    with pytest.raises(ValueError):
        B.stage_overlay(root, changes, tmp_path / "home", version)


def test_changed_candidate_or_unpinned_candidate_fails_without_pointer(tmp_path):
    root, changes = candidate(tmp_path)
    (root / changes[0]["path"]).write_text("value='tampered'\n")
    with pytest.raises(ValueError, match="isolated proof"):
        B.stage_overlay(root, changes, tmp_path / "home", "v1")
    with pytest.raises(ValueError, match="unpinned"):
        B.stage_overlay(root, [{"path": changes[0]["path"]}], tmp_path / "home", "v1")


def test_syntax_error_never_stages_and_existing_version_is_immutable(tmp_path):
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"def broken(\n"})
    with pytest.raises(SyntaxError):
        B.stage_overlay(root, changes, tmp_path / "home", "v1")
    home, original = stage(tmp_path, name="valid")
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"value='replacement'\n"}, "next")
    with pytest.raises(ValueError, match="immutable"):
        B.stage_overlay(root, changes, home, "v1")
    assert (Path(original["overlay"]) / "clipbot/bootstrap_probe.py").read_text() == "value = 'verified'\n"


def test_tampered_source_is_rejected_before_any_import(tmp_path):
    home, result = stage(tmp_path)
    target = Path(result["overlay"]) / "clipbot/bootstrap_probe.py"
    make_writable(target)
    target.write_text("raise RuntimeError('untrusted code must never execute')\n")
    assert not B.activate_bootstrap(home)
    assert "clipbot.bootstrap_probe" not in sys.modules
    assert pointer(home)["active"] is None


def test_manifest_tamper_cannot_repin_arbitrary_source(tmp_path):
    home, result = stage(tmp_path)
    target = Path(result["overlay"]) / "manifest.json"
    make_writable(target)
    manifest = json.loads(target.read_text())
    manifest["files"]["clipbot/bootstrap_probe.py"]["sha256"] = "0" * 64
    target.write_text(json.dumps(manifest))
    assert not B.activate_bootstrap(home)
    assert pointer(home)["active"] is None


def test_loader_rechecks_module_hash_at_actual_execution(tmp_path):
    home, result = stage(tmp_path)
    assert B.activate_bootstrap(home)
    target = Path(result["overlay"]) / "clipbot/bootstrap_probe.py"
    make_writable(target)
    target.write_bytes(b"value = 'evilcode'\n")
    with pytest.raises((ImportError, ValueError)):
        importlib.import_module("clipbot.bootstrap_probe")
    assert "clipbot.bootstrap_probe" not in sys.modules


def test_unconfirmed_boot_falls_back_to_previous_overlay(tmp_path):
    home, _ = stage(tmp_path)
    assert B.activate_bootstrap(home)
    B.mark_healthy(home)
    B._uninstall()
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"value='second'\n"}, "next")
    B.stage_overlay(root, changes, home, "v2")
    assert B.activate_bootstrap(home)
    # Simulate process death before readiness: pending.json survives.
    B._uninstall()
    assert B.activate_bootstrap(home)
    assert pointer(home)["active"]["version"] == "v1"
    assert importlib.import_module("clipbot.bootstrap_probe").value == "verified"
    B.mark_healthy(home)


def test_unconfirmed_first_overlay_disables_overlay(tmp_path):
    home, _ = stage(tmp_path)
    assert B.activate_bootstrap(home)
    B._uninstall()
    assert not B.activate_bootstrap(home)
    assert pointer(home)["active"] is None
    assert not (home / "supervisor/runtime/pending.json").exists()


def test_mark_healthy_clears_only_own_active_boot_marker(tmp_path):
    home, _ = stage(tmp_path)
    assert B.activate_bootstrap(home)
    marker = home / "supervisor/runtime/pending.json"
    B.mark_healthy(tmp_path / "other")
    assert marker.exists()
    B.mark_healthy(home)
    assert not marker.exists()
    B._uninstall()
    assert B.activate_bootstrap(home)
    assert pointer(home)["active"]["version"] == "v1"


def test_rollback_is_current_version_only_and_keeps_source_versions(tmp_path):
    home, first = stage(tmp_path)
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"value='second'\n"}, "next")
    second = B.stage_overlay(root, changes, home, "v2")
    original_pointer = pointer(home)
    with pytest.raises(ValueError, match="conflict"):
        B.rollback_overlay(home, "v1")
    assert pointer(home) == original_pointer
    rolled = B.rollback_overlay(home, "v2")
    assert rolled["active"] == "v1" and rolled["restart_required"]
    assert Path(first["overlay"]).exists() and Path(second["overlay"]).exists()
    with pytest.raises(ValueError, match="conflict"):
        B.rollback_overlay(home, "v2")
    assert B.rollback_overlay(home, "v1")["active"] is None


def test_corrupted_latest_overlay_automatically_uses_valid_previous(tmp_path):
    home, _ = stage(tmp_path)
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"value='second'\n"}, "next")
    second = B.stage_overlay(root, changes, home, "v2")
    target = Path(second["overlay"]) / "clipbot/bootstrap_probe.py"
    make_writable(target)
    target.write_bytes(b"value='broken'\n")
    assert B.activate_bootstrap(home)
    assert pointer(home)["active"]["version"] == "v1"
    assert importlib.import_module("clipbot.bootstrap_probe").value == "verified"


def test_size_ceilings_fail_before_activation_or_staging(tmp_path, monkeypatch):
    root, changes = candidate(tmp_path)
    monkeypatch.setattr(B, "MAX_OVERLAY_BYTES", 2)
    with pytest.raises(ValueError, match="ceiling"):
        B.stage_overlay(root, changes, tmp_path / "home", "v1")
    monkeypatch.setattr(B, "MAX_OVERLAY_BYTES", 1024)
    home, _ = stage(tmp_path, name="safe")
    monkeypatch.setattr(B, "MAX_OVERLAY_BYTES", 2)
    assert not B.activate_bootstrap(home)


def test_case_collisions_and_duplicates_cannot_stage(tmp_path):
    root, changes = candidate(tmp_path)
    with pytest.raises(ValueError, match="Duplicate"):
        B.stage_overlay(root, changes + changes, tmp_path / "home", "v1")


def test_source_link_cannot_read_unrelated_host_file(tmp_path):
    root, changes = candidate(tmp_path)
    target = root / changes[0]["path"]
    target.unlink()
    private = tmp_path / "private.py"
    private.write_text("value='private'\n")
    try:
        target.symlink_to(private)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="links"):
        B.stage_overlay(root, changes, tmp_path / "home", "v1")


def test_finder_is_limited_to_manifest_and_config_import_is_deferred(tmp_path):
    home, _ = stage(tmp_path)
    before_config = sys.modules.get("clipbot.config")
    assert B.activate_bootstrap(home)
    finder = B._ACTIVE
    assert finder.find_spec("clipbot.auth") is None
    assert finder.find_spec("clipbot.some_unlisted_module") is None
    assert sys.modules.get("clipbot.config") is before_config
    with pytest.raises(ValueError, match="static"):
        B.overlay_resource("clipbot/bootstrap_probe.py")


def test_existing_import_prevents_false_activation_claim(tmp_path):
    home, _ = stage(tmp_path)
    sys.modules["clipbot.bootstrap_probe"] = object()
    assert not B.activate_bootstrap(home)
    assert not any(isinstance(finder, B._OverlayFinder) for finder in sys.meta_path)


def test_hardlinked_candidate_cannot_read_unrelated_host_source(tmp_path):
    root, changes = candidate(tmp_path)
    target = root / changes[0]["path"]
    target.unlink()
    private = tmp_path / "private.py"
    private.write_bytes(b"value='private'\n")
    import os
    try:
        os.link(private, target)
    except OSError:
        pytest.skip("Filesystem does not support hardlinks")
    changes[0]["after_sha256"] = digest(private.read_bytes())
    with pytest.raises(ValueError, match="Hard-linked"):
        B.stage_overlay(root, changes, tmp_path / "home", "v1")


def test_corrupt_pending_boot_marker_recovers_previous_version(tmp_path):
    home, _ = stage(tmp_path)
    root, changes = candidate(tmp_path, {"clipbot/bootstrap_probe.py": b"value='second'\n"}, "next")
    B.stage_overlay(root, changes, home, "v2")
    (home / "supervisor/runtime/pending.json").write_text("corrupted")
    assert B.activate_bootstrap(home)
    assert pointer(home)["active"]["version"] == "v1"


def test_overlay_finder_precedes_frozen_importer_without_widening_source_paths(tmp_path, monkeypatch):
    import importlib.abc
    import importlib.util
    class FrozenLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            module.value = "bundled"
    class FrozenFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "clipbot.bootstrap_probe":
                return importlib.util.spec_from_loader(fullname, FrozenLoader(), origin="frozen")
            return None
    frozen = FrozenFinder()
    sys.meta_path.insert(0, frozen)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        home, _ = stage(tmp_path)
        assert B.activate_bootstrap(home)
        assert sys.meta_path.index(B._ACTIVE) < sys.meta_path.index(frozen)
        assert importlib.import_module("clipbot.bootstrap_probe").value == "verified"
    finally:
        sys.meta_path.remove(frozen)


def test_unlisted_python_sidecar_is_never_importable_from_overlay(tmp_path):
    home, result = stage(tmp_path)
    sidecar = Path(result["overlay"]) / "clipbot/bootstrap_probe_sidecar.py"
    sidecar.write_text("raise RuntimeError('must not import this unlisted file')\n")
    assert B.activate_bootstrap(home)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("clipbot.bootstrap_probe_sidecar")
