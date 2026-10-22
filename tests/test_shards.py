"""纯离线行为回归；合成原生工件不代表真实 Agent 或公开基准成绩。"""

from __future__ import annotations

import asyncio
import copy
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.task.id import LocalTaskId
from harbor.models.trial.config import AgentConfig, TaskConfig, TrialConfig
from harbor.models.trial.result import AgentInfo, TrialResult
from harbor.models.verifier.result import VerifierResult
from resource_samples import runtime_evidence

from sayacode_bench import shards, study
from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.execution import normalize_trial_result, paired_order
from sayacode_bench.locking import lock_candidate

ROOT = Path(__file__).resolve().parents[1]


def native(path: Path, task: Path, agent: AgentConfig, reward: int) -> TrialResult:
    now = datetime.now(UTC)
    trial = TrialResult(
        task_name=task.name,
        trial_name=path.name,
        trial_uri=path.as_uri(),
        task_id=LocalTaskId(path=task),
        task_checksum="offline-behavior-fixture",
        config=TrialConfig(task=TaskConfig(path=task), agent=agent),
        agent_info=AgentInfo(name="offline-fixture", version="1"),
        agent_result=AgentContext(),
        verifier_result=VerifierResult(rewards={"reward": reward}),
        started_at=now,
        finished_at=now + timedelta(seconds=2),
    )
    write_json(path / "result.json", trial.model_dump(mode="json"))
    write_json(path / "runtime.json", runtime_evidence())
    return trial


