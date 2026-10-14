"""Source capabilities, immutable promotion checks and conflict-aware recovery."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipbot.supervisor_changes import SourceChanges, digest, source_path


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "clipbot").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "clipbot" / "sample.py").write_text("def value(): return 1\n")
    (root / "clipbot" / "second.py").write_text("def second(): return 1\n")
    (root / "clipbot" / "auth.py").write_text("# protected account boundary\n")
    (root / "tests" / "test_original.py").write_text("def test_original(): assert True\n")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    cfg = SimpleNamespace(source_root=str(root), max_source_bytes=1048576, max_text_chars=1000,
                          max_patch_files=3, response_max_bytes=4096)
    service = SourceChanges(SimpleNamespace(supervisor=cfg), tmp_path / "workspace")
    return root, service


def edit(root, name="sample.py", text="def value(): return 2\n"):
    path = root / "clipbot" / name
    return {"path": "clipbot/" + name, "content": text,
            "before_sha256": digest(path.read_bytes() if path.exists() else b"")}


def stage(tmp_path, root, service, edits=None):
    job = tmp_path / "job"
    service.stage(job, edits if edits is not None else [edit(root)])
    return job


@pytest.mark.parametrize("path", ["../private.py", "/clipbot/sample.py", "C:/private.py", "clipbot\\sample.py",
    "clipbot/../sample.py", "settings.json", "clipbot/settings.json", "private/file.py",
    "tests/test_original.py", "requirements.txt", "clipbot/auth.py", "clipbot/supervisor_sandbox.py"])
def test_edit_capability_rejects_escape_credentials_tests_and_trust_boundary(checkout, path):
    root, _ = checkout
    with pytest.raises(ValueError):
        source_path(root, path, edit=True)


@pytest.mark.parametrize("path", ["./clipbot/auth.py", "clipbot/./auth.py", "clipbot/auth.py/",
                                 "clipbot/AUTH.py", "clipbot/./supervisor_changes.py"])
def test_normalized_or_windows_case_variant_cannot_bypass_protected_path(checkout, path):
    root, _ = checkout
    with pytest.raises(ValueError):
        source_path(root, path, edit=True)


def test_stage_keeps_checkout_and_immutable_baseline_unchanged(tmp_path, checkout):
    root, service = checkout
    original = (root / "clipbot" / "sample.py").read_bytes()
    job = stage(tmp_path, root, service)
    assert (root / "clipbot" / "sample.py").read_bytes() == original
    assert (job / "baseline" / "clipbot" / "sample.py").read_bytes() == original
    assert (job / "candidate" / "clipbot" / "sample.py").read_text() == "def value(): return 2\n"
    assert (job / "baseline" / "tests" / "test_original.py").read_bytes() == (root / "tests" / "test_original.py").read_bytes()
    manifest = json.loads((job / "changes.json").read_text())
    assert manifest[0]["before_sha256"] == digest(original)
    assert manifest[0]["after_sha256"] == digest((job / "candidate" / "clipbot" / "sample.py").read_bytes())


def test_inventory_prunes_generated_dependencies_before_budget_but_keeps_source_assets(checkout):
    root, service = checkout
    service.settings.supervisor.max_source_bytes = 1000
    for relative in ("phone/node_modules/package", "phone/.expo/cache", "art/out_pets", "art/out_ui",
                     "art/out_icons", "art/out_ashvane", "clipbot/__pycache__"):
        folder = root / relative
        folder.mkdir(parents=True)
        (folder / "generated.py").write_bytes(b"#" * 1001)
    for relative, content in (("art/original.py", b"# original artwork source"),
                              ("clipbot/dashboard/static/mark.png", b"original asset"),
                              ("docs/public-license.json", b'{"license":"AGPL-3.0"}')):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    paths = {row["path"] for row in service.inventory()}
    assert {"art/original.py", "clipbot/dashboard/static/mark.png", "docs/public-license.json"} <= paths
    assert not any("node_modules" in path or ".expo" in path or "out_" in path or "__pycache__" in path for path in paths)


@pytest.mark.parametrize("case", ["stale", "duplicate", "oversized", "syntax", "private_call"])
def test_invalid_candidate_is_not_applied(tmp_path, checkout, case):
    root, service = checkout
    original = (root / "clipbot" / "sample.py").read_bytes()
    edits = [edit(root)]
    if case == "stale":
        edits[0]["before_sha256"] = "0" * 64
    elif case == "duplicate":
        edits += [edit(root)]
    elif case == "oversized":
        edits[0]["content"] = "#" * (service.settings.supervisor.response_max_bytes + 1)
    elif case == "syntax":
        edits[0]["content"] = "def broken("
    else:
        edits[0]["content"] = "import os\ndef value(): return os.getenv('PRIVATE_TOKEN')\n"
    with pytest.raises((ValueError, SyntaxError)):
        service.stage(tmp_path / "job", edits)
    assert (root / "clipbot" / "sample.py").read_bytes() == original
    assert not (tmp_path / "job" / "changes.json").exists()


def test_fragment_edit_requires_one_exact_match(tmp_path, checkout):
    root, service = checkout
    change = edit(root)
    change.pop("content")
    change.update(search="return 1", replacement="return 2")
    job = stage(tmp_path, root, service, [change])
    assert "return 2" in (job / "candidate" / "clipbot" / "sample.py").read_text()
    bad = edit(root)
    bad.pop("content")
    bad.update(search="missing source fragment", replacement="return 3")
    with pytest.raises(ValueError, match="exact"):
        service.stage(tmp_path / "bad-job", [bad])


@pytest.mark.parametrize("checks,review", [({"passed": False}, {"passed": True}),
    ({"passed": True}, {"passed": False}), ({"passed": 1}, {"passed": True}),
    ({"passed": True}, {"passed": "true"}), ({}, {})])
def test_promotion_requires_actual_independent_pass_booleans(tmp_path, checkout, checks, review):
    root, service = checkout
    original = (root / "clipbot" / "sample.py").read_bytes()
    job = stage(tmp_path, root, service)
    with pytest.raises(ValueError):
        service.promote(job, checks=checks, review=review)
    assert (root / "clipbot" / "sample.py").read_bytes() == original
    assert not (job / "promotion.json").exists()


@pytest.mark.parametrize("where", ["checkout", "candidate"])
def test_promotion_refuses_owner_edit_or_candidate_tampering_before_any_write(tmp_path, checkout, where):
    root, service = checkout
    first = (root / "clipbot" / "sample.py").read_bytes()
    job = stage(tmp_path, root, service, [edit(root), edit(root, "second.py", "def second(): return 2\n")])
    folder = root if where == "checkout" else job / "candidate"
    (folder / "clipbot" / "second.py").write_text("# concurrent edit\n")
    with pytest.raises(ValueError, match="changed"):
        service.promote(job, checks={"passed": True}, review={"passed": True})
    assert (root / "clipbot" / "sample.py").read_bytes() == first
    assert not (job / "promotion.json").exists()


def test_successful_promotion_rollback_restores_existing_and_removes_new_file(tmp_path, checkout):
    root, service = checkout
    original = (root / "clipbot" / "sample.py").read_bytes()
    job = stage(tmp_path, root, service, [edit(root), edit(root, "new_module.py", "NEW = True\n")])
    applied = service.promote(job, checks={"passed": True}, review={"passed": True})
    assert applied["restart_required"] and applied["status"] == "source_applied"
    assert (root / "clipbot" / "new_module.py").exists()
    assert service.rollback(job)["status"] == "rolled_back"
    assert (root / "clipbot" / "sample.py").read_bytes() == original
    assert not (root / "clipbot" / "new_module.py").exists()


def test_rollback_preserves_concurrent_owner_edit_without_partial_restoration(tmp_path, checkout):
    root, service = checkout
    job = stage(tmp_path, root, service, [edit(root), edit(root, "second.py", "def second(): return 2\n")])
    service.promote(job, checks={"passed": True}, review={"passed": True})
    (root / "clipbot" / "second.py").write_text("# owner's subsequent work\n")
    with pytest.raises(ValueError, match="Rollback conflict"):
        service.rollback(job)
    assert (root / "clipbot" / "sample.py").read_text() == "def value(): return 2\n"
    assert (root / "clipbot" / "second.py").read_text() == "# owner's subsequent work\n"


def test_rollback_rejects_corrupt_baseline_before_restoring_any_file(tmp_path, checkout):
    root, service = checkout
    job = stage(tmp_path, root, service)
    service.promote(job, checks={"passed": True}, review={"passed": True})
    (job / "baseline" / "clipbot" / "sample.py").write_text("# corrupt baseline\n")
    with pytest.raises(ValueError, match="(?i)baseline|snapshot|digest|hash|changed"):
        service.rollback(job)
    assert (root / "clipbot" / "sample.py").read_text() == "def value(): return 2\n"


def test_partial_apply_failure_recovers_all_files_and_records_rollback(tmp_path, checkout, monkeypatch):
    import clipbot.supervisor_changes as module
    root, service = checkout
    original = {name: (root / "clipbot" / name).read_bytes() for name in ("sample.py", "second.py")}
    job = stage(tmp_path, root, service, [edit(root), edit(root, "second.py", "def second(): return 2\n")])
    write = module.atomic_write
    failed = False

    def disk_failure(path, content):
        nonlocal failed
        if path == root / "clipbot" / "second.py" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        return write(path, content)

    monkeypatch.setattr(module, "atomic_write", disk_failure)
    with pytest.raises(OSError, match="simulated"):
        service.promote(job, checks={"passed": True}, review={"passed": True})
    assert all((root / "clipbot" / name).read_bytes() == content for name, content in original.items())
    assert json.loads((job / "promotion.json").read_text())["status"] == "rolled_back"
