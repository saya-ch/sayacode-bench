"""真实文件归并与恢复拒绝边界；合成 source 不代表模型、Docker 或 Actions 实测。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from test_sharded_workflow import frozen as frozen
from test_sharded_workflow import manifest
from test_shards import experiment as experiment
from test_shards import run

from sayacode_bench import shards, study
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from scripts import generate_sharded_workflow as workflow
from scripts import study_resume as resume


def _history(rows: list[dict[str, Any]], field: str = "workflow_runs") -> list[dict[str, Any]]:
    return [{"total_count": len(rows), field: rows}]


def _run(run_id: int, master: str, **changes: Any) -> dict[str, Any]:
    return {
        "id": run_id,
        "display_title": "study " + master,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": f"2026-10-23T00:00:{run_id:02d}Z",
        **changes,
    }


def _job(job_id: int, run_id: int, name: str, **changes: Any) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": run_id,
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-10-23T00:01:00Z",
        "steps": [],
        **changes,
    }


@pytest.fixture
def recovery(frozen: Any, tmp_path: Path, request: Any) -> Any:
    """仅生成可映射的合同，不声称此 Windows 数据已做原生核验。"""
    k, run_id = getattr(request, "param", 2), 11
    original = frozen.plan["bundle_root"]
    previous = None
    for index, entry in enumerate(frozen.plan["schedule"][:k], 1):
        directory = frozen.bundle / "shards" / entry["shard_id"]
        ledger_path = directory / "ledger.json"
        write_json(ledger_path, {"phase_records": ["synthetic"] * index})
        ledger = {
            "path": original + f"/shards/{entry['shard_id']}/ledger.json",
            "sha256": file_sha256(ledger_path),
        }
        native_path = directory / "shard-receipt.json"
        write_json(
            native_path,
            {
                "plan_sha256": file_sha256(frozen.path),
                "sequence": index,
                "complete": True,
                "continuation_allowed": True,
                "ledger_after": ledger,
                "previous_receipt": previous,
            },
        )
        previous = {
            "path": original + f"/shards/{entry['shard_id']}/shard-receipt.json",
            "sha256": file_sha256(native_path),
        }
        identity = {"run_id": run_id, "run_attempt": 1, "job_key": f"shard_{index:04d}"}
        write_json(
            frozen.bundle / "orchestration" / entry["shard_id"] / "dispatch.json",
            {
                "actions_identity": identity,
                "plan_sha256": file_sha256(frozen.path),
                "shard_id": entry["shard_id"],
                "receipt_complete": True,
                "continuation_allowed": True,
                "credential_cleanup_confirmed": True,
                "host_cohort_confirmed": True,
                "native_cli_returncode": 0,
                "error_type": None,
                "receipt_sha256": previous["sha256"],
                "ledger_sha256": ledger["sha256"],
            },
        )
    seed = tmp_path / "seed.json"
    write_json(seed, manifest())
    archive = tmp_path / "archive-receipt.json"
    write_json(
        archive,
        {
            "transfer_status": "completed",
            "receipt_complete": True,
            "host_cohort_confirmed": True,
            "archive_sha256": manifest()["archive_sha256"],
            "archive_bytes": manifest()["archive_size"],
            "plan_sha256": file_sha256(frozen.path),
            "receipt_sha256": previous["sha256"],
            "ledger_sha256": ledger["sha256"],
            "actions_identity": identity,
            "shard_id": frozen.plan["schedule"][k - 1]["shard_id"],
            "continuation_allowed": True,
        },
    )
    history = _history([_run(run_id, frozen.plan["master"]["sha256"])])
    history_path = tmp_path / "history.json"
    write_json(history_path, history)
    jobs = _history(
        [
            _job(100, run_id, "review"),
            *[_job(100 + index, run_id, f"shard_{index:04d} / run") for index in range(1, k + 1)],
        ],
        "jobs",
    )
    jobs_dir = tmp_path / "jobs"
    write_json(jobs_dir / f"{run_id}.json", jobs)
    receipt_path = tmp_path / "resume.json"
    receipt = resume.freeze_resume_receipt(
        frozen.path,
        frozen.bundle,
        receipt_path,
        prefix_length=k,
        seed_manifest=seed,
        archive_receipt=archive,
        history=history_path,
        jobs_directory=jobs_dir,
        plan=frozen.plan,
        master=frozen.master,
        runner=frozen.runner,
    )
    return SimpleNamespace(
        frozen=frozen,
        path=receipt_path,
        receipt=receipt,
        history=history,
        jobs={str(run_id): jobs},
        seed=seed,
        archive=archive,
        history_path=history_path,
        jobs_dir=jobs_dir,
    )


def test_physical_batch_preserves_original_schedule_and_never_finalizes(
    frozen: Any, tmp_path: Path
) -> None:
    seed, output = tmp_path / "seed.json", tmp_path / "batch.json"
    write_json(seed, manifest())
    before = frozen.path.read_bytes()
    result = workflow.generate(
        frozen.path, frozen.bundle, output, seed_manifest=seed, through_sequence=2
    )
    dag = read_json(output)
    assert list(dag["jobs"]) == ["review", "shard_0001", "shard_0002"]
    assert result["shard_count"] == 48 and result["dispatched_shard_count"] == 2
    assert result["physical_batch_only"] is True
    assert frozen.path.read_bytes() == before


def test_resume_generation_starts_at_next_original_sequence(recovery: Any, tmp_path: Path) -> None:
    r, output = recovery, tmp_path / "continued.json"
    result = workflow.generate(
        r.frozen.path,
        r.frozen.bundle,
        output,
        seed_manifest=r.seed,
        resume_receipt=r.path,
        through_sequence=4,
    )
    jobs = read_json(output)["jobs"]
    assert list(jobs) == ["review", "shard_0003", "shard_0004"]
    first = jobs["shard_0003"]
    assert first["needs"] == ["review"]
    assert first["with"]["previous_receipt_sha256"] == r.receipt["last_receipt"]["sha256"]
    assert first["with"]["previous_ledger_sha256"] == r.receipt["ledger"]["sha256"]
    assert jobs["shard_0004"]["needs"] == ["shard_0003"]
    assert result["native_resume_validation_performed"] is False
    assert "resume-review" in jobs["review"]["steps"][-1]["run"]
    assert "secrets." not in json.dumps(jobs["review"])


@pytest.mark.parametrize("recovery", [48], indirect=True)
def test_full_prefix_generates_only_review_and_merge_without_model_secret(
    recovery: Any, tmp_path: Path
) -> None:
    r, output = recovery, tmp_path / "merge-only.json"
    workflow.generate(
        r.frozen.path, r.frozen.bundle, output, seed_manifest=r.seed, resume_receipt=r.path
    )
    jobs = read_json(output)["jobs"]
    assert list(jobs) == ["review", "merge"]
    assert jobs["merge"]["needs"] == ["review"]
    assert "inputs.execute_models" in jobs["merge"]["if"]
    assert "secrets." not in json.dumps(jobs)
    assert jobs["merge"]["with"]["previous_ledger_sha256"] == r.receipt["ledger"]["sha256"]


@pytest.mark.parametrize("recovery", [48], indirect=True)
@pytest.mark.parametrize("stop", sorted(shards.MERGE_ONLY_STOP_REASONS))
def test_full_prefix_dispatch_threshold_still_generates_merge_only(
    recovery: Any, tmp_path: Path, stop: str
) -> None:
    r = recovery
    entry = r.frozen.plan["schedule"][-1]
    native_path = r.frozen.bundle / "shards" / entry["shard_id"] / "shard-receipt.json"
    native = read_json(native_path)
    native.update(continuation_allowed=False, stop_reason=stop)
    write_json(native_path, native)
    r.receipt["last_receipt"]["sha256"] = file_sha256(native_path)
    status_path = r.frozen.bundle / "orchestration" / entry["shard_id"] / "dispatch.json"
    status = read_json(status_path)
    status.update(continuation_allowed=False, receipt_sha256=file_sha256(native_path))
    write_json(status_path, status)
    r.receipt["archive_receipt"].update(
        continuation_allowed=False, receipt_sha256=file_sha256(native_path)
    )
    write_json(r.path, r.receipt)
    output = tmp_path / "threshold-merge.json"
    workflow.generate(
        r.frozen.path, r.frozen.bundle, output, seed_manifest=r.seed, resume_receipt=r.path
    )
    assert list(read_json(output)["jobs"]) == ["review", "merge"]
    assert "secrets." not in json.dumps(read_json(output))


def test_frozen_resume_is_exclusive_and_requires_all_bound_files(recovery: Any) -> None:
    r = recovery
    with pytest.raises(FileExistsError):
        resume.freeze_resume_receipt(
            r.frozen.path,
            r.frozen.bundle,
            r.path,
            prefix_length=2,
            seed_manifest=r.seed,
            archive_receipt=r.archive,
            history=r.history_path,
            jobs_directory=r.jobs_dir,
            plan=r.frozen.plan,
            master=r.frozen.master,
            runner=r.frozen.runner,
        )
    r.frozen.bundle.joinpath(
        "orchestration", r.frozen.plan["schedule"][0]["shard_id"], "dispatch.json"
    ).unlink()
    with pytest.raises(FileNotFoundError):
        resume._validate_resume(
            r.receipt,
            r.frozen.path,
            r.frozen.plan,
            r.frozen.master,
            r.frozen.runner,
            r.frozen.bundle,
        )


@pytest.mark.parametrize(
    "case",
    [
        "later_same",
        "later_other",
        "inflight",
        "retry",
        "missing_page",
        "failed_job",
        "unknown_job",
        "started_suffix",
        "missing_job",
        "job_changed",
    ],
)
def test_resume_history_rejects_unprovable_or_stale_cases(recovery: Any, case: str) -> None:
    r = recovery
    history, jobs = copy.deepcopy(r.history), copy.deepcopy(r.jobs)
    if case in {"later_same", "later_other"}:
        digest = r.receipt["master_sha256"] if case == "later_same" else "c" * 64
        history = _history([*history[0]["workflow_runs"], _run(12, digest)])
    elif case == "inflight":
        history[0]["workflow_runs"][0]["status"] = "in_progress"
    elif case == "retry":
        history[0]["workflow_runs"][0]["run_attempt"] = 2
    elif case == "missing_page":
        history[0]["total_count"] = 2
    elif case == "failed_job":
        jobs["11"][0]["jobs"][1]["conclusion"] = "failure"
    elif case == "unknown_job":
        jobs["11"][0]["jobs"][1]["name"] = "unknown / run"
    elif case == "started_suffix":
        jobs["11"][0]["jobs"][2]["name"] = "shard_0003 / run"
    elif case == "missing_job":
        jobs = {}
    else:
        jobs["11"][0]["jobs"][1]["id"] = 1001
    with pytest.raises(ValueError):
        resume._resume_history(r.receipt, history, jobs)


def test_live_review_excludes_only_current_run_and_rejects_prior_other_master_spend(
    recovery: Any,
) -> None:
    r = recovery
    live = _history(
        [*r.history[0]["workflow_runs"], _run(12, r.receipt["master_sha256"], status="in_progress")]
    )
    assert (
        resume._resume_history(r.receipt, live, r.jobs, current_run_id=12)
        == r.receipt["started_shards"]
    )
    old = copy.deepcopy(r.receipt)
    old["budget_history_run_ids"] = [11, 12]
    prior_other = _history([*r.history[0]["workflow_runs"], _run(12, "c" * 64)])
    with pytest.raises(ValueError, match="冻结 prior"):
        resume._resume_history(old, prior_other, r.jobs)


def test_complete_prefix_can_span_multiple_successful_physical_batches(recovery: Any) -> None:
    declaration = copy.deepcopy(recovery.receipt)
    declaration["prior_run_ids"] = declaration["budget_history_run_ids"] = [11, 12]
    declaration["started_shards"][1].update(run_id=12, job_id=202)
    history = _history([_run(run_id, declaration["master_sha256"]) for run_id in (11, 12)])
    jobs = {
        "11": _history([_job(100, 11, "review"), _job(101, 11, "shard_0001 / run")], "jobs"),
        "12": _history([_job(200, 12, "review"), _job(202, 12, "shard_0002 / run")], "jobs"),
    }
    assert resume._resume_history(declaration, history, jobs) == declaration["started_shards"]


@pytest.mark.parametrize(
    "change",
    [
        "plan_sha256",
        "master_sha256",
        "schedule_sha256",
        "implementation",
        "financial_prior_sha256",
        "archive_unknown",
        "ledger",
        "legacy_dispatch",
    ],
)
def test_resume_binding_and_transfer_unknown_fail_closed(recovery: Any, change: str) -> None:
    r, value = recovery, copy.deepcopy(recovery.receipt)
    if change == "archive_unknown":
        value["archive_receipt"]["transfer_status"] = "failed"
    elif change == "ledger":
        value["ledger"]["sha256"] = "d" * 64
    elif change == "legacy_dispatch":
        path = (
            r.frozen.bundle
            / "orchestration"
            / r.frozen.plan["schedule"][0]["shard_id"]
            / "dispatch.json"
        )
        status = read_json(path)
        del status["actions_identity"]
        write_json(path, status)
    else:
        value[change] = {} if change == "implementation" else "d" * 64
    with pytest.raises(ValueError):
        resume._validate_resume(
            value, r.frozen.path, r.frozen.plan, r.frozen.master, r.frozen.runner, r.frozen.bundle
        )


async def test_native_resume_keeps_zero_score_and_rejects_started_next_source(
    experiment: Any,
) -> None:
    e = experiment
    _, first = await run(e, 0, None)
    _, tail = await run(e, 1, first)
    checked = shards.verify_resume_prefix(e.plan_path, 2)
    assert checked["last_receipt"]["sha256"] == file_sha256(tail)
    rows = read_json(Path(checked["ledger"]["path"]))["phase_records"]
    assert any(row["success"] is False for row in rows)
    third = e.bundle / "shards" / e.plan["schedule"][2]["shard_id"]
    write_json(third / "attempt.json", {"started": True})
    with pytest.raises(ValueError, match="剩余片已有"):
        shards.verify_resume_prefix(e.plan_path, 2)
    assert len(e.calls) == 2


@pytest.mark.parametrize("kind", ["token", "paid"])
async def test_native_complete_final_threshold_permits_only_merge(
    experiment: Any, kind: str
) -> None:
    e = experiment
    master = read_json(e.manifest_path)
    if kind == "token":
        master["reported_token_limit"] = 880
    else:
        master["paid_budget"]["limit_cny"] = 0.0028
    write_json(e.manifest_path, master)
    write_json(
        e.authorization,
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(e.manifest_path),
        },
    )
    e.plan_path = e.bundle / "final-stop-plan.json"
    e.plan = shards.freeze_execution_plan(
        e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
    )
    previous = None
    for index in range(8):
        native, previous = await run(e, index, previous)
    assert native["complete"] is True and native["continuation_allowed"] is False
    checked = shards.verify_resume_prefix(e.plan_path, 8)
    assert checked["merge_only"] is True
    merged = shards.merge_shards(
        e.plan_path, [previous], workflow._merge_directory(e.plan) / "final"
    )
    assert merged["complete"] is True
    assert merged["validity_issues"] == []


async def test_resumed_prefix_to_n_final_merge_checks_full_chain_not_empty_suffix(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment
    previous = None
    for index in range(2):
        native, previous = await run(e, index, previous)
    declaration = {
        "prefix_length": 2,
        "last_receipt": shards._ref(previous),
        "ledger": native["ledger_after"],
    }
    contract = {
        "plan_relative_path": e.plan_path.relative_to(e.bundle).as_posix(),
        "resume_receipt": declaration,
        "resume_receipt_sha256": workflow._hash(declaration),
    }
    monkeypatch.setattr(workflow, "load_contract", lambda _: (contract, e.plan, e.manifest))
    monkeypatch.setattr(workflow, "_mapped", lambda reference, *_: Path(reference["path"]))
    # 合同映射已有独立回归；此处真实运行完整原生 receipt 链，定位 k→N 的模式边界。
    monkeypatch.setattr(resume, "_validate_resume", lambda *_: None)
    assert workflow.verify_resume_contract("offline")["prefix_length"] == 2
    for index in range(2, 8):
        _, previous = await run(e, index, previous)
    with pytest.raises(ValueError, match="剩余片已有"):
        workflow.verify_resume_contract("offline")
    checked = workflow.verify_resume_contract("offline", mode="merge")
    assert checked["prefix_length"] == 8
    assert checked["last_receipt"] == shards._ref(previous)
    merged = shards.merge_shards(
        e.plan_path, [previous], workflow._merge_directory(e.plan) / "final"
    )
    assert merged["complete"] is True and merged["missing_trials"] == 0


@pytest.mark.parametrize(
    "case",
    ["source_missing", "extra_source", "inflight", "usage_unknown", "budget_stop", "windows"],
)
async def test_native_resume_rejects_incomplete_physical_evidence(
    experiment: Any, monkeypatch: Any, case: str
) -> None:
    e = experiment
    if case == "budget_stop":
        master = read_json(e.manifest_path)
        master["reported_token_limit"] = 1
        write_json(e.manifest_path, master)
        write_json(
            e.authorization,
            {
                "authorized": True,
                "phase": "dev",
                "master_manifest_sha256": file_sha256(e.manifest_path),
            },
        )
        e.plan_path = e.bundle / "stop-plan.json"
        e.plan = shards.freeze_execution_plan(
            e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
        )
    _, tail = await run(e, 0, None)
    directory = tail.parent
    if case == "source_missing":
        next((directory / "run/jobs").glob("*/**/result.json")).unlink()
    elif case == "extra_source":
        (directory / "run/jobs/unaccounted-source").mkdir()
    elif case == "inflight":
        write_json(directory / "run/inflight.json", {"state": "unknown"})
    elif case == "usage_unknown":
        native_path = next((directory / "run/jobs").glob("*/**/agent/sayacode/result.json"))
        value = read_json(native_path)
        value["usage"]["missing_usage_calls"] = 1
        value["terminal_http_statuses"] = [503]
        write_json(native_path, value)
    elif case == "windows":
        monkeypatch.setattr(shards.platform, "system", lambda: "Windows")
    with pytest.raises((ValueError, FileNotFoundError)):
        shards.verify_resume_prefix(e.plan_path, 1)


async def test_two_phases_share_bundle_keep_prior_paths_and_merge_separately(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment

    def local_cli(arguments: list[str], _log: Path, **_: Any) -> int:
        assert arguments[0] == "merge-shards"
        plan = Path(arguments[arguments.index("--plan") + 1])
        output = Path(arguments[arguments.index("--output") + 1])
        receipts = [
            Path(arguments[index + 1])
            for index, value in enumerate(arguments)
            if value == "--receipt"
        ]
        merged = shards.merge_shards(plan, receipts, output)
        return 0 if merged["complete"] else 1

    monkeypatch.setattr(workflow, "_cli", local_cli)
    monkeypatch.setattr(
        workflow,
        "load_contract",
        lambda _: (
            {"plan_relative_path": e.plan_path.relative_to(e.bundle).as_posix()},
            e.plan,
            e.manifest,
        ),
    )
    previous = None
    for index in range(8):
        _, previous = await run(e, index, previous)
        if index == 0:
            assert (
                workflow.merge("offline", output=workflow._merge_directory(e.plan) / "prefix-0001")
                == 1
            )
    assert workflow.merge("offline") == 0
    dev_directory = workflow._merge_directory(e.plan) / "final"
    before = {
        path: file_sha256(path)
        for path in [e.plan_path, e.manifest_path, previous, dev_directory / "records.jsonl"]
    }
    dev_rows = shards._rows(dev_directory / "records.jsonl")
    master = copy.deepcopy(e.manifest)
    master.update(phase="holdout", candidate="candidate")
    master["paid_budget"] = study.freeze_paid_budget(
        limit_cny=100,
        price_snapshot=e.inputs / "prices.json",
        prior_records=[dev_directory / "accounting-records.jsonl"],
        paid_endpoints=["remote"],
    )
    e.manifest_path = e.inputs / "holdout-master.json"
    write_json(e.manifest_path, master)
    e.authorization = e.inputs / "holdout-authorization.json"
    write_json(
        e.authorization,
        {
            "authorized": True,
            "phase": "holdout",
            "master_manifest_sha256": file_sha256(e.manifest_path),
        },
    )
    e.plan_path = e.bundle / "holdout-plan.json"
    e.plan = shards.freeze_execution_plan(
        e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
    )
    e.manifest = master
    offline_execute = study.run_phase

    async def distinct_requests(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await offline_execute(*args, **kwargs)
        rows_path = args[1] / "records.jsonl"
        rows = shards._rows(rows_path)
        rows[-1]["request_sha256"] = workflow._hash(["holdout", len(rows)])
        shards._write_rows(rows_path, rows)
        return result

    monkeypatch.setattr(study, "run_phase", distinct_requests)
    previous = None
    for index in range(8):
        _, previous = await run(e, index, previous)
        if index == 0:
            assert (
                workflow.merge("offline", output=workflow._merge_directory(e.plan) / "prefix-0001")
                == 1
            )
    assert workflow.merge("offline") == 0
    holdout_directory = workflow._merge_directory(e.plan) / "final"
    assert holdout_directory != dev_directory
    assert all(file_sha256(path) == digest for path, digest in before.items())
    assert all(Path(row["source_job"]).is_dir() for row in dev_rows)
    assert len(shards._rows(holdout_directory / "accounting-records.jsonl")) == 16
    assert read_json(holdout_directory / "merge-receipt.json")["complete"] is True


def test_template_verifies_resume_before_model_secret_and_scopes_merge_files() -> None:
    template = yaml.load(workflow.TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = template["jobs"]["run"]["steps"]
    verify = next(
        index for index, step in enumerate(steps) if " resume-verify " in step.get("run", "")
    )
    execute = next(index for index, step in enumerate(steps) if " execute " in step.get("run", ""))
    assert verify < execute
    assert "secrets." not in json.dumps(steps[verify])
    assert "merge_relative_directory" in workflow.TEMPLATE.read_text(encoding="utf-8")


def test_actions_identity_requires_explicit_study_job_context(monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.delenv("SAYACODE_ACTIONS_JOB_KEY", raising=False)
    assert workflow._actions_identity() is None
    monkeypatch.setenv("SAYACODE_ACTIONS_JOB_KEY", "shard_0002")
    assert workflow._actions_identity() == {
        "run_id": 123,
        "run_attempt": 1,
        "job_key": "shard_0002",
    }
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(ValueError):
        workflow._actions_identity()