@pytest.fixture
def experiment(tmp_path: Path, monkeypatch: Any) -> Any:
    bundle = tmp_path / "study"
    inputs = bundle / "inputs"
    inputs.mkdir(parents=True)
    wheel, requirements = inputs / "product.whl", inputs / "requirements.txt"
    wheel.write_bytes(b"frozen-product")
    requirements.write_bytes(b"frozen-requirements")
    variants = {}
    for label in ("baseline", "candidate"):
        path = inputs / f"{label}.json"
        write_json(path, {"id": label})
        variants[label] = path
    private = tmp_path / "private"
    private.mkdir()
    profile = private / "remote.json"
    public_profile = {
        "protocol": "anthropic_messages",
        "base_url": "https://model.invalid",
        "model_id": "DeepSeek-V4.1-Flash",
        "context_length": 65536,
        "max_output_tokens": 8192,
    }
    write_json(profile, {**public_profile, "api_key": "offline-not-a-real-key"})
    tasks = []
    for index in range(2):
        task = bundle / "cache" / f"instance_{index}"
        task.mkdir(parents=True)
        (task / "instruction.md").write_text("Offline task.\n", encoding="utf-8")
        (task / "task.toml").write_text("[environment]\ncpus=1\nmemory_mb=4096\n", encoding="utf-8")
        tasks.append(
            {
                "task_id": task.name,
                "repository": f"fixture/repo{index}",
                "leakage_group": f"fixture/fix{index}",
                "environment": {"cpus": 1, "memory_mb": 4096, "build_timeout_sec": 1800},
                "agent": {"timeout_sec": 3000},
                "verifier": {"timeout_sec": 3000},
            }
        )
    price = inputs / "prices.json"
    price.write_bytes(
        (ROOT / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json").read_bytes()
    )
    master = {
        "phase": "dev",
        "frozen": True,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "benchmark": "swe-bench-pro-v2",
        "seed": "fixed-shard-behavior",
        "tasks": tasks,
        "configurations": list(variants),
        "baseline": "baseline",
        "candidate": None,
        "repeats": 2,
        "connections": ["remote"],
        "connection_profiles": {"remote": public_profile},
        "reported_token_limit": 100000,
        "preflight_passed": True,
        "runtime_evidence_required": True,
        "qualified_runtime_identities": {task["task_id"]: runtime_evidence() for task in tasks},
        "implementation": implementation_identity(),
        "artifacts": {
            "product_wheel": file_sha256(wheel),
            "requirements": file_sha256(requirements),
            "variants": {label: file_sha256(path) for label, path in variants.items()},
        },
        "paid_budget": study.freeze_paid_budget(
            limit_cny=100, price_snapshot=price, paid_endpoints=["remote"]
        ),
    }
    manifest_path = inputs / "master.json"
    write_json(manifest_path, master)
    runner, authorization = inputs / "runner.json", inputs / "authorization.json"
    write_json(
        runner, {"platform": "linux", "architecture": "amd64", "executor": "frozen-offline-test"}
    )
    write_json(
        authorization,
        {"authorized": True, "phase": "dev", "master_manifest_sha256": file_sha256(manifest_path)},
    )
    plan_path = bundle / "plan.json"
    plan = shards.freeze_execution_plan(
        manifest_path, runner, authorization, plan_path, bundle_root=bundle
    )
    monkeypatch.setattr(shards.platform, "system", lambda: "Linux")
    monkeypatch.setattr(shards.platform, "machine", lambda: "x86_64")
    calls = []
    fail_after_source = []
    pause_after_source = []

    async def execute(
        manifest_path: Path,
        output: Path,
        cache: Path,
        product: Path,
        req: Path,
        variant_paths: dict[str, Path],
        connections: Any,
        private_home: Path,
        *,
        continuation: Any,
    ) -> dict[str, Any]:
        calls.append(continuation)
        config = read_json(manifest_path)
        entry = paired_order(config)[continuation.sequences[0] - 1]
        task = cache / entry["task_id"]
        source_job = output / "jobs" / f"source-{entry['sequence']}"
        source_dir = source_job / f"{task.name}__source"
        source = native(
            source_dir,
            task,
            AgentConfig(
                import_path="sayacode_bench.adapter:SayacodeAgent",
                model_name="DeepSeek-V4.1-Flash",
                kwargs={
                    "product_wheel": str(product),
                    "requirements_path": str(req),
                    "variant_path": str(variant_paths[entry["configuration"]]),
                },
            ),
            0,
        )
        write_json(
            source_dir / "agent/sayacode/result.json",
            {
                "status": "completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "model_calls": 1,
                    "reported_calls": 1,
                    "missing_usage_calls": 0,
                    "damaged_audit_lines": 0,
                },
            },
        )
        row = normalize_trial_result(
            source,
            source_dir,
            configuration=entry["configuration"],
            repeat=entry["repeat"],
            endpoint="remote",
            require_replay=True,
        )
        row.update(
            job_dir=str(source_job),
            source_job=str(source_job),
            request_sha256=f"{entry['sequence']:064x}",
        )
        rows = [*copy.deepcopy(continuation.phase_records), row]
        if pause_after_source:
            row["record_complete"] = False
            shards._write_rows(output / "records.jsonl", rows)
            try:
                await asyncio.Event().wait()
            finally:
                write_json(output / "finalized.json", {"cancelled_and_saved": True})
        if fail_after_source:
            row["record_complete"] = False
            shards._write_rows(output / "records.jsonl", rows)
            raise RuntimeError("offline source saved; verifier not started")
        patch = source_dir / "agent/model.patch"
        patch.write_bytes(b"")
        replay_job = output / "replays" / f"replay-{entry['sequence']}"
        replay_dir = replay_job / f"{task.name}__replay"
        score = int(entry["configuration"] == "candidate")
        replay_native = native(
            replay_dir,
            task,
            AgentConfig(
                import_path="patch_replay:PatchReplayAgent",
                model_name="replay",
                kwargs={"source_job": str(source_job)},
            ),
            score,
        )
        replay = normalize_trial_result(
            replay_native,
            replay_dir,
            configuration=entry["configuration"],
            repeat=entry["repeat"],
            endpoint="remote",
        )
        write_json(replay_dir / "agent/replay.json", {"patch": None, "apply_rc": None})
        row.update(
            verified=True,
            success=bool(score),
            patch=shards._ref(patch),
            replay_reward=score,
            replay_status="completed_no_changes",
            replay_job_dir=str(replay_job),
            replay_raw_trial_result=replay["raw_trial_result"],
            replay_runtime=replay["runtime"],
            replay_runtime_identity=replay["runtime_identity"],
            runtime_comparison={"same_image": True, "same_platform": True, "same_resources": True},
        )
        shards._write_rows(output / "records.jsonl", rows)
        return {"missing_trials": ["expected while partial"]}

    monkeypatch.setattr(study, "run_phase", execute)
    return SimpleNamespace(
        bundle=bundle,
        inputs=inputs,
        wheel=wheel,
        requirements=requirements,
        variants=variants,
        private=private,
        profile=profile,
        manifest=master,
        manifest_path=manifest_path,
        runner=runner,
        authorization=authorization,
        plan=plan,
        plan_path=plan_path,
        calls=calls,
        fail_after_source=fail_after_source,
        pause_after_source=pause_after_source,
    )


