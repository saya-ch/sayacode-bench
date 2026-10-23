"""无模型单批编排的离线行为测试；CLI 替身不代表真实官方资格成绩。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from scripts import qualify_cloud as module
from scripts.generate_sharded_workflow import restore_archive
from scripts.qualify_fixtures import digest

COHORT = {"ImageOS": "synthetic-ubuntu24", "ImageVersion": "offline-v1", "RUNNER_ARCH": "X64"}


@pytest.fixture
def experiment(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    tasks = [
        {
            "benchmark": "swe-bench-pro-v2",
            "task_id": f"offline-{index}",
            "environment": {
                "build_timeout_sec": 30,
                "docker_image": f"registry.invalid/task:{index}",
            },
            "agent": {"timeout_sec": 30},
            "verifier": {"timeout_sec": 30},
        }
        for index in range(2)
    ]
    initial = tmp_path / "public-initial.json"
    write_json(initial, {"seed": "fixed-offline-seed", "dev": tasks[:1], "holdout": tasks[1:]})
    monkeypatch.setattr(module, "INITIAL_SELECTION", initial)
    monkeypatch.setattr(module, "INITIAL_SHA", file_sha256(initial))
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10**14))
    bundle = tmp_path / "study"
    plan = module.initialize(bundle, "a" * 40, COHORT)
    preparation = tmp_path / "preparation.json"
    probe = tmp_path / "probe.json"
    write_json(
        preparation,
        {
            "passed": True,
            "repository": module.PUBLIC_REPOSITORY,
            "role": "public_official_controls_host_preparation",
            "controls_only": True,
            "runner_image": COHORT,
            "script_sha256": file_sha256(module.ROOT / "scripts/prepare_cloud_runner.py"),
        },
    )
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {"network.py": implementation_identity()["network.py"]},
        },
    )
    image_calls: list[str] = []

    async def image(_: Path, task: dict[str, Any]) -> dict[str, str]:
        image_calls.append(task["task_id"])
        return {"image_id": "synthetic-image"}

    monkeypatch.setattr(module, "prepare_task_image", image)
    cli_calls: list[str] = []

    def native(directory: Path, log: Path, deadline: float) -> int:
        task = module.next_task(directory)
        assert task is not None
        cli_calls.append(task["task_id"])
        key = digest({"benchmark": task["benchmark"], "task_id": task["task_id"]})[:20]
        qualification = directory / "qualification/qualifications" / key
        for name in ("oracle-1", "oracle-2", "oracle-3", "nop-1"):
            attempt = qualification / f"{name}.attempt.json"
            if not attempt.exists():
                write_json(attempt, {"control": name})
                job = directory / "qualification/jobs" / f"{key}-{name}"
                job.mkdir(parents=True)
                (job / "raw.bin").write_bytes(bytes(range(256)))
                write_json(
                    job / "native.json",
                    {"original_job_dir": str(job), "reward": 0 if name == "nop-1" else 1},
                )
                break
        done = len(list(qualification.glob("*.attempt.json"))) == 4
        write_json(qualification / "qualification.json", {"complete": done, "passed": done})
        write_json(directory / "qualification/selection.json", read_json(initial))
        complete = all(module.task_complete(directory, item) for item in tasks)
        write_json(
            directory / "qualification/sanity.json",
            {
                "complete": complete,
                "passed": complete,
                "qualification": {"reason": None if complete else "control_batch_limit_reached"},
            },
        )
        return 0 if complete else 1

    monkeypatch.setattr(module, "call_qualifier", native)
    return SimpleNamespace(
        bundle=bundle,
        plan=plan,
        preparation=preparation,
        probe=probe,
        tasks=tasks,
        images=image_calls,
        calls=cli_calls,
    )


def run(experiment: SimpleNamespace, limit: int = 4) -> dict[str, Any]:
    return module.run_batch(
        experiment.bundle,
        experiment.plan,
        experiment.preparation,
        experiment.probe,
        max_controls=limit,
        deadline=time.time() + 10000,
    )


def test_first_batch_restore_next_batch_and_final_selection_keep_native_paths(
    experiment: SimpleNamespace, tmp_path: Path
) -> None:
    first = run(experiment, 2)
    assert first["new_controls"] == 2
    assert first["complete"] is False and first["continuation_allowed"] is True
    assert first["reason"] == "control_batch_limit_reached"
    manifest = module.pack_bundle(experiment.bundle, tmp_path / "archive")
    expected = {
        path.relative_to(experiment.bundle): path.read_bytes()
        for path in experiment.bundle.rglob("*")
        if path.is_file()
    }
    # 测试只在 pytest 独占临时目录中移动，保留旧现场而不删除或改写原路径正文。
    old = tmp_path / "old-bundle"
    assert experiment.bundle.resolve().is_relative_to(tmp_path.resolve())
    assert old.resolve().is_relative_to(tmp_path.resolve())
    experiment.bundle.rename(old)
    restore_archive(
        tmp_path / "archive/bundle.tar.gz", experiment.bundle, manifest["archive_sha256"]
    )
    for relative, content in expected.items():
        assert (experiment.bundle / relative).read_bytes() == content
    module.initialize(experiment.bundle, "a" * 40, COHORT)
    second = run(experiment, 9)
    assert second["new_controls"] == 2
    assert second["reason"] == "task_boundary" and second["complete"] is False
    assert experiment.calls == ["offline-0"] * 4
    third = run(experiment, 4)
    assert third["new_controls"] == 4 and third["complete"] is True and third["passed"] is True
    assert experiment.calls == ["offline-0"] * 4 + ["offline-1"] * 4
    assert experiment.images == ["offline-0", "offline-0", "offline-1"]
    final = module.pack_bundle(experiment.bundle, tmp_path / "final")
    assert final["complete"] is True
    assert final["model_requests"] == 0 and final["formal_execution_authorized"] is False
    assert final["cloud_artifact_deletion_performed"] is False
    assert "不消耗私有 2000" in final["storage_note"]
    assert Path(final["selection_path"]).is_file() and Path(final["sanity_path"]).is_file()


@pytest.mark.parametrize(
    "change", ["source", "cohort", "selection", "seed", "repeats", "candidate_limit"]
)
def test_restored_frozen_identity_cannot_change(experiment: SimpleNamespace, change: str) -> None:
    source, host = "a" * 40, COHORT
    if change == "source":
        source = "b" * 40
    elif change == "cohort":
        host = {**COHORT, "ImageVersion": "other"}
    elif change == "selection":
        write_json(experiment.bundle / "inputs/initial-selection.json", {"seed": "changed"})
    else:
        path = experiment.bundle / "inputs/cloud-plan.json"
        plan = read_json(path)
        plan[
            {"seed": "seed", "repeats": "oracle_repeats", "candidate_limit": "max_candidates"}[
                change
            ]
        ] = "changed"
        write_json(path, plan)
    with pytest.raises(ValueError):
        module.initialize(experiment.bundle, source, host)
    assert experiment.calls == []


@pytest.mark.parametrize("change", ["cohort", "script", "preparation", "network", "cleanup"])
def test_unconfirmed_host_or_network_preserves_failed_batch_before_native_cli(
    experiment: SimpleNamespace, change: str
) -> None:
    path = (
        experiment.preparation
        if change in {"cohort", "script", "preparation"}
        else experiment.probe
    )
    value = read_json(path)
    if change == "cohort":
        value["runner_image"]["ImageVersion"] = "drift"
    else:
        value[
            {
                "script": "script_sha256",
                "preparation": "passed",
                "network": "passed",
                "cleanup": "cleanup_confirmed",
            }[change]
        ] = False
    write_json(path, value)
    result = run(experiment)
    assert result["error_type"] == "ValueError"
    assert result["new_controls"] == 0 and result["continuation_allowed"] is False
    assert experiment.calls == [] and experiment.images == []
    assert (experiment.bundle / "batches/batch-0001/batch.json").is_file()


def test_official_time_guard_is_partial_without_any_new_control(
    experiment: SimpleNamespace,
) -> None:
    result = module.run_batch(
        experiment.bundle,
        experiment.plan,
        experiment.preparation,
        experiment.probe,
        max_controls=4,
        deadline=time.time() + 100,
    )
    assert result["reason"] == "time_guard" and result["continuation_allowed"] is True
    assert result["complete"] is False and result["error_type"] is None
    assert experiment.calls == [] and experiment.images == []


def test_disk_shortage_preserves_incomplete_without_replacing_task(
    experiment: SimpleNamespace, monkeypatch: Any
) -> None:
    initial = (experiment.bundle / "inputs/initial-selection.json").read_bytes()
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    result = run(experiment)
    assert result["reason"] == "insufficient_disk_headroom"
    assert result["continuation_allowed"] is False and result["complete"] is False
    assert (experiment.bundle / "inputs/initial-selection.json").read_bytes() == initial
    assert experiment.calls == []


@pytest.mark.parametrize(
    "reason",
    [
        "qualification_execution_unconfirmed",
        "candidate_budget_exhausted",
        "eligible_pool_exhausted",
    ],
)
def test_native_unknown_or_exhaustion_never_retries_or_claims_success(
    experiment: SimpleNamespace, monkeypatch: Any, reason: str
) -> None:
    calls = []

    def incomplete(bundle: Path, *_: Any) -> int:
        calls.append(1)
        write_json(
            bundle / "qualification/sanity.json",
            {"complete": False, "passed": False, "qualification": {"reason": reason}},
        )
        return 1

    monkeypatch.setattr(module, "call_qualifier", incomplete)
    result = run(experiment, 8)
    assert len(calls) == 1
    assert result["reason"] == reason and result["continuation_allowed"] is False
    assert result["complete"] is False


def test_native_exception_preserves_log_and_attempts_for_manual_review(
    experiment: SimpleNamespace, monkeypatch: Any
) -> None:
    def broken(bundle: Path, log: Path, _: float) -> int:
        log.write_text("private native traceback", encoding="utf-8")
        write_json(
            bundle / "qualification/qualifications/unknown/oracle-1.attempt.json", {"unknown": True}
        )
        raise subprocess.TimeoutExpired("native qualifier", 10)

    monkeypatch.setattr(module, "call_qualifier", broken)
    result = run(experiment)
    assert result["error_type"] == "TimeoutExpired" and result["new_controls"] == 1
    assert result["continuation_allowed"] is False
    assert (experiment.bundle / "batches/batch-0001/control-1.log").read_text(
        encoding="utf-8"
    ) == "private native traceback"


def test_actual_qualifier_command_keeps_fixed_rules_and_single_control(
    tmp_path: Path, monkeypatch: Any
) -> None:
    def execute(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert command[1:3] == ["-m", "scripts.qualify_fixtures"]
        assert command[command.index("--oracle-repeats") + 1] == "3"
        assert command[command.index("--max-candidates") + 1] == "64"
        assert command[command.index("--max-new-controls") + 1] == "1"
        assert "--model" not in command and kwargs["timeout"] > 0
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", execute)
    assert module.call_qualifier(tmp_path, tmp_path / "entry.log", time.time() + 100) == 1


async def test_first_real_tag_metadata_then_frozen_digest_without_fabrication(
    tmp_path: Path, monkeypatch: Any
) -> None:
    task: dict[str, Any] = {
        "task_id": "synthetic-task",
        "environment": {"docker_image": "registry.invalid/task:original"},
    }
    image: dict[str, Any] = {
        "Id": "sha256:" + "a" * 64,
        "RepoDigests": ["registry.invalid/task@sha256:" + "b" * 64],
        "Os": "linux",
        "Architecture": "amd64",
    }
    pulls = []

    async def docker(*args: Any, **_: Any) -> str:
        pulls.append(args)
        return json.dumps([image]) if args[:2] == ("image", "inspect") else ""

    monkeypatch.setattr(module, "docker", docker)
    first = await module.prepare_task_image(tmp_path, task)
    assert first["repo_digest"] == image["RepoDigests"][0]
    assert pulls[0] == ("pull", task["environment"]["docker_image"])

    async def pin(fixture: dict[str, str]) -> dict[str, str]:
        assert fixture["immutable_image"] == first["repo_digest"]
        return {"expected_image_id": image["Id"], "os": "linux", "architecture": "amd64"}

    monkeypatch.setattr(module, "pin_image", pin)
    assert await module.prepare_task_image(tmp_path, task) == first
    assert len(pulls) == 2


@pytest.mark.parametrize(
    "complete,continuation,error,expected",
    [
        (False, True, None, 0),
        (False, False, None, 1),
        (True, False, None, 0),
        (False, True, "ValueError", 1),
    ],
)
def test_partial_is_distinct_from_qualification_success_in_exit_contract(
    tmp_path: Path,
    monkeypatch: Any,
    complete: bool,
    continuation: bool,
    error: str | None,
    expected: int,
) -> None:
    monkeypatch.setattr(module, "require_public_repository", lambda _: None)
    monkeypatch.setattr(module, "verify_source", lambda *_: None)
    monkeypatch.setattr(module, "bundle_root", lambda _: tmp_path / "new")
    monkeypatch.setattr(module, "initialize", lambda *_: {})
    history = tmp_path / "history.json"
    history.write_text(
        json.dumps(
            [
                {
                    "total_count": 1,
                    "workflow_runs": [
                        {"id": 1, "run_number": 1, "display_title": "qualification offline"}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "run_batch",
        lambda *_args, **_kwargs: {
            "batch": 1,
            "complete": complete,
            "passed": complete,
            "reason": "partial",
            "error_type": error,
            "model_requests": 0,
            "continuation_allowed": continuation,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify_cloud.py",
            "run",
            "--study-id",
            "offline",
            "--source-sha",
            "a" * 40,
            "--workflow",
            "offline.yml",
            "--image-os",
            "ubuntu24",
            "--image-version",
            "fixed",
            "--runner-preparation",
            "prep.json",
            "--probe",
            "probe.json",
            "--deadline-epoch",
            "19800",
            "--repository-metadata",
            "public-repo.json",
            "--first-batch-history",
            str(history),
            "--run-number",
            "1",
        ],
    )
    assert module.main() == expected


def test_template_is_manual_public_only_pinned_without_model_secret_or_automatic_next_batch() -> (
    None
):
    text = module.WORKFLOW.read_text(encoding="utf-8")
    value = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(value["on"]) == {"workflow_dispatch"}
    assert value["on"]["workflow_dispatch"]["inputs"]["acknowledge_execution"]["default"] == "false"
    assert value["on"]["workflow_dispatch"]["inputs"]["max_new_controls"]["default"] == "4"
    assert value["jobs"]["qualify"]["timeout-minutes"] == "360"
    steps = value["jobs"]["qualify"]["steps"]
    assert all(
        module.COMMIT.fullmatch(step["uses"].rsplit("@", 1)[1]) for step in steps if "uses" in step
    )
    assert "secrets." not in text and "gh workflow run" not in text
    assert "prepare_cloud_runner.py" in text and "test_real_docker_network_isolation" in text
    assert "retention-days: 3" in text and "delete-artifact" not in text
    assert "--resume-sha256" in text and "--max-new-controls" in text
    assert sum("gh api" in step.get("run", "") for step in steps) == 2
    assert text.count("gh api") == 3 and "--paginate --slurp" in text
    assert value["run-name"] == "qualification ${{ inputs.study_id }}"
    assert value["concurrency"]["group"] == "qualification-${{ inputs.study_id }}"
    assert value["permissions"] == {"contents": "read", "actions": "read"}
    assert "github.repository == 'saya-ch/sayacode-bench'" in value["jobs"]["qualify"]["if"]
    assert "saya-ch/sayacode-bench-runs" not in text
    assert text.count("d.get('private') is False") == 2
    assert "--controls-only" in text


def test_current_entry_failure_cannot_inherit_previous_batch_continuation(
    experiment: SimpleNamespace, tmp_path: Path
) -> None:
    assert run(experiment, 1)["continuation_allowed"] is True
    report = tmp_path / "failed-entry.json"
    write_json(
        report,
        {
            "complete": False,
            "passed": False,
            "continuation_allowed": False,
            "error_type": "ValueError",
            "exit_code": 2,
        },
    )
    result = module.pack_bundle(experiment.bundle, tmp_path / "failed-archive", entry_report=report)
    assert result["continuation_allowed"] is False and result["complete"] is False
    assert result["entry_error_type"] == "ValueError"
    assert result["entry_report_sha256"] == file_sha256(report)
    # 原始上一批记录不因入口失败被改写。
    assert (
        read_json(experiment.bundle / "batches/batch-0001/batch.json")["continuation_allowed"]
        is True
    )


def test_source_failure_records_only_this_invocation_and_preserves_prior_report(
    tmp_path: Path, monkeypatch: Any
) -> None:
    report = tmp_path / "entry.json"
    monkeypatch.setattr(module, "require_public_repository", lambda _: None)
    monkeypatch.setattr(module, "bundle_root", lambda _: tmp_path / "unused")

    def fail(*_: Any) -> None:
        raise ValueError("private source mismatch detail")

    monkeypatch.setattr(module, "verify_source", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify_cloud.py",
            "run",
            "--study-id",
            "offline",
            "--source-sha",
            "a" * 40,
            "--workflow",
            "offline.yml",
            "--image-os",
            "ubuntu24",
            "--image-version",
            "fixed",
            "--runner-preparation",
            "prep.json",
            "--probe",
            "probe.json",
            "--deadline-epoch",
            "19800",
            "--repository-metadata",
            "public-repo.json",
            "--entry-report",
            str(report),
        ],
    )
    assert module.main() == 2
    original = report.read_bytes()
    value = read_json(report)
    assert value["error_type"] == "ValueError" and value["exit_code"] == 2
    assert value["continuation_allowed"] is False
    assert "private source mismatch detail" not in report.read_text(encoding="utf-8")
    assert module.main() == 2
    assert report.read_bytes() == original


def test_native_actions_history_allows_only_first_study_id_and_not_just_prior_success() -> None:
    current = {"id": 2, "run_number": 2, "display_title": "qualification offline"}
    earlier = {
        "id": 1,
        "run_number": 1,
        "display_title": "qualification another",
        "conclusion": "failure",
    }
    pages = [
        {"total_count": 2, "workflow_runs": [current]},
        {"total_count": 2, "workflow_runs": [earlier]},
    ]
    module.guard_first_batch(pages, "offline", 2)
    earlier["display_title"] = "qualification offline"
    with pytest.raises(ValueError, match="必须显式恢复"):
        module.guard_first_batch(pages, "offline", 2)


@pytest.mark.parametrize(
    "history",
    [
        [],
        {},
        [{"total_count": 2, "workflow_runs": []}],
        [{"total_count": 1, "workflow_runs": ["invalid"]}],
        [
            {
                "total_count": 1,
                "workflow_runs": [
                    {"id": 1, "run_number": 1, "display_title": "qualification another"}
                ],
            }
        ],
        [{"total_count": 2, "workflow_runs": [{"id": 1}, {"id": 1}]}],
    ],
)
def test_uncertain_actions_history_fails_closed(history: Any) -> None:
    with pytest.raises(ValueError):
        module.guard_first_batch(history, "offline", 2)


def test_real_module_entrypoint_works_without_pytest_pythonpath() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.qualify_cloud", "--help"],
        cwd=module.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0
    assert "run" in result.stdout and "archive" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
    assert "python -m scripts.qualify_cloud" in module.WORKFLOW.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "project",
    [
        {"full_name": "saya-ch/sayacode-bench-runs", "private": True, "visibility": "private"},
        {"full_name": "saya-ch/sayacode-bench", "private": True, "visibility": "private"},
        {"full_name": "another/public", "private": False, "visibility": "public"},
    ],
)
def test_public_qualification_rejects_private_model_or_wrong_repository_before_upload(
    tmp_path: Path, monkeypatch: Any, project: dict[str, Any]
) -> None:
    monkeypatch.setattr(module, "require_hosted_runner", lambda **_: None)
    metadata = tmp_path / "repository.json"
    write_json(metadata, project)
    with pytest.raises(ValueError):
        module.require_public_repository(metadata)


def test_public_qualification_accepts_only_explicit_public_controls_host(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls = []
    monkeypatch.setattr(module, "require_hosted_runner", lambda **kwargs: calls.append(kwargs))
    metadata = tmp_path / "repository.json"
    write_json(
        metadata, {"full_name": module.PUBLIC_REPOSITORY, "private": False, "visibility": "public"}
    )
    module.require_public_repository(metadata)
    assert calls == [{"controls_only": True}]


def test_public_archive_refuses_private_or_model_bundle(
    experiment: SimpleNamespace, tmp_path: Path
) -> None:
    path = experiment.bundle / "inputs/cloud-plan.json"
    plan = read_json(path)
    plan["execution_repository"] = "saya-ch/sayacode-bench-runs"
    write_json(path, plan)
    with pytest.raises(ValueError, match="私有或模型"):
        module.pack_bundle(experiment.bundle, tmp_path / "must-not-upload")
    assert not (tmp_path / "must-not-upload").exists()


def test_public_artifact_scope_contains_only_fixed_official_material(
    experiment: SimpleNamespace,
) -> None:
    plan = experiment.plan
    assert plan["execution_repository"] == module.PUBLIC_REPOSITORY
    assert plan["public_artifact_scope"] == list(module.PUBLIC_ARTIFACT_SCOPE)
    assert plan["model_requests_planned"] == 0 and plan["formal_execution_authorized"] is False
    assert not {"product_wheel", "profile", "paid_budget", "private_home"} & set(plan)
    assert (
        "4 CPU/16 GiB" in plan["host_hardware_boundary"]
        and "2 CPU/8 GiB" in plan["host_hardware_boundary"]
    )
