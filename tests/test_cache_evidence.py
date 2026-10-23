"""原生缓存用量旁证的 host 透传与发布回归；不调用模型或 Docker。"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.task.id import LocalTaskId
from harbor.models.trial.config import AgentConfig, TaskConfig, TrialConfig
from harbor.models.trial.result import AgentInfo, TrialResult
from harbor.models.verifier.result import VerifierResult

from sayacode_bench import execution, shards
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.publish import public_record


@pytest.fixture
def evidence(tmp_path: Path) -> dict[str, Any]:
    job = tmp_path / "source-job"
    trial_dir = job / "instance_demo__native"
    logs = trial_dir / "agent/sayacode"
    logs.mkdir(parents=True)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = {}
    for name in ("wheel", "requirements", "variant"):
        paths[name] = inputs / name
        paths[name].write_bytes(name.encode("utf-8"))
    task = tmp_path / "instance_demo"
    task.mkdir()
    now = datetime.now(UTC)
    native = TrialResult(
        task_name="instance_demo",
        trial_name=trial_dir.name,
        trial_uri=trial_dir.as_uri(),
        task_id=LocalTaskId(path=task),
        task_checksum="offline-fixture",
        config=TrialConfig(
            task=TaskConfig(path=task),
            agent=AgentConfig(
                import_path="sayacode_bench.adapter:SayacodeAgent",
                kwargs={
                    "product_wheel": str(paths["wheel"]),
                    "requirements_path": str(paths["requirements"]),
                    "variant_path": str(paths["variant"]),
                },
            ),
        ),
        agent_info=AgentInfo(name="offline-fixture", version="1"),
        agent_result=AgentContext(),
        verifier_result=VerifierResult(rewards={"reward": 1}),
        started_at=now,
        finished_at=now + timedelta(seconds=1),
    )
    write_json(trial_dir / "result.json", native.model_dump(mode="json"))
    calls = []
    audit = []
    for index, thread in enumerate(("parent-thread", "child-thread"), 1):
        usage = {
            "input_tokens": index * 100,
            "output_tokens": index * 10,
            "total_tokens": index * 110,
        }
        run_id = f"native-run-{index}"
        audit += [
            {"event": "model.started", "run_id": run_id, "thread_id": thread},
            {
                "event": "model.completed",
                "run_id": run_id,
                "thread_id": thread,
                "details": {"usage": usage},
            },
        ]
        calls.append(
            {
                "run_id": run_id,
                "thread_id": thread,
                "event": "completed",
                "usage": {
                    **usage,
                    "input_token_details": {"cache_read": index * 60, "cache_creation": index * 10},
                },
            }
        )
    audit_path = logs / "audit.jsonl"
    audit_path.write_text("".join(json.dumps(row) + "\n" for row in audit), encoding="utf-8")
    payload = {
        "schema_version": 1,
        "collector": "langchain_callback_usage_v1",
        "audit_sha256": file_sha256(audit_path),
        "calls": calls,
    }
    write_json(logs / "usage-details.json", payload)
    usage = {
        "model_calls": 2,
        "reported_calls": 2,
        "missing_usage_calls": 0,
        "damaged_audit_lines": 0,
        "input_tokens": 300,
        "output_tokens": 30,
        "total_tokens": 330,
    }
    write_json(logs / "result.json", {"status": "completed", "usage": usage})
    return {
        "trial": native,
        "directory": trial_dir,
        "logs": logs,
        "payload": payload,
        "usage": usage,
        "master": {
            "benchmark": "terminal-bench-2.1",
            "canonical_model": execution.CANONICAL_MODEL,
            "artifacts": {
                "product_wheel": file_sha256(paths["wheel"]),
                "requirements": file_sha256(paths["requirements"]),
                "variants": {"baseline": file_sha256(paths["variant"])},
            },
        },
    }


def normalize(evidence: dict[str, Any]) -> dict[str, Any]:
    result = execution.normalize_trial_result(
        evidence["trial"],
        evidence["directory"],
        configuration="baseline",
        repeat=1,
        endpoint="remote",
    )
    result["job_dir"] = str(evidence["directory"].parent)
    return result


def test_complete_native_parent_and_child_cache_details_do_not_replace_usage(
    evidence: dict[str, Any],
) -> None:
    row = normalize(evidence)
    cache = row["cache_usage"]
    assert cache["status"] == "complete" and cache["coverage_complete"] is True
    assert cache["model_calls"] == cache["matched_calls"] == 2
    assert cache["cache_read_input_tokens"] == 180 and cache["cache_creation_input_tokens"] == 30
    assert row["usage"] == evidence["usage"]
    assert row["input_tokens"] == 300 and row["output_tokens"] == 30
    assert row["success"] is True and row["usage_complete"] is True
    assert row["usage_details"]["sha256"] == file_sha256(evidence["logs"] / "usage-details.json")


@pytest.mark.parametrize("missing_audit", [False, True])
def test_missing_sidecar_is_unavailable_without_invented_zero_cache(
    evidence: dict[str, Any], missing_audit: bool
) -> None:
    (evidence["logs"] / "usage-details.json").unlink()
    if missing_audit:
        (evidence["logs"] / "audit.jsonl").unlink()
    row = normalize(evidence)
    assert row["cache_usage"]["status"] == "unavailable"
    assert row["cache_usage"]["cache_read_input_tokens"] is None
    assert row["usage_details"]["sha256"] is None
    assert row["usage"] == evidence["usage"] and row["success"] is True


@pytest.mark.parametrize(
    "mutation", ["audit_hash", "run_id", "tokens", "empty", "unreadable", "worker_total"]
)
def test_conflicting_native_details_never_discount_or_change_original_score(
    evidence: dict[str, Any], mutation: str
) -> None:
    payload = copy.deepcopy(evidence["payload"])
    path = evidence["logs"] / "usage-details.json"
    if mutation == "audit_hash":
        payload["audit_sha256"] = "f" * 64
    elif mutation == "run_id":
        payload["calls"].append(copy.deepcopy(payload["calls"][0]))
    elif mutation == "tokens":
        payload["calls"][0]["usage"]["total_tokens"] += 1
    elif mutation == "empty":
        payload = {}
    elif mutation == "worker_total":
        worker = read_json(evidence["logs"] / "result.json")
        worker["usage"]["total_tokens"] += 1
        write_json(evidence["logs"] / "result.json", worker)
    if mutation == "unreadable":
        path.write_bytes(b"\xffinvalid")
    else:
        write_json(path, payload)
    row = normalize(evidence)
    assert row["cache_usage"]["status"] == "invalid"
    assert row["cache_usage"]["coverage_complete"] is False
    assert row["input_tokens"] == 300 and row["output_tokens"] == 30
    assert row["success"] is True and row["original_reward"] == 1


def test_shard_revalidates_summary_and_inventories_original_sidecar(
    evidence: dict[str, Any],
) -> None:
    row = normalize(evidence)
    files = shards._record_evidence(row, evidence["master"], None)
    assert row["usage_details"] in files
    forged = copy.deepcopy(row)
    forged["cache_usage"]["cache_read_input_tokens"] += 1
    with pytest.raises(ValueError, match="cache"):
        shards._record_evidence(forged, evidence["master"], None)
    path = evidence["logs"] / "usage-details.json"
    payload = read_json(path)
    payload["calls"][0]["usage"]["input_token_details"]["cache_read"] += 1
    write_json(path, payload)
    with pytest.raises(ValueError):
        shards._record_evidence(row, evidence["master"], None)


def test_old_rows_without_sidecar_remain_equivalent_and_are_not_rewritten(
    evidence: dict[str, Any],
) -> None:
    (evidence["logs"] / "usage-details.json").unlink()
    row = normalize(evidence)
    row.pop("cache_usage")
    row.pop("usage_details")
    saved = evidence["directory"].parent / "old-normalized.json"
    write_json(saved, row)
    previous = saved.read_bytes()
    shards._record_evidence(row, evidence["master"], None)
    assert saved.read_bytes() == previous
    assert "cache_usage" not in row and "usage_details" not in row


def test_public_cache_summary_drops_calls_private_bodies_paths_and_exports_only_hash(
    evidence: dict[str, Any],
) -> None:
    row = normalize(evidence)
    row["cache_usage"].update(
        calls=[{"run_id": "private-run", "api_key": "non-prefixed-secret"}],
        path="C:\\Users\\private\\audit.jsonl",
        response={"text": "private body"},
    )
    result = public_record(row)
    assert result["cache_usage"]["cache_read_input_tokens"] == 180
    assert result["evidence"]["usage_details"] == {"sha256": row["usage_details"]["sha256"]}
    assert "private" not in json.dumps(result)
    assert set(result["cache_usage"]) == {
        "collector",
        "status",
        "reason",
        "audit_sha256",
        "model_calls",
        "matched_calls",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "coverage_complete",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("cache_read_input_tokens", -1),
        ("matched_calls", True),
        ("cache_creation_input_tokens", 1.1),
        ("audit_sha256", "not-sha"),
        ("status", "arbitrary"),
        ("coverage_complete", "true"),
    ],
)
def test_public_summary_rejects_invalid_count_coverage_or_hash(
    evidence: dict[str, Any], key: str, value: Any
) -> None:
    row = normalize(evidence)
    row["cache_usage"][key] = value
    with pytest.raises(ValueError):
        public_record(row)


def test_shard_stop_forwards_frozen_observed_pricing_strategy(monkeypatch: Any) -> None:
    policy = {"limit_cny": 100, "stop_fraction": 0.8}
    monkeypatch.setattr(shards, "check_budget", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(shards.study, "_paid_inputs", lambda _: (policy, []))
    monkeypatch.setattr(
        shards.study,
        "_budget_arguments",
        lambda _: {"pricing_method": "observed_cache_v1", "paid_endpoints": ("remote",)},
    )

    def reason(*_: Any, **kwargs: Any) -> str:
        assert kwargs["pricing_method"] == "observed_cache_v1"
        assert kwargs["paid_endpoints"] == ("remote",)
        return "paid_usage_incomplete"

    monkeypatch.setattr(shards, "budget_reason", reason)
    assert shards._stop_reason({"reported_token_limit": 1000}, [], []) == "paid_usage_incomplete"


@pytest.mark.parametrize(
    "financial_issue", [None, "paid_usage_incomplete", "paid_budget_evidence_invalid"]
)
def test_merge_persists_financial_unknown_for_candidate_lock_but_not_normal_threshold(
    tmp_path: Path, monkeypatch: Any, financial_issue: str | None
) -> None:
    # 隔离财务持久化分支；不将此控制替身称为实际来源或有效基准成绩。
    plan_path, receipt_path = tmp_path / "plan.json", tmp_path / "receipt.json"
    write_json(plan_path, {})
    write_json(receipt_path, {})
    row = {"task_id": "offline", "configuration": "baseline", "repeat": 1, "success": True}
    plan = {"schedule": [row], "master": {"sha256": "a" * 64}}
    master = {"paid_budget": {"pricing_method": "observed_cache_v1"}}
    monkeypatch.setattr(shards, "_load_plan", lambda _: (plan, master, None))
    monkeypatch.setattr(
        shards,
        "_read_receipt",
        lambda *_: (
            {"sequence": 1, "complete": True, "validity_issues": []},
            {"phase_records": [row]},
        ),
    )

    def paid(_: Any) -> tuple[None, list[Any]]:
        if financial_issue == "paid_budget_evidence_invalid":
            raise ValueError("changed frozen price reference")
        return None, []

    monkeypatch.setattr(shards.study, "_paid_inputs", paid)
    monkeypatch.setattr(shards, "_initial_paid", lambda *_: [])
    monkeypatch.setattr(
        shards.study,
        "phase_summary",
        lambda *_args, **_kwargs: {
            "validity_issues": [financial_issue] if financial_issue else [],
            "paid_budget": {
                "stop_reason": "estimated_paid_threshold"
                if financial_issue is None
                else "paid_usage_incomplete"
            },
        },
    )
    output = tmp_path / "merged"
    result = shards.merge_shards(plan_path, [receipt_path], output)
    assert result["complete"] is True
    assert json.loads((output / "records.jsonl").read_text(encoding="utf-8")) == row
    if financial_issue:
        assert (output / "invalid.json").is_file()
        assert financial_issue in read_json(output / "manifest.json")["validity_issues"]
        assert financial_issue in result["validity_issues"]
    else:
        assert not (output / "invalid.json").exists()
        assert result["validity_issues"] == []