async def run(
    e: Any, index: int, previous: Path | None, **kwargs: Any
) -> tuple[dict[str, Any], Path]:
    entry = e.plan["schedule"][index]
    output = e.bundle / "shards" / entry["shard_id"]
    receipt = await shards.run_shard(
        e.plan_path,
        entry["shard_id"],
        previous,
        output=output,
        cache=e.bundle / "cache",
        wheel=e.wheel,
        requirements=e.requirements,
        variants=e.variants,
        connections={"remote": e.profile},
        private_home=e.private,
        **kwargs,
    )
    return receipt, output / "shard-receipt.json"


def test_frozen_plan_preserves_all_keys_order_and_repeats(experiment: Any) -> None:
    e = experiment
    original = paired_order(e.manifest)
    assert len(e.plan["schedule"]) == 8
    assert [{key: row[key] for key in original[0]} for row in e.plan["schedule"]] == original
    assert len({row["trial_key"] for row in e.plan["schedule"]}) == 8
    assert len({row["block_id"] for row in e.plan["schedule"]}) == 4
    with pytest.raises(FileExistsError):
        shards.freeze_execution_plan(
            e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
        )


async def test_full_run_uses_prefix_once_and_merge_keeps_full_master_denominator(
    experiment: Any,
) -> None:
    e = experiment
    previous, receipts = None, []
    for index in range(8):
        receipt, previous = await run(e, index, previous)
        assert receipt["status"] == "completed" and receipt["complete"] is True
        assert receipt["continuation_allowed"] is True
        receipts.append(previous)
        assert e.calls[-1].sequences == (index + 1,)
        assert len(e.calls[-1].phase_records) == index
    merged = shards.merge_shards(e.plan_path, [*receipts, receipts[0]], e.bundle / "merged/dev")
    assert merged["complete"] is True and merged["accepted_receipts"] == 8
    assert merged["missing_trials"] == 0
    assert merged["summary"]["groups"]["baseline"]["task_macro_success_rate"] == 0
    assert merged["summary"]["groups"]["candidate"]["task_macro_success_rate"] == 1
    assert len(shards._rows(e.bundle / "merged/dev/records.jsonl")) == 8
    assert "offline-not-a-real-key" not in (e.bundle / "merged/dev/merge-receipt.json").read_text(
        encoding="utf-8"
    )


async def test_completed_failure_is_idempotent_and_not_rerun(experiment: Any) -> None:
    e = experiment
    first, path = await run(e, 0, None)
    again, _ = await run(e, 0, None)
    assert again == first and len(e.calls) == 1
    assert read_json(path)["complete"] is True


async def test_missing_pair_stays_missing_and_cannot_be_promoted(experiment: Any) -> None:
    e = experiment
    _, receipt = await run(e, 0, None)
    merged = shards.merge_shards(e.plan_path, [receipt], e.bundle / "merged/partial")
    assert merged["complete"] is False and merged["missing_trials"] == 7
    assert merged["summary"]["formal_comparison_eligible"] is False


async def test_source_saved_then_exception_keeps_usage_and_never_replays_source(
    experiment: Any,
) -> None:
    e = experiment
    e.fail_after_source.append(True)
    receipt, path = await run(e, 0, None)
    assert receipt["status"] == "incomplete" and receipt["continuation_allowed"] is False
    ledger = read_json(Path(receipt["ledger_after"]["path"]))
    assert ledger["phase_records"][0]["input_tokens"] == 100
    assert ledger["unresolved_execution"] is True
    assert (await run(e, 0, None))[0] == receipt
    assert len(e.calls) == 1
    with pytest.raises(ValueError, match="前序"):
        await run(e, 1, path)


