"""Durable bounded learning, provenance eligibility, redaction and held-out data."""
import json
from types import SimpleNamespace

import pytest

from clipbot.supervisor_memory import SupervisorMemory, clean


def settings(**changes):
    cfg = dict(store_max_bytes=1048576, max_history=10, dataset_limit=100,
               max_agents=12, max_text_chars=1000, dataset_eval_percent=50)
    cfg.update(changes)
    return SimpleNamespace(supervisor=SimpleNamespace(**cfg))


def provenance():
    return {"job_id": "synthetic-job-1", "checks": {"passed": True}, "source": "owner_code"}


def exported(memory, split):
    return [json.loads(line) for line in memory.export(split).splitlines()]


def test_roundtrip_preserves_evidence_and_marks_unfinished_jobs_interrupted(tmp_path):
    memory = SupervisorMemory(settings(), tmp_path)
    memory.event("engineer", "tested", "Synthetic regression reproduced")
    memory.example("Improve this pure function", "Verified patch", provenance(), verified=True, rights="owner_code")
    memory.data["jobs"] = [{"id": str(index), "status": state} for index, state in enumerate(
        ("running", "evaluating", "applying", "passed", "failed"))]
    memory.save()
    reloaded = SupervisorMemory(settings(), tmp_path)
    assert reloaded.data["events"] == memory.data["events"]
    assert reloaded.data["examples"] == memory.data["examples"]
    assert [job["status"] for job in reloaded.data["jobs"]] == ["interrupted"] * 3 + ["passed", "failed"]
    assert all(job.get("error") for job in reloaded.data["jobs"][:3])


@pytest.mark.parametrize("verified,rights", [(False, "owner_code"), (1, "owner_code"),
    (True, "unknown"), (True, "private_account"), (False, "permitted_public")])
def test_unverified_or_unlicensed_examples_never_enter_exports(tmp_path, verified, rights):
    memory = SupervisorMemory(settings(), tmp_path)
    row = memory.example("Prompt", "Response", provenance(), verified=verified, rights=rights)
    assert not row["eligible"]
    assert memory.export("training") == memory.export("evaluation") == ""


@pytest.mark.parametrize("rights", ["owner_code", "original_synthetic", "permitted_public"])
def test_verified_examples_with_provenance_can_be_exported(tmp_path, rights):
    memory = SupervisorMemory(settings(), tmp_path)
    supplied = provenance()
    row = memory.example("Prompt", "Response", supplied, verified=True, rights=rights)
    supplied["checks"]["passed"] = False
    assert row["eligible"] and row["provenance"]["checks"]["passed"] is True
    record = exported(memory, row["split"])[0]
    assert record["id"] == row["id"] and record["provenance"] == row["provenance"]
    assert record["messages"] == [{"role": "user", "content": "Prompt"}, {"role": "assistant", "content": "Response"}]


def test_verified_flag_without_provenance_is_not_training_evidence(tmp_path):
    memory = SupervisorMemory(settings(), tmp_path)
    row = memory.example("Unsupported assertion", "Trust the agent", {}, verified=True, rights="owner_code")
    assert not row["eligible"]
    assert memory.export("training") == memory.export("evaluation") == ""


def test_holdout_split_is_deterministic_disjoint_and_survives_reload(tmp_path):
    cfg = settings()
    memory = SupervisorMemory(cfg, tmp_path)
    for index in range(80):
        memory.example(f"Original synthetic case {index}", f"Verified outcome {index}", provenance(),
                       verified=True, rights="original_synthetic")
    training = {row["id"] for row in exported(memory, "training")}
    evaluation = {row["id"] for row in exported(memory, "evaluation")}
    assert training and evaluation and not training & evaluation
    assert training | evaluation == {row["id"] for row in memory.data["examples"]}
    reloaded = SupervisorMemory(cfg, tmp_path)
    assert {row["id"] for row in exported(reloaded, "training")} == training
    assert {row["id"] for row in exported(reloaded, "evaluation")} == evaluation


def test_duplicate_example_is_not_added_or_downgraded(tmp_path):
    memory = SupervisorMemory(settings(), tmp_path)
    first = memory.example("Prompt", "Response", provenance(), verified=True, rights="owner_code")
    duplicate = memory.example("Prompt", "Response", {}, verified=False, rights="unknown")
    assert duplicate["id"] == first["id"] and duplicate["eligible"]
    assert len(memory.data["examples"]) == 1


@pytest.mark.parametrize("secret", ["Bearer fake-token-value", "password=hunter2-test", "api_key=synthetic-secret",
    '{"access_token": "synthetic-secret"}', "{'refresh_token': 'synthetic-secret'}"])
def test_secret_forms_are_redacted_before_persistence(tmp_path, secret):
    memory = SupervisorMemory(settings(), tmp_path)
    memory.example(secret, "Original response", provenance(), verified=True, rights="owner_code")
    text = memory.path.read_text()
    for value in ("fake-token-value", "hunter2-test", "synthetic-secret"):
        assert value not in text
    assert "[redacted]" in text


def test_nested_provenance_and_event_metadata_are_redacted(tmp_path):
    memory = SupervisorMemory(settings(), tmp_path)
    supplied = {**provenance(), "nested": {"access_token": "not-for-learning", "note": "Bearer event-secret"}}
    row = memory.example("Prompt", "Response", supplied, verified=True, rights="owner_code")
    memory.event("researcher", "fetched", "Public evidence", details={"password": "event-password"})
    persisted = memory.path.read_text()
    combined = persisted + memory.export(row["split"])
    assert all(value not in combined for value in ("not-for-learning", "event-secret", "event-password"))


def test_history_dataset_and_agent_counts_are_bounded(tmp_path):
    memory = SupervisorMemory(settings(max_history=2, dataset_limit=3, max_agents=2), tmp_path)
    for index in range(5):
        memory.event("engineer", "outcome", f"Outcome {index}")
        memory.example(f"Prompt {index}", "Response", provenance(), verified=True, rights="owner_code")
    memory.data["agents"] = [{"role": str(index)} for index in range(5)]
    memory.save()
    assert [row["summary"] for row in memory.data["events"]] == ["Outcome 3", "Outcome 4"]
    assert len(memory.data["examples"]) == 3 and len(memory.data["agents"]) == 2


def test_oversized_save_keeps_last_durable_ledger(tmp_path):
    cfg = settings()
    memory = SupervisorMemory(cfg, tmp_path)
    memory.event("engineer", "outcome", "Known good")
    original = memory.path.read_bytes()
    cfg.supervisor.store_max_bytes = len(original)
    memory.data["learning"].append({"observation": "x" * 1000})
    with pytest.raises(ValueError, match="budget"):
        memory.save()
    assert memory.path.read_bytes() == original


@pytest.mark.parametrize("content", ['{"events": "bad list"}', '{broken json'])
def test_invalid_ledger_is_not_silently_overwritten(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        SupervisorMemory(settings(), tmp_path)
    assert path.read_text() == content


def test_export_rejects_unknown_split_and_clean_bounds_text(tmp_path):
    memory = SupervisorMemory(settings(), tmp_path)
    with pytest.raises(ValueError, match="training or evaluation"):
        memory.export("all")
    assert clean("x" * 200, 25) == "x" * 25
