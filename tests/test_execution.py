"""官方执行边界的离线验证；不调用真实模型或 Docker。"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.verifier.result import VerifierResult

from sayacode_bench import execution


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "instance_demo"
    path.mkdir()
    (path / "task.toml").write_text('version = "1.0"\n', encoding="utf-8")
    return path


def trial(task_name="instance_demo", *, reward=1, exception=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        task_name=task_name,
        trial_name=f"{task_name}__unique",
        task_checksum="task-checksum",
        agent_result=AgentContext(),
        verifier_result=VerifierResult.model_construct(rewards={"reward": reward})
        if reward is not None
        else None,
        exception_info=SimpleNamespace(exception_type=exception) if exception else None,
        started_at=now,
        finished_at=now + timedelta(seconds=5),
    )


def worker(*, status="completed", complete=True):
    return {
        "status": status,
        "task_count": 2,
        "child_roles": ["planner", "reviewer"],
        "terminal_http_statuses": [],
        "usage": {
            "model_calls": 4,
            "reported_calls": 4 if complete else 3,
            "missing_usage_calls": 0 if complete else 1,
            "damaged_audit_lines": 0,
            "input_tokens": 1000,
            "output_tokens": 100,
        },
    }


def normalize(tmp_path, *, source_worker=None, **trial_kwargs):
    path = tmp_path / "trial"
    path.mkdir(exist_ok=True)
    write(path / "result.json", {"task_name": "instance_demo"})
    if source_worker is not None:
        write(path / "agent" / "sayacode" / "result.json", source_worker)
    return execution.normalize_trial_result(
        trial(**trial_kwargs), path, configuration="candidate", repeat=2, endpoint="remote"
    )


def test_official_reward_and_worker_status_are_independent(tmp_path):
    result = normalize(tmp_path, source_worker=worker(status="failed"), reward=1)
    assert result["status"] == "failed"
    assert result["original_reward"] == 1
    assert result["success"] is False
    assert result["usage_complete"] is True
    assert result["task_count"] == 2


def test_official_qualified_name_maps_to_frozen_task_id(tmp_path):
    result = normalize(tmp_path, source_worker=worker(), task_name="swebench-pro/instance_demo")
    assert result["task_id"] == "instance_demo"
    assert result["official_task_name"] == "swebench-pro/instance_demo"


def test_only_terminal_native_error_types_classify_connection_failures(tmp_path):
    path = tmp_path / "trial" / "agent" / "sayacode"
    write(path / "result.json", worker(status="failed"))
    audit = path / "audit.jsonl"
    failed = {
        "event": "model.failed",
        "thread_id": "child",
        "details": {
            "error_type": "OpenAIConnectionError",
            "error_chain": ["APIConnectionError", "RemoteProtocolError"],
        },
    }
    audit.write_text(json.dumps(failed) + "\n", encoding="utf-8")
    first = normalize(tmp_path, source_worker=worker(status="failed"))
    assert first["failure_category"] == "model_connection"
    with audit.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "model.completed", "thread_id": "child"}) + "\n")
    second = normalize(tmp_path, source_worker=worker(status="failed"))
    assert second["failure_category"] is None


def test_missing_score_is_unknown_not_failure(tmp_path):
    result = normalize(tmp_path, source_worker=worker(), reward=None)
    assert result["status"] == "completed"
    assert result["success"] is None
    assert result["verified"] is False


@pytest.mark.parametrize("reward", [0.5, "1", True, float("nan")])
def test_non_binary_or_invalid_reward_is_not_assumed_pass(tmp_path, reward):
    result = normalize(tmp_path, source_worker=worker(), reward=reward)
    assert result["success"] is None


def test_swe_success_waits_for_pristine_replay(tmp_path):
    path = tmp_path / "trial"
    write(path / "agent" / "sayacode" / "result.json", worker())
    result = execution.normalize_trial_result(
        trial(), path, configuration="baseline", repeat=1, endpoint="local", require_replay=True
    )
    assert result["original_reward"] == 1
    assert result["success"] is None
    assert result["verified"] is False


def test_timeout_wins_over_worker_shutdown_status(tmp_path):
    result = normalize(
        tmp_path, source_worker=worker(status="stopped"), exception="AgentTimeoutError"
    )
    assert result["status"] == "timeout"
    assert result["success"] is False


def test_verifier_error_does_not_relabel_agent_completion(tmp_path):
    result = normalize(
        tmp_path, source_worker=worker(), reward=None, exception="VerifierTimeoutError"
    )
    assert result["status"] == "completed"
    assert result["harbor_exception_type"] == "VerifierTimeoutError"
    assert result["success"] is None


def test_missing_worker_with_native_metadata_is_recovered(tmp_path):
    value = trial()
    value.agent_result.metadata = {"sayacode": worker(complete=False)}
    result = execution.normalize_trial_result(
        value, tmp_path, configuration="baseline", repeat=1, endpoint="local"
    )
    assert result["status"] == "completed"
    assert result["input_tokens"] == 1000
    assert result["usage_complete"] is False


def test_native_runtime_proof_is_referenced_without_random_container_identity(tmp_path):
    path = tmp_path / "trial"
    write(
        path / "runtime.json",
        {
            "available": True,
            "container_id": "random",
            "image_id": "sha256:fixed",
            "architecture": "amd64",
            "os": "linux",
            "docker_limits": {"Memory": 4294967296},
            "requested": {"memory_mb": 4096},
        },
    )
    result = normalize(tmp_path, source_worker=worker())
    assert result["runtime"]["sha256"]
    assert result["runtime_identity"]["image_id"] == "sha256:fixed"
    assert "container_id" not in result["runtime_identity"]


def test_legacy_trial_missing_runtime_is_not_backfilled(tmp_path):
    result = normalize(tmp_path, source_worker=worker())
    assert result["runtime_identity"] == {"available": False, "reason": "missing"}


def install_fake_job(
    monkeypatch, *, value=None, source_worker=None, error=None, count=1, replay_details=None
):
    captured = []

    async def create(config):
        captured.append(config)
        if error:
            raise error

        async def run():
            selected = value or trial(config.tasks[0].path.name)
            path = config.jobs_dir / config.job_name / selected.trial_name
            write(path / "result.json", {"task_name": selected.task_name})
            write(config.jobs_dir / config.job_name / "result.json", {"id": "job-uuid"})
            if source_worker is not None:
                write(path / "agent" / "sayacode" / "result.json", source_worker)
            if replay_details is not None:
                write(path / "agent" / "replay.json", replay_details)
            return SimpleNamespace(trial_results=[selected] * count)

        return SimpleNamespace(run=run)

    mock = AsyncMock(side_effect=create)
    monkeypatch.setattr(execution.Job, "create", mock)
    return captured, mock


async def test_real_job_config_keeps_one_attempt_and_zero_retry(task, tmp_path, monkeypatch):
    captured, _ = install_fake_job(monkeypatch, source_worker=worker())
    result = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    config = captured[0]
    assert config.n_attempts == config.n_concurrent_trials == 1
    assert config.retry.max_retries == 0
    assert len(config.tasks) == len(config.agents) == 1
    assert result["success"] is True
    assert result["raw_trial_result"]["sha256"]


async def test_completed_record_is_reused_without_rerunning(task, tmp_path, monkeypatch):
    _, mock = install_fake_job(monkeypatch, source_worker=worker())
    first = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    second = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    assert first == second
    assert mock.await_count == 1


@pytest.mark.parametrize("native_model", [False, True])
async def test_optional_official_verifier_env_reaches_job_without_mutating_input(
    task, tmp_path, monkeypatch, native_model
):
    from harbor.models.trial.config import VerifierConfig

    captured, _ = install_fake_job(monkeypatch)
    settings = {"env": {"PYTEST_ADDOPTS": "--hypothesis-seed=123", "PYTHONHASHSEED": "0"}}
    value = VerifierConfig.model_validate(settings) if native_model else settings
    await execution.run_official_trial(
        task, tmp_path / "jobs", "fixed", {"name": "oracle"}, verifier_config=value
    )
    assert captured[0].verifier.env == settings["env"]
    assert captured[0].agents[0].env == {}
    captured[0].verifier.env["PYTEST_ADDOPTS"] = "changed-in-copy"
    assert (value.env if native_model else value["env"])[
        "PYTEST_ADDOPTS"
    ] == "--hypothesis-seed=123"


async def test_changed_verifier_seed_cannot_reuse_a_previous_trial(task, tmp_path, monkeypatch):
    _, calls = install_fake_job(monkeypatch)
    await execution.run_official_trial(
        task,
        tmp_path / "jobs",
        "fixed",
        {"name": "oracle"},
        verifier_config={"env": {"PYTEST_ADDOPTS": "--hypothesis-seed=123"}},
    )
    with pytest.raises(ValueError, match="身份变化"):
        await execution.run_official_trial(
            task,
            tmp_path / "jobs",
            "fixed",
            {"name": "oracle"},
            verifier_config={"env": {"PYTEST_ADDOPTS": "--hypothesis-seed=124"}},
        )
    assert calls.await_count == 1


async def test_official_verifier_passes_override_only_to_its_native_exec(tmp_path, monkeypatch):
    from harbor.verifier.verifier import Verifier

    tests = tmp_path / "tests"
    tests.mkdir()
    script = tests / "test.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    logs = tmp_path / "verifier"
    logs.mkdir()
    reward = logs / "reward.txt"
    reward.write_text("1", encoding="utf-8")
    task_env = {"PYTEST_ADDOPTS": "--old-flag", "EXISTING": "kept"}
    injected = {"PYTEST_ADDOPTS": "--old-flag --hypothesis-seed=123", "PYTHONHASHSEED": "0"}
    environment = SimpleNamespace(
        os="linux", capabilities=SimpleNamespace(mounted=True), exec=AsyncMock()
    )
    verifier = Verifier(
        task=SimpleNamespace(config=SimpleNamespace(verifier=SimpleNamespace(env=task_env))),
        trial_paths=SimpleNamespace(
            verifier_dir=logs,
            test_stdout_path=logs / "test-stdout.txt",
            reward_text_path=reward,
            reward_json_path=logs / "reward.json",
        ),
        environment=environment,
        override_env=injected,
        skip_tests_upload=True,
    )
    monkeypatch.setattr(verifier, "_resolve_tests", lambda: ([tests], tests, script))
    result = await verifier.verify()
    assert result.rewards == {"reward": 1}
    assert environment.exec.await_args.kwargs["env"] == {**task_env, **injected}
    assert task_env["PYTEST_ADDOPTS"] == "--old-flag"


async def test_unrelated_loaded_replay_module_does_not_change_original_job_identity(
    task, tmp_path, monkeypatch
):
    _, mock = install_fake_job(monkeypatch, source_worker=worker())
    first = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    module = ModuleType("patch_replay")
    path = tmp_path / "patch_replay.py"
    path.write_text("# different public module\n", encoding="utf-8")
    module.__file__ = str(path)
    monkeypatch.setitem(sys.modules, "patch_replay", module)
    second = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    assert first == second
    assert mock.await_count == 1


async def test_existing_job_without_complete_record_is_never_implicitly_resumed(
    task, tmp_path, monkeypatch
):
    _, mock = install_fake_job(monkeypatch)
    (tmp_path / "jobs" / "one").mkdir(parents=True)
    with pytest.raises(ValueError, match="未收尾"):
        await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    assert mock.await_count == 0


async def test_changed_inputs_cannot_silently_reuse_record(task, tmp_path, monkeypatch):
    install_fake_job(monkeypatch)
    await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    (task / "task.toml").write_text('version = "2.0"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="身份变化"):
        await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})


async def test_harbor_failure_is_retained_without_exception_body(task, tmp_path, monkeypatch):
    install_fake_job(monkeypatch, error=RuntimeError("SECRET-do-not-log"))
    result = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    assert result["status"] == "infrastructure_error"
    assert result["success"] is False
    assert "SECRET" not in json.dumps(result)


async def test_cancelled_job_retains_incomplete_record(task, tmp_path, monkeypatch):
    install_fake_job(monkeypatch, error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    result = json.loads((tmp_path / "jobs" / "one" / "normalized.json").read_text(encoding="utf-8"))
    assert result["record_complete"] is False
    assert result["success"] is None


async def test_unexpected_trial_count_remains_unknown(task, tmp_path, monkeypatch):
    install_fake_job(monkeypatch, count=0)
    result = await execution.run_official_trial(task, tmp_path / "jobs", "one", {"name": "oracle"})
    assert result["trial_result_count"] == 0
    assert result["success"] is None
    assert result["record_complete"] is False


@pytest.mark.parametrize("job_name", ["../bad", "..", "a/b", "x:y"])
async def test_job_path_escape_is_rejected(task, tmp_path, job_name):
    with pytest.raises(ValueError):
        await execution.run_official_trial(task, tmp_path / "jobs", job_name, {"name": "oracle"})


@pytest.fixture
def replay_source(task, tmp_path):
    source = tmp_path / "source"
    write(
        source / "normalized.json",
        {
            "task_id": task.name,
            "configuration": "candidate",
            "repeat": 2,
            "canonical_model": execution.CANONICAL_MODEL,
            "endpoint": "remote",
            "status": "completed",
            "success": None,
            "verified": False,
            "record_complete": True,
            "duration_seconds": 8,
        },
    )
    write(source / "instance_demo__only" / "result.json", {"task_name": task.name})
    patch = source / "instance_demo__only" / "agent" / "model.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"a real captured patch\n")
    return source, patch


def fake_replay(monkeypatch, tmp_path, patch, *, apply_rc=0, reward=1, verified=True):
    tooling = tmp_path / "tooling"
    tooling.mkdir()
    module_file = tooling / "patch_replay.py"
    module_file.write_text("class PatchReplayAgent: pass\n", encoding="utf-8")
    module = ModuleType("patch_replay")
    module.__file__ = str(module_file)
    monkeypatch.setitem(sys.modules, "patch_replay", module)
    job_dir = tmp_path / "regrade" / "fresh"
    write(
        job_dir / "instance_demo__new" / "agent" / "replay.json",
        {
            "patch": str(patch),
            "apply_rc": apply_rc,
        },
    )
    result = {
        "job_dir": str(job_dir),
        "trial_name": "instance_demo__new",
        "original_reward": reward,
        "verified": verified,
        "duration_seconds": 3,
        "raw_trial_result": {"sha256": "replay-sha"},
    }
    mock = AsyncMock(return_value=result)
    monkeypatch.setattr(execution, "run_official_trial", mock)
    return tooling, mock


async def test_pristine_replay_uses_official_agent_and_records_apply_evidence(
    task, tmp_path, replay_source, monkeypatch
):
    source, patch = replay_source
    tooling, mock = fake_replay(monkeypatch, tmp_path, patch)
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["verified"] is True
    assert result["success"] is True
    assert result["apply_rc"] == 0
    assert result["patch"]["sha256"]
    assert result["replay_raw_trial_result"]["sha256"] == "replay-sha"
    assert mock.call_args.args[3].import_path == "patch_replay:PatchReplayAgent"
    assert mock.call_args.args[3].kwargs == {"source_job": str(source)}


async def test_missing_patch_has_no_fabricated_verification(task, tmp_path, replay_source):
    source, patch = replay_source
    patch.unlink()
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tmp_path / "absent"
    )
    assert result["verified"] is False
    assert result["success"] is None
    assert result["replay_job_dir"] is None


@pytest.mark.parametrize("reward", [0, 1])
async def test_empty_patch_is_regraded_through_official_job_without_guessing_reward(
    task, tmp_path, replay_source, monkeypatch, reward
):
    source, patch = replay_source
    patch.write_bytes(b"")
    tooling = tmp_path / "official-tooling"
    tooling.mkdir()
    module_file = tooling / "patch_replay.py"
    module_file.write_text("class PatchReplayAgent: pass\n", encoding="utf-8")
    module = ModuleType("patch_replay")
    module.__file__ = str(module_file)
    monkeypatch.setitem(sys.modules, "patch_replay", module)
    captured, mock = install_fake_job(
        monkeypatch, value=trial(reward=reward), replay_details={"task": task.name, "patch": None}
    )
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert mock.await_count == 1
    assert captured[0].agents[0].import_path == "patch_replay:PatchReplayAgent"
    assert captured[0].n_attempts == 1
    assert result["replay_reward"] == reward
    assert result["success"] is (reward == 1)
    assert result["verified"] is True
    assert result["apply_rc"] is None
    assert result["patch_application"] == "not_required_empty_patch"
    assert result["replay_status"] == "completed_no_changes"
    assert result["replay_raw_trial_result"]["sha256"]


async def test_nonzero_patch_apply_never_passes_even_if_reward_is_one(
    task, tmp_path, replay_source, monkeypatch
):
    source, patch = replay_source
    tooling, _ = fake_replay(monkeypatch, tmp_path, patch, apply_rc=1)
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["status"] == "patch_apply_failed"
    assert result["success"] is False
    assert result["verified"] is False


async def test_replay_missing_score_remains_unknown(task, tmp_path, replay_source, monkeypatch):
    source, patch = replay_source
    tooling, _ = fake_replay(monkeypatch, tmp_path, patch, reward=None, verified=False)
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["verified"] is False
    assert result["success"] is None


@pytest.mark.parametrize(
    "field, changed", [("image_id", "sha256:different"), ("architecture", "arm64")]
)
async def test_runtime_drift_prevents_verification_even_when_official_reward_passes(
    task, tmp_path, replay_source, monkeypatch, field, changed
):
    source, patch = replay_source
    tooling, mock = fake_replay(monkeypatch, tmp_path, patch)
    original_runtime = source / "instance_demo__only" / "runtime.json"
    base = {"available": True, "image_id": "sha256:fixed", "architecture": "amd64", "os": "linux"}
    write(original_runtime, base)
    source_record = json.loads((source / "normalized.json").read_text(encoding="utf-8"))
    source_record["runtime"] = execution._file_identity(original_runtime)
    write(source / "normalized.json", source_record)
    replay_runtime = tmp_path / "regrade" / "fresh" / "instance_demo__new" / "runtime.json"
    write(replay_runtime, {**base, field: changed})
    mock.return_value["runtime"] = execution._file_identity(replay_runtime)
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["replay_reward"] == 1
    assert result["verified"] is False
    assert result["success"] is None
    assert result["replay_status"] == "runtime_identity_mismatch"
    comparison = result["runtime_comparison"]
    assert comparison["same_image" if field == "image_id" else "same_platform"] is False


async def test_replay_needs_confirmation_that_expected_patch_was_applied(
    task, tmp_path, replay_source, monkeypatch
):
    source, patch = replay_source
    tooling, _ = fake_replay(monkeypatch, tmp_path, patch)
    evidence = tmp_path / "regrade" / "fresh" / "instance_demo__new" / "agent" / "replay.json"
    write(evidence, {"apply_rc": 0, "patch": "another.patch"})
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["replay_status"] == "patch_identity_unconfirmed"
    assert result["success"] is None
    assert result["verified"] is False


async def test_replay_evidence_corruption_preserves_unknown(
    task, tmp_path, replay_source, monkeypatch
):
    source, patch = replay_source
    tooling, _ = fake_replay(monkeypatch, tmp_path, patch)
    evidence = tmp_path / "regrade" / "fresh" / "instance_demo__new" / "agent" / "replay.json"
    evidence.write_bytes(b"{invalid")
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tooling
    )
    assert result["replay_status"] == "replay_evidence_unreadable"
    assert result["success"] is None
    assert result["verified"] is False


async def test_source_patch_change_cannot_reuse_old_replay_identity(
    task, tmp_path, replay_source, monkeypatch
):
    source, patch = replay_source
    install_fake_job(monkeypatch)
    config = {"import_path": "patch_replay:PatchReplayAgent", "kwargs": {"source_job": str(source)}}
    await execution.run_official_trial(task, tmp_path / "jobs", "one", config)
    patch.write_bytes(b"changed patch\n")
    with pytest.raises(ValueError, match="身份变化"):
        await execution.run_official_trial(task, tmp_path / "jobs", "one", config)


@pytest.mark.parametrize("initial_flag", [False, True])
async def test_real_official_module_import_preserves_snapshot_and_restores_bytecode_flag(
    task, tmp_path, replay_source, monkeypatch, initial_flag
):
    source, patch = replay_source
    tooling = tmp_path / "immutable-tooling"
    tooling.mkdir()
    module_path = tooling / "patch_replay.py"
    module_path.write_text("IMPORTED = True\nclass PatchReplayAgent: pass\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tooling.iterdir()}
    fresh = tmp_path / "fresh"
    write(
        fresh / "instance_demo__new" / "agent" / "replay.json", {"patch": str(patch), "apply_rc": 0}
    )
    monkeypatch.setattr(
        execution,
        "run_official_trial",
        AsyncMock(
            return_value={
                "job_dir": str(fresh),
                "trial_name": "instance_demo__new",
                "original_reward": 1,
                "verified": True,
            }
        ),
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", initial_flag)
    prior_module = sys.modules.pop("patch_replay", None)
    try:
        result = await execution.replay_official_trial(
            task, tmp_path / "jobs", "fresh", source, tooling
        )
        assert sys.modules["patch_replay"].IMPORTED is True
        assert result["verified"] is True
        assert sys.dont_write_bytecode is initial_flag
        assert {path.name: path.read_bytes() for path in tooling.iterdir()} == before
        assert not (tooling / "__pycache__").exists()
    finally:
        sys.modules.pop("patch_replay", None)
        if prior_module is not None:
            sys.modules["patch_replay"] = prior_module


async def test_failed_real_import_also_restores_global_flag_and_does_not_write_cache(
    task, tmp_path, replay_source, monkeypatch
):
    source, _ = replay_source
    tooling = tmp_path / "broken-tooling"
    tooling.mkdir()
    (tooling / "patch_replay.py").write_text(
        "raise RuntimeError('controlled import failure')\n", encoding="utf-8"
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    prior_module = sys.modules.pop("patch_replay", None)
    try:
        with pytest.raises(RuntimeError, match="controlled import"):
            await execution.replay_official_trial(task, tmp_path / "jobs", "fresh", source, tooling)
        assert sys.dont_write_bytecode is False
        assert not (tooling / "__pycache__").exists()
        assert str(tooling) not in sys.path
    finally:
        sys.modules.pop("patch_replay", None)
        if prior_module is not None:
            sys.modules["patch_replay"] = prior_module


async def test_multiple_source_trials_are_rejected_instead_of_first_patch(
    task, tmp_path, replay_source
):
    source, _ = replay_source
    write(source / "instance_other__trial" / "result.json", {"task_name": "instance_other"})
    with pytest.raises(ValueError, match="恰好一个"):
        await execution.replay_official_trial(task, tmp_path / "jobs", "fresh", source, tmp_path)


@pytest.mark.parametrize(
    "status", ["failed", "infrastructure_error", "cancelled", "timeout", "completed"]
)
async def test_missing_native_trial_retains_runtime_failure_without_guessing_grade(
    task, tmp_path, replay_source, status
):
    source, _ = replay_source
    record = json.loads((source / "normalized.json").read_text(encoding="utf-8"))
    record.update(status=status, success=False)
    write(source / "normalized.json", record)
    (source / "instance_demo__only" / "result.json").unlink()
    result = await execution.replay_official_trial(
        task, tmp_path / "jobs", "fresh", source, tmp_path
    )
    assert result["status"] == status
    assert result["success"] is (None if status == "completed" else False)
    assert result["verified"] is False
    assert result["replay_status"] == "missing_source_trial"
    assert result["replay_job_dir"] is None


async def test_source_task_mismatch_is_rejected(task, tmp_path, replay_source):
    source, _ = replay_source
    write(source / "instance_demo__only" / "result.json", {"task_name": "instance_other"})
    with pytest.raises(ValueError, match="不一致"):
        await execution.replay_official_trial(task, tmp_path / "jobs", "fresh", source, tmp_path)


def test_paired_order_is_fixed_and_every_block_stays_adjacent():
    plan = {
        "seed": 42,
        "tasks": [{"task_id": "a"}, {"task_id": "b"}],
        "configurations": ["baseline", "candidate"],
        "repeats": 3,
    }
    order = execution.paired_order(plan)
    assert order == execution.paired_order(plan)
    assert len(order) == 12
    for index in range(0, len(order), 2):
        left, right = order[index : index + 2]
        assert (left["task_id"], left["repeat"]) == (right["task_id"], right["repeat"])
        assert left["configuration"] != right["configuration"]


def test_resume_skips_completed_failures_and_preserves_sequence():
    plan = {
        "seed": "frozen",
        "tasks": [{"task_id": "a"}],
        "configurations": ["baseline", "candidate"],
        "repeats": 1,
    }
    full = execution.paired_order(plan)
    prior = {**full[0], "success": False, "record_complete": True}
    assert execution.remaining_order(plan, [prior]) == full[1:]
    prior["record_complete"] = False
    with pytest.raises(ValueError, match="未收尾"):
        execution.remaining_order(plan, [prior])
