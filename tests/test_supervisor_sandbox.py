"""Containment and evaluator controls; no production data or engine required."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipbot.supervisor_sandbox import Sandbox, _copy_snapshot, _plain_dir, _protect_tests, RESULT_PREFIX


def settings():
    return SimpleNamespace(supervisor=SimpleNamespace(docker_distribution="Debian", sandbox_image="example:test",
        sandbox_memory_mb=4096, sandbox_cpus=2, sandbox_pids=128, sandbox_timeout_s=10,
        max_command_bytes=1048576, max_source_bytes=1048576))


def job(tmp_path):
    candidate, baseline, reports = (tmp_path / name for name in ("candidate", "baseline", "evaluation"))
    for folder in (candidate, baseline):
        (folder / "tests").mkdir(parents=True)
        (folder / "clipbot").mkdir()
        (folder / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
        (folder / "tests" / "test_protected.py").write_text("def test_required():\n    assert True\n")
    return candidate, baseline, reports


def response(**overrides):
    result = dict(policy="1", tests=1, failures=0, errors=0, skipped=0, exit_code=0, error="")
    result.update(overrides)
    result.setdefault("phases", [{"name": "baseline", **{key: result[key] for key in ("tests", "failures", "errors", "skipped", "exit_code")}}])
    return RESULT_PREFIX + json.dumps(result)


def fake_engine(sandbox, monkeypatch, result=None, exit_code=0):
    calls = []

    async def command(args):
        calls.append(args)
        if args[0] == "info":
            return 0, "29.6.1"
        if args[:2] == ["image", "inspect"]:
            return 0, "1"
        if args[0] == "run":
            return exit_code, result if result is not None else response()
        if args[0] == "rm":
            return 0, "removed"
        raise AssertionError(args)

    monkeypatch.setattr(sandbox, "_command", command)
    return calls


def test_missing_engine_never_executes_candidate(tmp_path, monkeypatch):
    sandbox = Sandbox(settings(), tmp_path)
    calls = []

    async def command(args):
        calls.append(args)
        return 1, "not available"

    monkeypatch.setattr(sandbox, "_command", command)
    result = asyncio.run(sandbox.evaluate(*job(tmp_path)))
    assert result["status"] == "setup_needed" and not result["passed"]
    assert [args[0] for args in calls] == ["info"]


def test_container_flags_and_exact_owned_cleanup(tmp_path, monkeypatch):
    sandbox = Sandbox(settings(), tmp_path)
    calls = fake_engine(sandbox, monkeypatch)
    candidate, baseline, reports = job(tmp_path)
    (candidate / "settings.json").write_text("must not copy")
    result = asyncio.run(sandbox.evaluate(candidate, baseline, reports))
    assert result["passed"] and result["tests"] == 1
    command = next(args for args in calls if args[0] == "run")
    for key, value in (("--network", "none"), ("--user", "65534:65534"), ("--cap-drop", "ALL"),
                       ("--security-opt", "no-new-privileges")):
        assert command[command.index(key) + 1] == value
    assert "--read-only" in command
    mounts = [command[index + 1] for index, arg in enumerate(command) if arg == "--mount"]
    assert len(mounts) == 2 and all(value.endswith(",readonly") for value in mounts)
    assert not any("docker.sock" in value for value in mounts)
    name = command[command.index("--name") + 1]
    assert calls[-1] == ["rm", "--force", name]
    assert not sandbox._owned
    assert list(reports.iterdir()) == [reports / "result.json"]


@pytest.mark.parametrize("result,exit_code", [(response(tests=0), 0), (response(failures=1), 1),
    (response(skipped=1), 0), (response(error="runner failed"), 0), ("", 0), (response(exit_code=False), 0)])
def test_failures_empty_tests_and_skips_cannot_pass(tmp_path, monkeypatch, result, exit_code):
    sandbox = Sandbox(settings(), tmp_path)
    fake_engine(sandbox, monkeypatch, result, exit_code)
    observed = asyncio.run(sandbox.evaluate(*job(tmp_path)))
    assert not observed["passed"]


@pytest.mark.parametrize("phases", [[], [{"name": "additional"}],
    [{"name": "baseline", "tests": True, "failures": 0, "errors": 0, "skipped": 0, "exit_code": 0}],
    [{"name": "baseline", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "exit_code": False}],
    [{"name": "baseline", "tests": 2, "failures": 0, "errors": 0, "skipped": 0, "exit_code": 0}]])
def test_invalid_or_inconsistent_phase_evidence_cannot_pass(tmp_path, monkeypatch, phases):
    sandbox = Sandbox(settings(), tmp_path)
    fake_engine(sandbox, monkeypatch, response(phases=phases))
    observed = asyncio.run(sandbox.evaluate(*job(tmp_path)))
    assert not observed["passed"] and "phase" in observed["error"]


def test_report_escape_rejected_before_any_command(tmp_path, monkeypatch):
    sandbox = Sandbox(settings(), tmp_path)
    calls = fake_engine(sandbox, monkeypatch)
    candidate, baseline, _ = job(tmp_path)
    result = asyncio.run(sandbox.evaluate(candidate, baseline, tmp_path.parent / "escape"))
    assert not result["passed"] and "siblings" in result["error"] and not calls


def test_link_paths_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="links"):
        _plain_dir(link / "report")


def test_link_guard_without_symlink_privilege(tmp_path, monkeypatch):
    import clipbot.supervisor_sandbox as module
    monkeypatch.setattr(module, "_linked", lambda path: path == tmp_path)
    with pytest.raises(ValueError, match="links"):
        _plain_dir(tmp_path / "not-created-yet")


def test_snapshot_allowlist_and_byte_limit(tmp_path):
    source, _, _ = job(tmp_path)
    (source / "clipbot" / "safe.py").write_text("x = 1")
    (source / "clipbot" / "tokens.json").write_text("private")
    (source / "clipbot" / "unknown.db").write_text("private")
    (source / "private").mkdir()
    (source / "private" / "account.json").write_text("private")
    dest = tmp_path / "copy"
    copied = _copy_snapshot(source, dest, settings().supervisor.max_source_bytes)
    assert copied["bytes"] > 0 and (dest / "clipbot" / "safe.py").exists()
    assert not (dest / "clipbot" / "tokens.json").exists()
    assert not (dest / "clipbot" / "unknown.db").exists()
    assert not (dest / "private").exists()
    with pytest.raises(ValueError, match="byte limit"):
        _copy_snapshot(source, tmp_path / "small", 1)


def test_hardlinked_source_rejected(tmp_path):
    source, _, _ = job(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("private = True")
    try:
        (source / "clipbot" / "linked.py").hardlink_to(outside)
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    with pytest.raises(ValueError, match="hard links"):
        _copy_snapshot(source, tmp_path / "copy", settings().supervisor.max_source_bytes)


def test_command_output_is_bounded_and_process_terminated(tmp_path, monkeypatch):
    import clipbot.supervisor_sandbox as module
    sandbox = Sandbox(settings(), tmp_path)
    sandbox.cfg.max_command_bytes = 8
    terminated = []

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 32)
        reader.feed_eof()
        process = SimpleNamespace(stdout=reader, returncode=0)

        async def launch(*args, **kwargs):
            return process

        async def stop(actual, grace):
            terminated.append(actual)

        monkeypatch.setattr(module, "spawn", launch)
        monkeypatch.setattr(module, "terminate", stop)
        with pytest.raises(ValueError, match="output exceeded"):
            await sandbox._command(["info"])
        assert terminated == [process]

    asyncio.run(run())


def test_candidate_cannot_replace_baseline_test_or_conftest(tmp_path):
    candidate, baseline, _ = job(tmp_path)
    required = (baseline / "tests" / "test_protected.py").read_bytes()
    (baseline / "tests" / "conftest.py").write_text("# protected fixtures")
    (candidate / "tests" / "test_protected.py").write_text("# weakened")
    (candidate / "tests" / "conftest.py").write_text("# disable all tests")
    (candidate / "tests" / "test_addition.py").write_text("def test_added(): pass")
    (candidate / "conftest.py").write_text("# hostile root fixture")
    work = candidate
    _protect_tests(work, baseline)
    assert (work / "tests" / "test_protected.py").read_bytes() == required
    assert (work / "tests" / "conftest.py").read_text() == "# protected fixtures"
    assert not (work / "tests" / "test_addition.py").exists()
    assert (work / "_additional_tests" / "test_addition.py").exists()
    assert (work / "_additional_tests" / "conftest.py").read_text() == "# protected fixtures"
    assert not (work / "conftest.py").exists()


def test_cancellation_removes_only_own_container(tmp_path, monkeypatch):
    sandbox = Sandbox(settings(), tmp_path)
    calls = []

    async def run():
        started = asyncio.Event()

        async def command(args):
            calls.append(args)
            if args[0] == "info":
                return 0, "29.6.1"
            if args[0] == "image":
                return 0, "1"
            if args[0] == "run":
                started.set()
                await asyncio.Event().wait()
            return 0, "removed"

        monkeypatch.setattr(sandbox, "_command", command)
        task = asyncio.create_task(sandbox.evaluate(*job(tmp_path)))
        await started.wait()
        await sandbox.close()
        assert task.cancelled()

    asyncio.run(run())
    run_args = next(args for args in calls if args[0] == "run")
    name = run_args[run_args.index("--name") + 1]
    assert [args for args in calls if args[0] == "rm"] == [["rm", "--force", name]]
    assert not sandbox._owned
