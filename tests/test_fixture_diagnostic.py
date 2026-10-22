"""云端交叉诊断仅处理两道已知题，不调用模型，也不挑选参考解成绩。"""

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

from sayacode_bench.artifacts import read_json, write_json


def module() -> Any:
    source = Path(__file__).parents[1] / "scripts" / "diagnose_fixtures.py"
    spec = importlib.util.spec_from_file_location("diagnose_script", source)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_plan_has_only_two_explicit_tasks_and_fixed_eight_jobs() -> None:
    plan = module().fixed_plan()
    assert len(plan["fixtures"]) == 2
    assert len(plan["schedule"]) == 8
    assert plan["revision"] == "66f92766bba642462d4bbe5479e83f91f9211862"
    for fixture in plan["fixtures"]:
        rows = [row for row in plan["schedule"] if row["fixture"] == fixture["name"]]
        assert [(row["agent"], row["repeat"]) for row in rows] == [
            ("oracle", 1),
            ("oracle", 2),
            ("oracle", 3),
            ("nop", 1),
        ]
        assert fixture["immutable_image"].endswith("@" + fixture["digest"])
        assert fixture["original_image_reference"].endswith(":" + fixture["task_id"])
    assert plan["model_requests"] == 0
    assert plan["formal_comparison_eligible"] is False