async def test_sequence_holes_and_source_drift_are_rejected_before_execution(
    experiment: Any,
) -> None:
    e = experiment
    with pytest.raises(ValueError, match="前序"):
        await run(e, 1, None)
    assert not e.calls
    e.wheel.write_bytes(b"different")
    with pytest.raises(ValueError, match="工件"):
        await run(e, 0, None)
    assert not e.calls


@pytest.mark.parametrize("target", ["runner", "authorization", "implementation"])
async def test_frozen_policy_or_implementation_drift_is_rejected(
    experiment: Any, monkeypatch: Any, target: str
) -> None:
    e = experiment
    if target == "implementation":
        monkeypatch.setattr(shards, "implementation_identity", lambda: {"changed": "a" * 64})
    else:
        path = getattr(e, target)
        path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        await run(e, 0, None)
    assert not e.calls


async def test_tampered_native_artifact_rejected_on_restore(experiment: Any) -> None:
    e = experiment
    receipt, path = await run(e, 0, None)
    state = read_json(Path(receipt["ledger_after"]["path"]))
    worker = Path(state["phase_records"][0]["worker_result"]["path"])
    worker.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        shards.merge_shards(e.plan_path, [path], e.bundle / "merged/tampered")


async def test_phase_token_threshold_is_not_reset_each_shard(experiment: Any) -> None:
    e = experiment
    master = read_json(e.manifest_path)
    master["reported_token_limit"] = 150
    write_json(e.manifest_path, master)
    write_json(
        e.authorization,
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(e.manifest_path),
        },
    )
    e.plan_path.unlink()
    e.plan = shards.freeze_execution_plan(
        e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
    )
    first, path = await run(e, 0, None)
    assert first["continuation_allowed"] is True
    second, next_path = await run(e, 1, path)
    assert second["complete"] is True and second["continuation_allowed"] is False
    assert second["stop_reason"] == "reported_token_threshold"
    with pytest.raises(ValueError, match="前序"):
        await run(e, 2, next_path)
    assert len(e.calls) == 2


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True])
async def test_nonfinite_or_boolean_deadline_rejected_before_dispatch(
    experiment: Any, deadline: Any
) -> None:
    with pytest.raises(ValueError, match="有限"):
        await run(experiment, 0, None, deadline_epoch=deadline)
    assert not experiment.calls


async def test_insufficient_deadline_saves_stopped_receipt_without_source(experiment: Any) -> None:
    e = experiment
    receipt, _ = await run(e, 0, None, deadline_epoch=time.time() + 100)
    assert e.plan["schedule"][0]["reserve_seconds"] == 17700
    assert receipt["status"] == "stopped" and receipt["complete"] is False
    assert receipt["stop_reason"] == "insufficient_job_time" and not e.calls


