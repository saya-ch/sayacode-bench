"""最终阶段行政装配的离线边界；不把 CLI 替身认定为原生模型或云端验证。"""

from __future__ import annotations

import shutil
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from scripts import prepare_final_study as module

COHORT = {"ImageOS": "offline", "ImageVersion": "offline", "RUNNER_ARCH": "X64"}
SOURCE = "a" * 40


@pytest.fixture
def completed(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    bundle = tmp_path / "bundle"
    inputs = bundle / "inputs/restart-v2"
    inputs.mkdir(parents=True)
    monkeypatch.setattr(module, "BUNDLE", bundle)
    master = {
        "tasks": [{"task_id": f"fixture-{index}"} for index in range(8)],
        "repeats": 2,
        "configurations": ["baseline", "diagnostic", "focused"],
    }
    master_path = inputs / "primary-dev.json"
    write_json(master_path, master)
    plan = {
        "master": {"path": str(master_path), "sha256": file_sha256(master_path)},
        "schedule": [{"shard_id": f"dev-{index:04}"} for index in range(48)],
    }
    plan_path = bundle / "primary-dev-v2-plan.json"
    write_json(plan_path, plan)
    runner = {"public_source_sha": SOURCE, "host_cohort": COHORT}
    monkeypatch.setattr(module, "inspect_plan", lambda *args: (plan, master, runner))
    final = bundle / "merged" / plan["master"]["sha256"] / "final"
    final.mkdir(parents=True)
    for row in plan["schedule"]:
        write_json(bundle / "shards" / row["shard_id"] / "shard-receipt.json", {"offline": True})
    for name in ("records.jsonl", "accounting-records.jsonl"):
        (final / name).write_text('{"offline":true}\n', encoding="utf-8")
    receipt = {
        "complete": True,
        "missing_trials": 0,
        "validity_issues": [],
        "plan_sha256": file_sha256(plan_path),
        "summary": {
            "paid_budget": {"evidence_valid": True, "usage_complete": True, "stop_reason": None}
        },
        "records": {
            "path": str(final / "records.jsonl"),
            "sha256": file_sha256(final / "records.jsonl"),
        },
    }
    write_json(final / "merge-receipt.json", receipt)
    candidate = inputs / "primary-candidate.json"
    write_json(
        candidate,
        {
            "dev_manifest": plan["master"],
            "dev_records": receipt["records"],
            "selected": "focused",
            "baseline": "baseline",
        },
    )
    output = tmp_path / "review"
    output.mkdir()
    calls = []

    def cli(arguments: list[str], log: Path) -> None:
        assert arguments[0] == "merge-shards"
        calls.append(arguments)
        review = Path(arguments[arguments.index("--output") + 1])
        write_json(review / "merge-receipt.json", receipt)
        for name in ("records.jsonl", "accounting-records.jsonl"):
            (review / name).write_text('{"offline":true}\n', encoding="utf-8")

    monkeypatch.setattr(module, "_cli", cli)
    return SimpleNamespace(
        bundle=bundle,
        final=final,
        output=output,
        plan=plan,
        master=master,
        candidate=candidate,
        receipt=receipt,
        calls=calls,
    )


def review(completed: SimpleNamespace) -> tuple[dict[str, Any], Path]:
    return module.review_completed(
        "primary-dev",
        8,
        2,
        ["baseline", "diagnostic", "focused"],
        cohort=COHORT,
        output=completed.output,
        source_sha=SOURCE,
    )


@pytest.mark.parametrize("damage", ["missing_final", "incomplete", "missing_shard"])
def test_missing_or_partial_previous_stage_cannot_reach_cli(
    completed: SimpleNamespace, damage: str
) -> None:
    path = completed.final / "merge-receipt.json"
    if damage == "missing_final":
        path.unlink()
    elif damage == "incomplete":
        completed.receipt["complete"] = False
        write_json(path, completed.receipt)
    else:
        (completed.bundle / "shards/dev-0047/shard-receipt.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        review(completed)
    assert completed.calls == []


def test_current_native_recheck_uses_every_receipt_and_does_not_rewrite_originals(
    completed: SimpleNamespace,
) -> None:
    before = {path: file_sha256(path) for path in completed.bundle.rglob("*") if path.is_file()}
    _, final = review(completed)
    assert final == completed.final
    assert len(completed.calls) == 1 and completed.calls[0].count("--receipt") == 48
    assert before == {
        path: file_sha256(path) for path in completed.bundle.rglob("*") if path.is_file()
    }


def test_modified_accounting_file_is_rejected_against_remerged_source(
    completed: SimpleNamespace,
) -> None:
    (completed.final / "accounting-records.jsonl").write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="累计费用与收据链不同"):
        review(completed)


@pytest.mark.parametrize("field", ["usage_complete", "evidence_valid", "stop_reason"])
def test_unknown_or_stopped_finance_cannot_prepare_next_phase(
    completed: SimpleNamespace, field: str
) -> None:
    financial = completed.receipt["summary"]["paid_budget"]
    financial[field] = "paid_usage_incomplete" if field == "stop_reason" else False
    write_json(completed.final / "merge-receipt.json", completed.receipt)
    with pytest.raises(ValueError, match="费用未知或原预算已停止"):
        review(completed)


@pytest.mark.parametrize("field", ["dev_manifest", "dev_records"])
def test_candidate_must_reference_original_master_and_records(
    completed: SimpleNamespace, field: str
) -> None:
    receipt = read_json(completed.candidate)
    receipt[field]["sha256"] = "f" * 64
    write_json(completed.candidate, receipt)
    with pytest.raises(ValueError, match="原完整 SWE 开发来源"):
        module.candidate_configuration(completed.candidate, completed.master, completed.final)


@pytest.mark.parametrize("selected", ["baseline", "focused"])
def test_only_signed_selection_determines_validation_or_holdout(
    completed: SimpleNamespace, selected: str
) -> None:
    receipt = read_json(completed.candidate)
    receipt["selected"] = selected
    write_json(completed.candidate, receipt)
    expected = (
        ("validation", ["baseline"])
        if selected == "baseline"
        else ("holdout", ["baseline", selected])
    )
    assert (
        module.candidate_configuration(completed.candidate, completed.master, completed.final)
        == expected
    )


def test_extra_candidate_is_rejected(completed: SimpleNamespace) -> None:
    receipt = read_json(completed.candidate)
    receipt["selected"] = "retuned-after-holdout"
    write_json(completed.candidate, receipt)
    with pytest.raises(ValueError, match="候选身份不匹配"):
        module.candidate_configuration(completed.candidate, completed.master, completed.final)


@pytest.mark.skipif(
    sys.platform != "linux", reason="真实 inspect_plan 与 CLI 恢复要求原生 POSIX 路径"
)
async def test_linux_full_dev_review_uses_real_inspect_and_cli_with_one_historical_debit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """合成 48 次原生 JSON，真实重归并子进程；不是模型、Docker 或基准成绩。"""
    from resource_samples import runtime_evidence
    from test_historical_settlement import historical
    from test_shards import make_experiment, run

    from sayacode_bench import shards, study
    from scripts.generate_sharded_workflow import TEMPLATE, inspect_plan
    from scripts.prepare_primary_study import RELEASE, _cli

    base = Path("/tmp/sayacode-studies")
    base.mkdir(exist_ok=True)
    bundle = base / ("offline-final-review-" + uuid4().hex)
    assert not bundle.exists() and bundle.parent.resolve() == base.resolve()
    try:
        e = make_experiment(bundle, tmp_path / "private", monkeypatch)
        for index in range(2, 8):
            definition = deepcopy(e.manifest["tasks"][0])
            definition.update(
                task_id=f"instance_{index}",
                repository=f"fixture/repo{index}",
                leakage_group=f"fixture/fix{index}",
            )
            directory = bundle / "cache" / definition["task_id"]
            directory.mkdir()
            (directory / "instruction.md").write_text("Offline task.\n", encoding="utf-8")
            (directory / "task.toml").write_text(
                "[environment]\ncpus=1\nmemory_mb=4096\n", encoding="utf-8"
            )
            e.manifest["tasks"].append(definition)
        e.variants = {"baseline": e.variants["baseline"]}
        for label in ("diagnostic", "focused"):
            e.variants[label] = e.inputs / (label + ".json")
            write_json(e.variants[label], {"id": label})
        settled = historical.__wrapped__(e.inputs)
        e.manifest.update(
            configurations=list(e.variants),
            qualified_runtime_identities={
                task["task_id"]: runtime_evidence() for task in e.manifest["tasks"]
            },
            paid_budget=study.freeze_paid_budget(
                limit_cny=100,
                price_snapshot=e.inputs / "prices.json",
                historical_settlement=settled["path"],
            ),
        )
        e.manifest["artifacts"]["variants"] = {
            label: file_sha256(path) for label, path in e.variants.items()
        }
        (e.inputs / "restart-v2").mkdir()
        e.manifest_path = e.inputs / "restart-v2/primary-dev.json"
        write_json(e.manifest_path, e.manifest)
        write_json(
            e.runner,
            {
                "platform": "linux",
                "architecture": "amd64",
                "job_timeout_seconds": 21600,
                "public_source_sha": SOURCE,
                "executor_workflow_sha256": file_sha256(TEMPLATE),
                "evidence_release": RELEASE,
                "host_cohort": COHORT,
            },
        )
        write_json(
            e.authorization,
            {
                "authorized": True,
                "phase": "dev",
                "master_manifest_sha256": file_sha256(e.manifest_path),
            },
        )
        e.plan_path = bundle / "primary-dev-v2-plan.json"
        e.plan = shards.freeze_execution_plan(
            e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=bundle
        )
        assert len(e.plan["schedule"]) == 48
        previous, receipts = None, []
        for index in range(48):
            receipt, previous = await run(e, index, previous)
            assert receipt["complete"] is True
            receipts.append(previous)
        final = bundle / "merged" / file_sha256(e.manifest_path) / "final"
        original = shards.merge_shards(e.plan_path, receipts, final)
        assert original["complete"] is True
        before = {path: file_sha256(path) for path in bundle.rglob("*") if path.is_file()}
        monkeypatch.setattr(module, "BUNDLE", bundle)
        assert module.inspect_plan is inspect_plan and module._cli is _cli
        output = tmp_path / "actual-cli-review"
        output.mkdir()
        master, restored = module.review_completed(
            "primary-dev", 8, 2, list(e.variants), cohort=COHORT, output=output, source_sha=SOURCE
        )
        reviewed = read_json(output / "primary-dev-review/merge-receipt.json")
        assert restored == final and master == e.manifest
        assert reviewed["summary"] == original["summary"]
        assert reviewed["summary"]["paid_budget"]["historical_settled_cny"] == 0.62
        assert reviewed["summary"]["paid_budget"]["budget_consumed_cny"] == pytest.approx(0.63344)
        for name in ("records.jsonl", "accounting-records.jsonl"):
            assert (final / name).read_bytes() == (
                output / "primary-dev-review" / name
            ).read_bytes()
        assert before == {path: file_sha256(path) for path in bundle.rglob("*") if path.is_file()}
    finally:
        assert bundle.parent.resolve() == base.resolve() and bundle.name.startswith(
            "offline-final-review-"
        )
        shutil.rmtree(bundle, ignore_errors=True)
