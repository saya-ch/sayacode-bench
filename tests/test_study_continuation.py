"""全局阶段的微分片延续：官方执行器边界使用离线工件，不调用 Docker/API。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from resource_samples import runtime_evidence
from test_study import experiment as experiment
from test_study import install_jobs, install_observed_model_failures, paid_policy

from sayacode_bench import study
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.execution import paired_order
from sayacode_bench.sources import tree_digest
from sayacode_bench.study import PhaseContinuation


def master(
    bundle: Any, *, repeats: int = 2, tasks: int = 1, configurations: int = 2
) -> list[dict[str, Any]]:
    rows = [deepcopy(bundle.manifest["tasks"][0])]
    for index in range(1, tasks):
        directory = bundle.task.parent / f"instance_extra_{index}"
        directory.mkdir()
        for filename in ("task.toml", "instruction.md"):
            (directory / filename).write_bytes((bundle.task / filename).read_bytes())
        rows.append(
            {**rows[0], "task_id": directory.name, "task_tree_sha256": tree_digest(directory)}
        )
    if configurations == 3:
        path = bundle.root / "third.json"
        write_json(path, {"id": "third", "team_enabled": True})
        bundle.variants["third"] = path
    remote = bundle.private / "remote.json"
    remote.write_bytes(bundle.connections["local"].read_bytes())
    bundle.connections["remote"] = remote
    profiles = {
        key: {name: value for name, value in read_json(path).items() if name != "api_key"}
        for key, path in bundle.connections.items()
    }
    bundle.manifest.update(
        phase="dev",
        repeats=repeats,
        tasks=rows,
        configurations=list(bundle.variants),
        connections=["local", "remote"],
        connection_profiles=profiles,
        qualified_runtime_identities={row["task_id"]: runtime_evidence() for row in rows},
        preflight_passed=True,
        implementation=study.implementation_identity(),
        artifacts={
            "product_wheel": file_sha256(bundle.wheel),
            "requirements": file_sha256(bundle.requirements),
            "variants": {key: file_sha256(path) for key, path in bundle.variants.items()},
        },
    )
    write_json(bundle.manifest_path, bundle.manifest)
    return paired_order(bundle.manifest)


def completed(bundle: Any, item: dict[str, Any], **updates: Any) -> dict[str, Any]:
    row = {
        "task_id": item["task_id"],
        "configuration": item["configuration"],
        "repeat": item["repeat"],
        "endpoint": bundle.manifest["connections"][(item["repeat"] - 1) % 2],
        "canonical_model": bundle.manifest["canonical_model"],
        "status": "completed",
        "success": True,
        "verified": True,
        "record_complete": True,
        "original_reward": 1,
        "replay_reward": 1,
        "input_tokens": 100,
        "output_tokens": 10,
        "usage_complete": True,
        "request_sha256": hashlib.sha256(f"history-{item['sequence']}".encode()).hexdigest(),
        "usage": {
            "model_calls": 1,
            "reported_calls": 1,
            "missing_usage_calls": 0,
            "damaged_audit_lines": 0,
        },
        "runtime_identity": runtime_evidence(),
        "replay_runtime_identity": runtime_evidence(),
    }
    row.update(updates)
    return row


async def run(bundle: Any, name: str, continuation: PhaseContinuation | None) -> dict[str, Any]:
    return await study.run_phase(
        bundle.manifest_path,
        bundle.root / name,
        bundle.cache,
        bundle.wheel,
        bundle.requirements,
        bundle.variants,
        bundle.connections,
        bundle.private,
        continuation=continuation,
    )


def records(bundle: Any, name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (bundle.root / name / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]


async def test_one_micro_shard_keeps_full_48_trial_development_denominator(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment, tasks=8, configurations=3)
    result = await run(experiment, "first", PhaseContinuation((1,)))
    assert len(schedule) == 48 and len(calls) == 2
    assert len(records(experiment, "first")) == 1 and len(result["missing_trials"]) == 47
    assert all(group["planned"] == 16 for group in result["groups"].values())
    assert not result["final_result_eligible"]
    assert read_json(experiment.root / "first/progress.json")["planned"] == 48


async def test_prefix_continues_global_job_repeat_endpoint_and_persists_history(
    experiment, monkeypatch
):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    history = tuple(completed(experiment, item) for item in schedule[:2])
    before = deepcopy(history)
    result = await run(experiment, "third", PhaseContinuation((3,), history))
    saved = records(experiment, "third")
    expected = schedule[2]
    assert len(calls) == 2 and len(saved) == 3 and saved[:2] == list(history)
    assert calls[0].job_name == f"dev-0003-{expected['configuration']}-{expected['repeat']}"
    assert saved[-1]["endpoint"] == experiment.manifest["connections"][(expected["repeat"] - 1) % 2]
    assert saved[-1]["repeat"] == expected["repeat"]
    assert history == before and len(result["missing_trials"]) == 1
    assert (await run(experiment, "third", PhaseContinuation((3,), history))) == result
    assert len(calls) == 2


async def test_contiguous_sequences_use_same_existing_execution_loop(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    history = (completed(experiment, schedule[0]),)
    await run(experiment, "middle", PhaseContinuation((2, 3), history))
    assert len(calls) == 4 and len(records(experiment, "middle")) == 3
    assert [config.job_name.split("-")[1] for config in calls[::2]] == ["0002", "0003"]


@pytest.mark.parametrize(
    "sequences", [(), (1,), (3,), (2, 2), (3, 2), (2, 4), (2, 3, 4, 5), (True,)]
)
async def test_selection_cannot_skip_reorder_repeat_or_reset_global_sequence(
    experiment, monkeypatch, sequences
):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    with pytest.raises(ValueError, match="全局序号"):
        await run(
            experiment, "bad", PhaseContinuation(sequences, (completed(experiment, schedule[0]),))
        )
    assert calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        "key",
        "endpoint",
        "sequence",
        "unfinished",
        "usage_flag",
        "missing_tokens",
        "missing_counter",
        "model",
        "resource",
        "fatal",
    ],
)
async def test_invalid_phase_prefix_cannot_start_model(experiment, monkeypatch, mutation):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    row = completed(experiment, schedule[0])
    if mutation == "key":
        row["configuration"] = "not-in-master"
    elif mutation == "endpoint":
        row["endpoint"] = "unexpected"
    elif mutation == "sequence":
        row["sequence"] = 3
    elif mutation == "unfinished":
        row["record_complete"] = False
    elif mutation == "usage_flag":
        row["usage_complete"] = False
    elif mutation == "missing_tokens":
        row["input_tokens"] = None
    elif mutation == "missing_counter":
        row["usage"].pop("reported_calls")
    elif mutation == "model":
        row["canonical_model"] = "other"
    elif mutation == "resource":
        row["runtime_identity"].pop("cgroup_v2")
    else:
        row.update(status="failed", success=False, terminal_http_statuses=[401])
    with pytest.raises(ValueError):
        await run(experiment, "invalid", PhaseContinuation((2,), (row,)))
    assert calls == []


async def test_out_of_order_phase_history_is_rejected(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    history = tuple(completed(experiment, item) for item in reversed(schedule[:2]))
    with pytest.raises(ValueError, match="严格前缀"):
        await run(experiment, "reordered", PhaseContinuation((3,), history))
    assert calls == []


async def test_existing_local_history_conflict_is_not_overwritten(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    row = completed(experiment, schedule[0])
    output = experiment.root / "conflict"
    output.mkdir()
    local = {**row, "input_tokens": 200}
    saved = json.dumps(local) + "\n"
    (output / "records.jsonl").write_text(saved, encoding="utf-8")
    with pytest.raises(ValueError, match="冲突"):
        await run(experiment, "conflict", PhaseContinuation((2,), (row,)))
    assert calls == [] and (output / "records.jsonl").read_text(encoding="utf-8") == saved


async def test_existing_piece_cannot_expand_its_frozen_selection(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    history = (completed(experiment, schedule[0]),)
    await run(experiment, "piece", PhaseContinuation((2,), history))
    with pytest.raises(ValueError, match="输入身份"):
        await run(experiment, "piece", PhaseContinuation((2, 3), history))
    assert len(calls) == 2


async def test_stage_tokens_are_not_reset_and_last_piece_usage_remains_recorded(
    experiment, monkeypatch
):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    experiment.manifest["reported_token_limit"] = 150
    write_json(experiment.manifest_path, experiment.manifest)
    history = (completed(experiment, schedule[0]),)
    await run(experiment, "over-limit", PhaseContinuation((2,), history))
    prefix = records(experiment, "over-limit")
    assert (
        len(prefix) == 2
        and sum(row["input_tokens"] + row["output_tokens"] for row in prefix) == 220
    )
    await run(experiment, "stopped", PhaseContinuation((3,), tuple(prefix)))
    assert len(calls) == 2 and records(experiment, "stopped") == prefix
    assert read_json(experiment.root / "stopped/abort.json")["reason"] == "reported_token_threshold"


async def test_failure_window_spans_pieces_and_cannot_be_restarted(experiment, monkeypatch):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    prior = completed(
        experiment, schedule[0], status="failed", success=False, failure_category="model_connection"
    )
    install_observed_model_failures(monkeypatch, {1})
    await run(experiment, "second-failure", PhaseContinuation((2,), (prior,)))
    prefix = records(experiment, "second-failure")
    assert (
        read_json(experiment.root / "second-failure/abort.json")["reason"]
        == "unstable_model_connection"
    )
    with pytest.raises(ValueError, match="故障止损"):
        await run(experiment, "cannot-reset", PhaseContinuation((3,), tuple(prefix)))
    assert len(calls) == 2


async def test_extra_paid_ledger_appends_to_master_prior_without_replacing_it(
    experiment, monkeypatch
):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    phase = completed(
        experiment, schedule[0], endpoint="remote", input_tokens=100000, output_tokens=0
    )
    # 固定repeat路由仍须一致，统一使用remote以隔离本例的费用累计变量。
    experiment.manifest["connections"] = ["remote"]
    prior_path = experiment.root / "frozen-prior.jsonl"
    prior = {**phase, "request_sha256": "1" * 64, "task_id": "previous-calibration"}
    prior_path.write_text(json.dumps(prior) + "\n", encoding="utf-8")
    extra = {**prior, "request_sha256": "2" * 64, "task_id": "another-stage"}
    experiment.manifest["paid_budget"] = paid_policy(experiment, limit_cny=0.7, prior=[prior_path])
    write_json(experiment.manifest_path, experiment.manifest)
    before = experiment.manifest_path.read_bytes()
    result = await run(experiment, "financial-stop", PhaseContinuation((2,), (phase,), (extra,)))
    assert calls == []
    assert result["paid_budget"]["known_estimate_cny"] == pytest.approx(0.6)
    assert (
        read_json(experiment.root / "financial-stop/abort.json")["reason"]
        == "paid_estimate_stop_fraction_reached"
    )
    assert experiment.manifest_path.read_bytes() == before
    assert records(experiment, "financial-stop") == [phase]


@pytest.mark.parametrize("field,value", [("record_complete", False), ("usage_complete", False)])
async def test_unconfirmed_additional_paid_records_cannot_dispatch(
    experiment, monkeypatch, field, value
):
    calls = install_jobs(monkeypatch)
    schedule = master(experiment)
    extra = completed(experiment, schedule[0], **{field: value})
    with pytest.raises(ValueError):
        await run(experiment, "unknown-paid", PhaseContinuation((1,), (), (extra,)))
    assert calls == []


def test_continuation_fields_are_frozen():
    continuation = PhaseContinuation((1,))
    with pytest.raises(FrozenInstanceError):
        continuation.sequences = (2,)
