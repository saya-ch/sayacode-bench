"""固定 seed 诊断的范围、原生配置链和公开证据边界；不运行 Docker 或模型。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml
from harbor.models.job.config import JobConfig, RetryConfig
from harbor.models.trial.config import AgentConfig, TaskConfig, TrialConfig, VerifierConfig

from sayacode_bench.artifacts import read_json, write_json


def module() -> Any:
    path = Path(__file__).parents[1] / "scripts" / "reproduce_hypothesis_seed.py"
    spec = importlib.util.spec_from_file_location("hypothesis_diagnostic", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def test_plan_contains_only_fixed_qutebrowser_seed_and_three_oracles() -> None:
    diagnostic = module()
    plan = diagnostic.fixed_plan()
    assert plan["fixture"]["task_id"].startswith("instance_qutebrowser__qutebrowser-3d01c201")
    assert (
        plan["fixture"]["digest"]
        == "sha256:cc0e0f503659eac82afb4f304e853c5a94ddd2aba834e62d3fd757fa6fba13e3"
    )
    assert plan["hypothesis_seed"] == "242126932532074149523975327703198283377"
    assert plan["python_hash_seed"] == "0"
    assert plan["external_diagnostic_window_seconds"] == 1500
    assert plan["external_force_cancel_grace_seconds"] == 60
    assert [(row["agent"], row["repeat"]) for row in plan["schedule"]] == [
        ("oracle", 1),
        ("oracle", 2),
        ("oracle", 3),
    ]
    assert plan["model_requests"] == 0
    assert plan["formal_comparison_eligible"] is plan["formal_validation_eligible"] is False


@pytest.mark.parametrize("original", [None, "", '-ra -n auto --ignore="space path" --flag=a=b'])
async def test_image_read_extracts_only_addopts_and_preserves_existing_flags(
    original: str | None, monkeypatch: Any
) -> None:
    diagnostic = module()
    value = "" if original is None else json.dumps("PYTEST_ADDOPTS=" + original) + "\n"
    inspect = AsyncMock(return_value=value)
    monkeypatch.setattr(diagnostic, "docker", inspect)
    fixture = diagnostic.fixed_plan()["fixture"]
    env, proof = await diagnostic.verifier_environment(fixture)
    expected = (original + " " if original else "") + "--hypothesis-seed=" + diagnostic.SEED
    assert env == {"PYTEST_ADDOPTS": expected, "PYTHONHASHSEED": "0"}
    assert proof["image_pytest_addopts_present"] is (original is not None)
    assert proof["verifier_env_sha256"] == diagnostic._value_hash(env)
    args = inspect.await_args.args
    assert args[:3] == ("image", "inspect", "--format")
    assert args[-1] == fixture["immutable_image"]
    assert '"PYTEST_ADDOPTS"' in args[3] and "{{json .Config.Env}}" not in args[3]
    assert "--ignore" not in json.dumps(proof)


@pytest.mark.parametrize(
    "value",
    [
        '"PYTEST_ADDOPTS=-ra"\n"PYTEST_ADDOPTS=-q"\n',
        '"OTHER=do-not-copy"\n',
        "null\n",
    ],
)
async def test_ambiguous_or_unexpected_image_env_stops_before_running(value, monkeypatch):
    diagnostic = module()
    monkeypatch.setattr(diagnostic, "docker", AsyncMock(return_value=value))
    with pytest.raises(ValueError):
        await diagnostic.verifier_environment(diagnostic.fixed_plan()["fixture"])


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: Any) -> Any:
    diagnostic = module()
    fixture = diagnostic.fixed_plan()["fixture"]
    tasks = tmp_path / "source" / "tasks"
    task = tasks / fixture["task_id"]
    task.mkdir(parents=True)
    (task / "task.toml").write_text(
        "[environment]\ncpus=1\nmemory_mb=4096\nstorage_mb=10240\n"
        f'docker_image="{fixture["original_image_reference"]}"\n',
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(
        tasks_path=tasks, spec=SimpleNamespace(revision=diagnostic.fixtures.REVISION)
    )
    monkeypatch.setattr(diagnostic, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(diagnostic, "version", lambda *args: "0.24.0")
    monkeypatch.setattr(
        diagnostic.fixtures,
        "pin_image",
        AsyncMock(
            return_value={
                "expected_image_id": "sha256:" + "a" * 64,
                "expected_repo_digest": fixture["immutable_image"],
                "architecture": "amd64",
                "os": "linux",
            }
        ),
    )
    monkeypatch.setattr(diagnostic, "docker", AsyncMock(return_value='"PYTEST_ADDOPTS=-ra"\n'))
    calls = []

    async def execute(task_path, raw_root, name, agent, environment, **kwargs):
        calls.append({"task": task_path, "agent": agent, "environment": environment, **kwargs})
        job = raw_root / name
        trial = job / "instance_fake__trial"
        verifier = VerifierConfig.model_validate(kwargs["verifier_config"])
        config = JobConfig(
            job_name=name,
            jobs_dir=raw_root,
            tasks=[TaskConfig(path=task_path)],
            agents=[AgentConfig(name="oracle")],
            verifier=verifier,
            n_attempts=1,
            n_concurrent_trials=1,
            retry=RetryConfig(max_retries=0),
        )
        trial_config = TrialConfig(
            task=TaskConfig(path=task_path), agent=AgentConfig(name="oracle"), verifier=verifier
        )
        write_json(job / "config.json", config.model_dump(mode="json", exclude_defaults=True))
        write_json(
            trial / "config.json", trial_config.model_dump(mode="json", exclude_defaults=True)
        )
        reward = 0 if kwargs["repeat"] == 2 else 1
        write_json(
            trial / "result.json",
            {
                "task_name": task_path.name,
                "verifier_result": {"rewards": {"reward": reward}},
            },
        )
        write_json(
            trial / "runtime.json",
            {
                "available": True,
                "image_id": "sha256:" + "a" * 64,
                "repo_digests": [fixture["immutable_image"]],
                "architecture": "amd64",
                "os": "linux",
                "requested": {"memory_mb": 4096},
                "docker_limits": {"Memory": 4 * 1024**3},
            },
        )
        (trial / "agent").mkdir()
        (trial / "agent" / "solution.log").write_text(
            "DO-NOT-PUBLISH-REFERENCE-PATCH", encoding="utf-8"
        )
        (trial / "verifier").mkdir()
        (trial / "verifier" / "run-script-stderr.txt").write_text(
            "AttributeError: DO-NOT-PUBLISH-TEST-BODY\n",
            encoding="utf-8",
        )
        return {
            "job_dir": str(job),
            "status": "completed",
            "original_reward": reward,
            "verified": True,
            "request_sha256": f"{kwargs['repeat']:064x}",
        }

    monkeypatch.setattr(diagnostic, "run_official_trial", execute)
    return SimpleNamespace(
        diagnostic=diagnostic,
        fixture=fixture,
        calls=calls,
        task=task,
        cache=tmp_path / "cache",
        output=tmp_path / "output",
    )


async def test_three_trials_keep_zero_reward_and_native_seed_evidence_without_publishing_raw(
    scenario,
):
    before = (scenario.task / "task.toml").read_bytes()
    result = await scenario.diagnostic.reproduce(scenario.cache, scenario.output)
    assert len(scenario.calls) == 3
    assert result["diagnostic_evidence_complete"] is True
    assert result["oracle_all_passed"] is False
    assert result["oracle_rewards"] == [1, 0, 1]
    assert (scenario.task / "task.toml").read_bytes() == before
    for call in scenario.calls:
        assert call["agent"] == {"name": "oracle"}
        assert call["canonical_model"] == call["endpoint"] == "not_used"
        assert call["verifier_config"]["env"]["PYTEST_ADDOPTS"].startswith("-ra --hypothesis-seed=")
    records = read_json(scenario.output / "public" / "summary.json")
    assert records == result
    published = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (scenario.output / "public").rglob("*")
        if path.is_file()
    )
    assert "DO-NOT-PUBLISH" not in published and str(scenario.output) not in published
    assert (scenario.output / "raw" / "verifier-env.json").is_file()
    observations = list((scenario.output / "public").glob("trials/*/native-observations.json"))
    assert len(observations) == 3
    assert all(read_json(path)["config"]["matches_expected"] for path in observations)


async def test_a_trial_error_does_not_skip_later_fixed_repeats(scenario, monkeypatch):
    original = scenario.diagnostic.run_official_trial

    async def execute(*args, **kwargs):
        if kwargs["repeat"] == 2:
            raise RuntimeError("DO-NOT-PUBLISH-RAW-ERROR")
        return await original(*args, **kwargs)

    monkeypatch.setattr(scenario.diagnostic, "run_official_trial", execute)
    result = await scenario.diagnostic.reproduce(scenario.cache, scenario.output)
    assert len(scenario.calls) == 2 and result["recorded_jobs"] == 3
    assert result["diagnostic_evidence_complete"] is False
    assert result["oracle_rewards"] == [1, None, 1]


async def test_preparation_failure_keeps_three_not_attempted_without_model_requests(
    scenario, monkeypatch
):
    monkeypatch.setattr(
        scenario.diagnostic, "docker", AsyncMock(side_effect=RuntimeError("private"))
    )
    result = await scenario.diagnostic.reproduce(scenario.cache, scenario.output)
    assert scenario.calls == [] and result["recorded_jobs"] == 3
    assert result["all_jobs_attempted"] is False
    assert result["diagnostic_evidence_complete"] is False


async def test_interruption_retains_partial_evidence_and_refuses_resume(scenario, monkeypatch):
    original = scenario.diagnostic.run_official_trial

    async def execute(*args, **kwargs):
        if kwargs["repeat"] == 2:
            raise asyncio.CancelledError
        return await original(*args, **kwargs)

    monkeypatch.setattr(scenario.diagnostic, "run_official_trial", execute)
    with pytest.raises(asyncio.CancelledError):
        await scenario.diagnostic.reproduce(scenario.cache, scenario.output)
    result = read_json(scenario.output / "public" / "summary.json")
    assert result["interrupted"] and result["recorded_jobs"] == 1
    with pytest.raises(FileExistsError):
        await scenario.diagnostic.reproduce(scenario.cache, scenario.output)


@pytest.mark.parametrize("mutation", ["seed", "agent", "timeout", "resource", "task"])
async def test_native_config_mismatch_keeps_grade_but_blocks_complete_diagnostic(
    scenario, monkeypatch, mutation
):
    original = scenario.diagnostic.run_official_trial

    async def execute(*args, **kwargs):
        raw = await original(*args, **kwargs)
        config = next(Path(raw["job_dir"]).glob("instance_*/config.json"))
        value = read_json(config)
        if mutation == "seed":
            value["verifier"]["env"]["PYTEST_ADDOPTS"] = "--hypothesis-seed=other"
        elif mutation == "agent":
            value.setdefault("agent", {})["name"] = "nop"
        elif mutation == "timeout":
            value["timeout_multiplier"] = 2
        elif mutation == "resource":
            value["environment"] = {"override_memory_mb": 1}
        else:
            value["task"]["path"] = str(scenario.task.parent / "different")
        write_json(config, value)
        return raw

    monkeypatch.setattr(scenario.diagnostic, "run_official_trial", execute)
    result = await scenario.diagnostic.reproduce(scenario.cache, scenario.output)
    assert result["recorded_jobs"] == 3 and result["oracle_rewards"] == [1, 0, 1]
    assert result["diagnostic_evidence_complete"] is False


def test_workflow_is_manual_fixed_and_only_uploads_public_evidence():
    path = Path(__file__).parents[1] / ".github/workflows/hypothesis-seed-diagnostic.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert "secrets." not in text and "inputs." not in text
    job = workflow["jobs"]["hypothesis-seed"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "30"
    assert "--kill-after=60s 25m" in text
    upload = job["steps"][-1]
    assert upload["if"] == "always()"
    assert upload["with"]["path"].endswith("/public/")
    assert "python -m scripts.reproduce_hypothesis_seed" in text


@pytest.mark.parametrize("complete,exit_code", [(True, 0), (False, 1)])
def test_exit_code_describes_evidence_not_whether_oracle_scored_one(
    tmp_path, monkeypatch, complete, exit_code
):
    import sys

    diagnostic = module()
    monkeypatch.setattr(
        diagnostic,
        "reproduce",
        AsyncMock(
            return_value={
                "diagnostic_evidence_complete": complete,
                "oracle_all_passed": False,
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["reproduce", "--cache", str(tmp_path / "cache"), "--output", str(tmp_path / "output")],
    )
    assert diagnostic.main() == exit_code


@pytest.mark.parametrize("option", ["--seed", "--task", "--repeats"])
def test_command_cannot_change_fixed_seed_task_or_trial_count(tmp_path, monkeypatch, option):
    import sys

    diagnostic = module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reproduce",
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "output"),
            option,
            "anything",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        diagnostic.main()
    assert caught.value.code == 2