async def test_timeout_runs_finally_keeps_source_usage_and_blocks_replay(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment
    e.pause_after_source.append(True)
    original_wait = asyncio.wait_for

    async def shortened(awaitable: Any, *, timeout: float) -> Any:
        assert timeout > 900
        return await original_wait(awaitable, timeout=0.01)

    monkeypatch.setattr(shards.asyncio, "wait_for", shortened)
    receipt, path = await run(e, 0, None, deadline_epoch=time.time() + 20000)
    assert receipt["status"] == "incomplete" and receipt["error_type"] == "TimeoutError"
    assert read_json(path.parent / "run/finalized.json")["cancelled_and_saved"] is True
    assert (
        read_json(Path(receipt["ledger_after"]["path"]))["phase_records"][0]["input_tokens"] == 100
    )
    assert (await run(e, 0, None, deadline_epoch=time.time() + 20000))[0] == receipt
    assert len(e.calls) == 1


async def test_rehashed_partial_ledger_cannot_zero_native_source_usage(experiment: Any) -> None:
    e = experiment
    e.fail_after_source.append(True)
    receipt, path = await run(e, 0, None)
    ledger = Path(receipt["ledger_after"]["path"])
    rows = read_json(ledger)
    rows["phase_records"][0]["input_tokens"] = 0
    write_json(ledger, rows)
    receipt["ledger_after"] = shards._ref(ledger)
    write_json(path, receipt)
    with pytest.raises(ValueError, match="input_tokens"):
        shards.merge_shards(e.plan_path, [path], e.bundle / "merged/false-zero")


async def test_complete_row_then_exception_remains_invalid_for_candidate_lock(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment
    normal = study.run_phase

    async def after_saved(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await normal(*args, **kwargs)
        if kwargs["continuation"].sequences == (8,):
            raise RuntimeError("offline failure after complete row")
        return result

    monkeypatch.setattr(study, "run_phase", after_saved)
    previous = None
    for index in range(8):
        _, previous = await run(e, index, previous)
    output = e.bundle / "merged/aborted"
    merged = shards.merge_shards(e.plan_path, [previous], output)
    assert merged["complete"] is False
    assert len(shards._rows(output / "records.jsonl")) == 8
    assert (output / "invalid.json").is_file()
    with pytest.raises(ValueError, match="已中止或失效"):
        lock_candidate(
            e.manifest_path, output / "records.jsonl", e.variants, output / "candidate.json"
        )


async def test_receipt_flag_cannot_override_cumulative_stop(experiment: Any) -> None:
    e = experiment
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
    e.plan_path = e.bundle / "small-budget-plan.json"
    e.plan = shards.freeze_execution_plan(
        e.manifest_path, e.runner, e.authorization, e.plan_path, bundle_root=e.bundle
    )
    receipt, path = await run(e, 0, None)
    assert receipt["complete"] is True and receipt["continuation_allowed"] is False
    receipt.update(continuation_allowed=True, stop_reason=None)
    write_json(path, receipt)
    with pytest.raises(ValueError, match="放行旗标"):
        await run(e, 1, path)
    assert len(e.calls) == 1


async def test_conflicting_receipt_and_reused_source_identity_rejected(experiment: Any) -> None:
    e = experiment
    first, first_path = await run(e, 0, None)
    copy_path = first_path.parent / "conflict.json"
    write_json(copy_path, {**first, "extra_conflicting_fact": True})
    with pytest.raises(ValueError, match="冲突"):
        shards.merge_shards(e.plan_path, [first_path, copy_path], e.bundle / "merged/conflict")
    second, second_path = await run(e, 1, first_path)
    ledger_path = Path(second["ledger_after"]["path"])
    ledger = read_json(ledger_path)
    ledger["phase_records"][1]["request_sha256"] = ledger["phase_records"][0]["request_sha256"]
    write_json(ledger_path, ledger)
    second["ledger_after"] = shards._ref(ledger_path)
    write_json(second_path, second)
    with pytest.raises(ValueError, match="执行身份"):
        shards.merge_shards(e.plan_path, [second_path], e.bundle / "merged/reused")


async def test_cross_phase_paid_increment_is_frozen_and_not_double_counted(experiment: Any) -> None:
    e = experiment
    paid = e.inputs / "previous-phase.jsonl"
    prior = {
        "record_complete": True,
        "endpoint": "remote",
        "source_job": "historical-paid-job",
        "request_sha256": "e" * 64,
        "usage_complete": True,
        "input_tokens": 20_000_000,
        "output_tokens": 0,
        "usage": {
            "model_calls": 1,
            "reported_calls": 1,
            "missing_usage_calls": 0,
            "damaged_audit_lines": 0,
        },
    }
    shards._write_rows(paid, [prior])
    e.plan_path = e.bundle / "paid-plan.json"
    e.plan = shards.freeze_execution_plan(
        e.manifest_path,
        e.runner,
        e.authorization,
        e.plan_path,
        bundle_root=e.bundle,
        paid_record_paths=[paid],
    )
    _, first_path = await run(e, 0, None)
    _, second_path = await run(e, 1, first_path)
    assert e.calls[0].paid_records == e.calls[1].paid_records == (prior,)
    merged = shards.merge_shards(e.plan_path, [second_path], e.bundle / "merged/paid")
    assert merged["summary"]["paid_budget"]["known_estimate_cny"] == pytest.approx(40.00056)
    paid.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        await run(e, 2, second_path)