async def test_image_is_pulled_by_digest_then_tagged_without_assuming_config_digest(
    monkeypatch: Any,
) -> None:
    diagnostic = module()
    fixture = diagnostic.fixed_plan()["fixtures"][0]
    calls = []

    async def docker(*args: str, **kwargs: Any) -> str:
        calls.append(args)
        if args[0] == "image":
            return json.dumps(
                [
                    {
                        "Id": "sha256:" + "a" * 64,
                        "RepoDigests": [fixture["immutable_image"]],
                        "Architecture": "amd64",
                        "Os": "linux",
                    }
                ]
            )
        return ""

    monkeypatch.setattr(diagnostic, "docker", docker)
    result = await diagnostic.pin_image(fixture)
    assert calls[0] == ("pull", fixture["immutable_image"])
    assert calls[1] == ("tag", fixture["immutable_image"], fixture["original_image_reference"])
    assert result["expected_image_id"] == "sha256:" + "a" * 64
    assert result["expected_image_id"] != fixture["digest"]


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: Any) -> Any:
    diagnostic = module()
    tasks = tmp_path / "source" / "tasks"
    for fixture in diagnostic.fixed_plan()["fixtures"]:
        task = tasks / fixture["task_id"]
        task.mkdir(parents=True)
        (task / "task.toml").write_text(
            "[environment]\ncpus=1\nmemory_mb=4096\nstorage_mb=10240\n"
            f'docker_image="{fixture["original_image_reference"]}"\n',
            encoding="utf-8",
        )
    snapshot = SimpleNamespace(tasks_path=tasks, spec=SimpleNamespace(revision=diagnostic.REVISION))
    monkeypatch.setattr(diagnostic, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(diagnostic, "version", lambda *args: "0.24.0")

    async def pin(fixture: dict[str, Any]) -> dict[str, Any]:
        return {
            "expected_image_id": "sha256:" + "a" * 64,
            "expected_repo_digest": fixture["immutable_image"],
            "os": "linux",
            "architecture": "amd64",
        }

    monkeypatch.setattr(diagnostic, "pin_image", pin)
    calls: list[dict[str, Any]] = []

    async def execute(
        task: Path,
        raw: Path,
        name: str,
        agent: dict[str, Any],
        environment: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(
            {"task": task.name, "name": name, "agent": agent, "environment": environment, **kwargs}
        )
        fixture = next(
            item for item in diagnostic.fixed_plan()["fixtures"] if item["task_id"] == task.name
        )
        trial = raw / name / "instance_fake__trial"
        write_json(trial / "result.json", {"task_name": task.name})
        write_json(
            trial / "runtime.json",
            {
                "available": True,
                "image_id": "sha256:" + "a" * 64,
                "repo_digests": [fixture["immutable_image"]],
                "docker_limits": {"Memory": 4294967296, "MemorySwap": 8589934592},
            },
        )
        (trial / "agent").mkdir()
        (trial / "agent" / "solution.log").write_text(
            "DO-NOT-PUBLISH-GOLD-CONTENT", encoding="utf-8"
        )
        (trial / "agent" / "model.patch").write_text("DO-NOT-PUBLISH-PATCH", encoding="utf-8")
        verifier = trial / "verifier"
        verifier.mkdir()
        (verifier / "run-script-stderr.txt").write_text(
            "Segmentation fault (core dumped)\nTypeError: DO-NOT-PUBLISH-PRIVATE-ERROR-TEXT\n",
            encoding="utf-8",
        )
        (verifier / "test-stdout.txt").write_text(
            "Required tests: 12\nPassed tests: 11\n", encoding="utf-8"
        )
        reward = 0 if agent["name"] == "nop" or kwargs["repeat"] == 2 else 1
        return {
            "job_dir": str(raw / name),
            "status": "completed",
            "original_reward": reward,
            "verified": True,
            "duration_seconds": 3.0,
        }

    monkeypatch.setattr(diagnostic, "run_official_trial", execute)
    return SimpleNamespace(
        diagnostic=diagnostic,
        snapshot=snapshot,
        calls=calls,
        cache=tmp_path / "cache",
        output=tmp_path / "output",
    )


async def test_all_eight_outcomes_are_retained_and_artifacts_exclude_private_raw_jobs(
    scenario: Any,
) -> None:
    result = await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    assert len(scenario.calls) == 8
    assert result["all_jobs_attempted"] and result["all_expected_images_confirmed"]
    assert result["formal_comparison_eligible"] is False
    assert result["affects_local_scores"] is False
    assert result["fixtures"]["calibration-qutebrowser"]["oracle_rewards"] == [1, 0, 1]
    assert result["fixtures"]["development-openlibrary"]["oracle_rewards"] == [1, 0, 1]
    assert all(call["canonical_model"] == "not_used" for call in scenario.calls)
    assert all(call["agent"] in ({"name": "oracle"}, {"name": "nop"}) for call in scenario.calls)
    assert all(
        call["environment"]["kwargs"] == {"messages_upstream": "http://127.0.0.1:9/v1/messages"}
        for call in scenario.calls
    )
    public = scenario.output / "public"
    files = [path for path in public.rglob("*") if path.is_file()]
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "DO-NOT-PUBLISH" not in serialized
    assert not any(path.suffix == ".patch" or "solution" in path.name for path in files)
    assert len(list(public.glob("trials/*/runtime.json"))) == 8
    observations = read_json(next(public.glob("trials/*/verifier-observations.json")))
    assert observations["run-script-stderr.txt"]["exception_types"] == {"TypeError": 1}
    assert observations["run-script-stderr.txt"]["segmentation_fault"] is True
    assert observations["test-stdout.txt"]["required_tests"] == 12


async def test_one_execution_error_does_not_selectively_skip_later_fixed_jobs(
    scenario: Any,
    monkeypatch: Any,
) -> None:
    execute = scenario.diagnostic.run_official_trial

    async def failing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if args[2] == "cross-host-1-oracle-1":
            raise OSError("unpublished runtime details")
        return await execute(*args, **kwargs)

    mocked = AsyncMock(side_effect=failing)
    monkeypatch.setattr(scenario.diagnostic, "run_official_trial", mocked)
    result = await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    records = json.loads((scenario.output / "public" / "records.json").read_text(encoding="utf-8"))
    assert mocked.await_count == 8 and len(records) == 8
    assert records[0]["status"] == "diagnostic_error"
    assert records[0]["error_type"] == "OSError"
    assert result["all_jobs_attempted"] is True
    assert result["all_expected_images_confirmed"] is False


async def test_image_preparation_failure_is_explicit_and_other_fixture_still_runs(
    scenario: Any,
    monkeypatch: Any,
) -> None:
    original = scenario.diagnostic.pin_image

    async def pin(fixture: dict[str, Any]) -> dict[str, Any]:
        if fixture["name"] == "calibration-qutebrowser":
            raise ValueError("image identity unavailable")
        return await original(fixture)

    monkeypatch.setattr(scenario.diagnostic, "pin_image", pin)
    result = await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    records = json.loads((scenario.output / "public" / "records.json").read_text(encoding="utf-8"))
    assert len(records) == 8 and len(scenario.calls) == 4
    assert all(
        row["status"] == "preparation_failed" and not row["attempted"] for row in records[:4]
    )
    assert result["all_jobs_attempted"] is False


async def test_evidence_collection_failure_keeps_native_rewards_and_runs_all_jobs(
    scenario: Any,
    monkeypatch: Any,
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("runtime metadata unreadable")

    monkeypatch.setattr(scenario.diagnostic, "collect_trial", unavailable)
    result = await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    records = json.loads((scenario.output / "public" / "records.json").read_text(encoding="utf-8"))
    assert len(scenario.calls) == 8 and result["recorded_jobs"] == 8
    assert records[0]["native_status"] == "completed"
    assert records[0]["original_reward"] == 1
    assert records[0]["status"] == "diagnostic_error"
    assert result["all_expected_images_confirmed"] is False


async def test_cancelled_diagnostic_keeps_partial_counts_not_fake_eight_failures(
    scenario: Any,
    monkeypatch: Any,
) -> None:
    execute = scenario.diagnostic.run_official_trial

    async def cancelled(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if args[2] == "cross-host-1-oracle-2":
            raise asyncio.CancelledError()
        return await execute(*args, **kwargs)

    monkeypatch.setattr(scenario.diagnostic, "run_official_trial", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    result = read_json(scenario.output / "public" / "summary.json")
    assert result["interrupted"] is True
    assert result["recorded_jobs"] == 1 and result["planned_jobs"] == 8


async def test_existing_output_cannot_be_resumed_or_overwritten(scenario: Any) -> None:
    scenario.output.mkdir()
    with pytest.raises(FileExistsError):
        await scenario.diagnostic.diagnose(scenario.cache, scenario.output)
    assert not scenario.calls


def test_task_metadata_does_not_require_instructions_or_solution(scenario: Any) -> None:
    fixture = scenario.diagnostic.fixed_plan()["fixtures"][0]
    metadata = scenario.diagnostic.fixture_metadata(scenario.snapshot, fixture)
    assert metadata["official_resources"]["memory_mb"] == 4096
    assert metadata["task_config_sha256"]


def test_workflow_is_manual_and_uploads_only_the_minimal_public_directory() -> None:
    path = Path(__file__).parents[1] / ".github" / "workflows" / "fixture-diagnostic.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    job = workflow["jobs"]["fixture-diagnostic"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "30"
    assert workflow["permissions"] == {"contents": "read"}
    uploads = [step for step in job["steps"] if "upload-artifact" in step.get("uses", "")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"].endswith("/fixture-diagnostic/public/")
    assert uploads[0]["if"] == "always()"
    assert "secrets." not in text and "api_key" not in text
