"""Bounded local discovery without credential stores, links or secret fragments."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipbot.supervisor_files import LocalFiles


@pytest.fixture
def files(tmp_path):
    cfg = SimpleNamespace(file_scan_limit=12, max_history=5, max_text_chars=32, response_max_bytes=256)
    private = tmp_path / "ashvane-private"
    private.mkdir()
    return LocalFiles(SimpleNamespace(supervisor=cfg), private)


@pytest.mark.parametrize("relative", [".ssh/id_rsa", ".aws/credentials", "credentials/notes.txt",
    "Google/Chrome/profiles.json", ".git/config", "settings.json", "tokens-stories.json", ".env.production"])
def test_credential_paths_rejected_before_reading(files, tmp_path, relative):
    with pytest.raises(ValueError, match="private"):
        files.path(str(tmp_path / relative))


@pytest.mark.parametrize("relative", [".codex/auth.json", ".ENV.txt", ".netrc", ".pypirc"])
def test_other_account_stores_and_case_variant_environment_files_excluded(files, tmp_path, relative):
    with pytest.raises(ValueError, match="private|credential"):
        files.path(str(tmp_path / relative))


def test_runtime_directory_and_relative_or_network_paths_excluded(files, tmp_path):
    for path in (str(files.private_root / "anything.txt"), "relative/file.txt", "https://example.org/file.txt"):
        with pytest.raises(ValueError):
            files.path(path)
    if Path("C:/").is_absolute():
        with pytest.raises(ValueError):
            files.path(r"\\server\share\file.txt")


def test_normalization_cannot_traverse_into_private_runtime(files, tmp_path):
    with pytest.raises(ValueError, match="runtime|excluded"):
        files.path(str(tmp_path / "ordinary" / ".." / files.private_root.name / "notes.txt"))


def test_read_is_bounded_paged_and_does_not_modify_file(files, tmp_path):
    path = tmp_path / "public.py"
    original = "abcdefghij" * 10
    path.write_text(original)
    result = files.read(str(path), offset=17)
    assert result["text"] == original[17:49]
    assert result["characters"] == len(original) and result["offset"] == 17
    assert path.read_text() == original


@pytest.mark.parametrize("offset", [-1, True, "0", 0.5])
def test_invalid_offsets_rejected(files, tmp_path, offset):
    path = tmp_path / "public.txt"
    path.write_text("Original public text")
    with pytest.raises(ValueError, match="Offset"):
        files.read(str(path), offset)


def test_oversized_or_binary_file_not_read(files, tmp_path):
    for name, content in (("large.txt", b"x" * 257), ("private.db", b"database")):
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(ValueError):
            files.read(str(path))


def test_redaction_survives_paging_into_secret_value(files, tmp_path):
    path = tmp_path / "ordinary.txt"
    path.write_text("password=synthetic-value-must-not-leak")
    result = files.read(str(path), offset=len("password="))
    assert "synthetic-value" not in result["text"]


def test_browse_bounds_scan_and_result_counts_and_excludes_private_entries(files, tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_rsa").write_text("not read")
    (root / "tokens.json").write_text("not read")
    for index in range(20):
        (root / f"note-{index}.txt").write_text("public")
    result = files.browse(str(root), pattern="*.txt", recursive=True)
    assert len(result["entries"]) <= files.settings.supervisor.max_history
    assert result["examined"] <= files.settings.supervisor.file_scan_limit
    assert result["truncated"]
    assert not any(".ssh" in row["path"] or "tokens.json" in row["path"] for row in result["entries"])


def test_browse_pattern_is_filename_filter_not_path_traversal(files, tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "visible.txt").write_text("public")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not discover")
    result = files.browse(str(root), pattern="../*.txt", recursive=True)
    assert not result["entries"]
    with pytest.raises(ValueError):
        files.browse(str(root), pattern="x" * 33)


def test_links_to_private_data_are_not_followed(files, tmp_path):
    private = files.private_root / "notes.txt"
    private.write_text("synthetic private content")
    link = tmp_path / "public.txt"
    try:
        link.symlink_to(private)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="Linked"):
        files.read(str(link))


def test_hardlink_cannot_alias_private_file(files, tmp_path):
    private = files.private_root / "notes.txt"
    private.write_text("synthetic private content")
    alias = tmp_path / "public.txt"
    try:
        alias.hardlink_to(private)
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    with pytest.raises(ValueError, match="link|private"):
        files.read(str(alias))
