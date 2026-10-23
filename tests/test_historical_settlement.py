"""账单核销的离线行为验收；合成账单不代表真实供应商或真实用户授权。"""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import test_locking
import test_shards
import test_study
from test_budget import record
from test_locking import final_manifest, lock, save_records
from test_observed_cache_budget import cached
from test_shards import run as run_shard
from test_study import freeze_arguments, gate_and_probe

from sayacode_bench import budget, cli, shards, study
from sayacode_bench.artifacts import file_sha256, write_json
from sayacode_bench.locking import validate_candidate_receipt
from sayacode_bench.publish import export_results

PRICE = (
    Path(__file__).resolve().parents[1]
    / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json"
)
development = test_locking.experiment
sharded = test_shards.experiment
phased = test_study.experiment


def reference(path: Path, *, base: Path | None = None) -> dict[str, str]:
    return {"path": str(path.relative_to(base) if base else path), "sha256": file_sha256(path)}


@pytest.fixture
def historical(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "historical"
    root.mkdir()
    rows = [
        record(index, job_dir="C:/old/shared-job", record_complete=True) for index in (101, 102)
    ]
    rows[1]["usage_complete"] = False
    rows[1]["usage"].update(reported_calls=9, missing_usage_calls=1)
    sources = []
    for index, row in enumerate(rows):
        path = root / f"source-{index}.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        sources.append({**reference(path, base=root), "request_sha256": row["request_sha256"]})
    bill = {
        "kind": "supplier_ui_read_only_billing_reconciliation",
        "budget_start_utc": "2026-10-22T13:24:34Z",
        "original_calibration_records_modified": False,
        "per_failure_zero_charge_guarantee": False,
        "candidate_conservative_historical_budget_debit_cny": "0.62",
        "calculated_nominal_cny_from_displayed_units_and_rates": "0.60930176",
        "displayed_entire_date_range_nominal_cny": "0.61",
        "sources": [
            {
                "record_sha256": source["sha256"],
                "request_sha256": row["request_sha256"],
                "source_usage": row["usage"],
            }
            for source, row in zip(sources, rows, strict=True)
        ],
    }
    bill_path = root / "billing.json"
    write_json(bill_path, bill)
    auth = {
        "schema_version": 1,
        "kind": "user_authorized_historical_settlement",
        "confirmation": "均同意",
        "budget_start_utc": bill["budget_start_utc"],
        "budget_limit_cny": "100",
        "amount_cny": "0.62",
        "billing_sha256": file_sha256(bill_path),
        "request_sha256s": sorted(row["request_sha256"] for row in rows),
        "original_usage_unknown_preserved": True,
        "future_missing_usage_allowed": False,
        "private_note": "不应公开的授权上下文",
    }
    auth_path = root / "authorization.json"
    write_json(auth_path, auth)
    receipt = {
        "schema_version": 1,
        "kind": "historical_supplier_ui_settlement",
        "currency": "CNY",
        "amount_cny": "0.62",
        "budget_start_utc": bill["budget_start_utc"],
        "budget_limit_cny": "100",
        "billing_evidence": reference(bill_path, base=root),
        "authorization": reference(auth_path, base=root),
        "records": sources,
        "raw_usage_complete": False,
        "future_missing_usage_allowed": False,
        "private_note": "不应公开的收据上下文",
    }
    path = root / "settlement.json"
    write_json(path, receipt)
    return {"path": path, "reference": reference(path), "receipt": receipt, "rows": rows}


def policy(historical: dict[str, Any], **changes: Any) -> dict[str, Any]:
    result = study.freeze_paid_budget(
        **{
            "limit_cny": 100,
            "price_snapshot": PRICE,
            "historical_settlement": historical["path"],
            **changes,
        }
    )
    assert result is not None
    return result


def save_receipt(historical: dict[str, Any]) -> None:
    write_json(historical["path"], historical["receipt"])
    historical["reference"] = reference(historical["path"])


def test_old_path_collision_is_settled_without_rewriting_or_inventing_tokens(
    historical: dict[str, Any],
) -> None:
    original = [
        (historical["path"].parent / source["path"]).read_bytes()
        for source in historical["receipt"]["records"]
    ]
    with pytest.raises(ValueError, match="request_sha256 冲突"):
        budget.estimate_paid_usage(historical["rows"])
    report = study.paid_budget_report({"paid_budget": policy(historical)}, [])
    assert report is not None
    assert report["known_estimate_cny"] == 0
    assert report["historical_settled_cny"] == report["budget_consumed_cny"] == 0.62
    assert report["historical_settlement"]["raw_usage_complete"] is False
    assert report["historical_settlement"]["supplier_signed"] is False
    assert report["usage_complete_scope"] == "token_records_excluding_historical_settlement"
    assert report["stop_reason"] is None and report["limit_cny"] == 100
    assert report["reported_paid_input_tokens"] == report["paid_records"] == 0
    assert historical["rows"][1]["usage"]["missing_usage_calls"] == 1
    assert original == [
        (historical["path"].parent / source["path"]).read_bytes()
        for source in historical["receipt"]["records"]
    ]


def test_same_budget_threshold_counts_historical_debit_exactly_once(
    historical: dict[str, Any],
) -> None:
    settled = historical["reference"]
    before = record(input_tokens=39_689_999, output_tokens=0)
    at = record(input_tokens=39_690_000, output_tokens=0)
    assert budget.budget_reason([before], limit_cny=100, historical_settlement=settled) is None
    assert (
        budget.budget_reason([at], limit_cny=100, historical_settlement=settled)
        == "paid_estimate_stop_fraction_reached"
    )
    report = budget.estimate_paid_usage([at, deepcopy(at)], historical_settlement=settled)
    assert report["known_estimate_cny"] == 79.38
    assert report["budget_consumed_cny"] == 80
    assert report["historical_settled_cny"] == 0.62
    for new_limit in (99.38, 100.62, 200):
        with pytest.raises(ValueError, match="原总预算"):
            budget.budget_reason([], limit_cny=new_limit, historical_settlement=settled)


def test_new_unknown_usage_still_stops_after_historical_settlement(
    historical: dict[str, Any],
) -> None:
    new = record(usage_complete=False)
    assert (
        budget.budget_reason([new], limit_cny=100, historical_settlement=historical["reference"])
        == "paid_usage_incomplete"
    )
    new_policy = policy(historical)
    assert study._paid_stop_reason(new_policy, [new], []) == "paid_usage_incomplete"
    report = study.paid_budget_report({"paid_budget": new_policy}, [new])
    assert report is not None and report["usage_complete"] is False
    assert report["historical_settled_cny"] == 0.62


def test_multiple_phases_inherit_one_debit_and_all_new_token_usage(
    historical: dict[str, Any],
    tmp_path: Path,
) -> None:
    first = record(1)
    first_path = tmp_path / "dev-records.jsonl"
    first_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    holdout = policy(historical, prior_records=[first_path])
    second = record(2)
    second_path = tmp_path / "holdout-records.jsonl"
    second_path.write_text(json.dumps(second) + "\n", encoding="utf-8")
    terminal = policy(historical, prior_records=[first_path, second_path])
    for frozen, rows, expected in (
        (policy(historical), [first], 4.62),
        (holdout, [second], 8.62),
        (terminal, [record(3)], 12.62),
    ):
        report = study.paid_budget_report({"paid_budget": frozen}, rows)
        assert report is not None
        assert report["budget_consumed_cny"] == expected
        assert report["historical_settled_cny"] == 0.62
        assert report["limit_cny"] == 100


@pytest.mark.parametrize("location", ["current", "prior"])
@pytest.mark.parametrize("identity", ["request", "job", "windows_alias"])
def test_settled_source_or_replay_cannot_be_counted_again(
    historical: dict[str, Any],
    location: str,
    identity: str,
) -> None:
    row = record()
    if identity == "request":
        row["request_sha256"] = historical["rows"][0]["request_sha256"]
    else:
        row["source_job"] = "C:/old/shared-job" if identity == "job" else "c:\\OLD\\shared-job"
    current, prior = ([row], []) if location == "current" else ([], [row])
    with pytest.raises(ValueError, match="不能再次进入"):
        budget.budget_reason(
            current, prior, limit_cny=100, historical_settlement=historical["reference"]
        )


def test_freeze_rejects_token_prior_covering_settled_requests(historical: dict[str, Any]) -> None:
    prior = historical["path"].parent / historical["receipt"]["records"][0]["path"]
    with pytest.raises(ValueError, match="不能再次进入"):
        policy(historical, prior_records=[prior])
    with pytest.raises(ValueError, match="paid-limit"):
        policy(historical, limit_cny=None)


@pytest.mark.parametrize(
    "name",
    ["settlement.json", "billing.json", "authorization.json", "source-0.jsonl", "source-1.jsonl"],
)
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_changed_or_missing_original_stops_dispatch_and_invalidates_report(
    historical: dict[str, Any],
    development: dict[str, Any],
    name: str,
    damage: str,
) -> None:
    frozen = policy(historical)
    path = historical["path"].parent / name
    if damage == "missing":
        path.unlink()
    else:
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert study._paid_stop_reason(frozen, [], []) == "paid_budget_evidence_changed"
    report = study.phase_summary(
        {**development["manifest"], "paid_budget": frozen}, development["records"]
    )
    assert report["paid_budget"]["evidence_valid"] is False
    assert report["final_result_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing_source",
        "fake_complete",
        "future_waiver",
        "amount",
        "budget_start",
        "wrong_request",
    ],
)
def test_frozen_receipt_cannot_widen_authorization_or_duplicate_sources(
    historical: dict[str, Any],
    mutation: str,
) -> None:
    receipt = historical["receipt"]
    if mutation == "duplicate":
        receipt["records"].append(deepcopy(receipt["records"][0]))
    elif mutation == "missing_source":
        receipt["records"].pop()
    elif mutation == "fake_complete":
        receipt["raw_usage_complete"] = True
    elif mutation == "future_waiver":
        receipt["future_missing_usage_allowed"] = True
    elif mutation == "amount":
        receipt["amount_cny"] = "0.60"
    elif mutation == "budget_start":
        receipt["budget_start_utc"] = "2026-10-23T13:24:34Z"
    else:
        receipt["records"][0]["request_sha256"] = "f" * 64
    save_receipt(historical)
    with pytest.raises(ValueError):
        policy(historical)


def test_relative_evidence_transfers_without_changing_original_identity(
    historical: dict[str, Any],
    tmp_path: Path,
) -> None:
    moved = tmp_path / "new-host" / "historical"
    shutil.copytree(historical["path"].parent, moved)
    old = budget.estimate_paid_usage([], historical_settlement=historical["reference"])
    new = budget.estimate_paid_usage([], historical_settlement=reference(moved / "settlement.json"))
    assert old == new


def test_cli_freeze_binds_explicit_settlement(phased: Any, historical: dict[str, Any]) -> None:
    gate, probe = gate_and_probe(phased)
    args = freeze_arguments(phased, gate, probe)
    args.paid_limit_cny = 100
    args.paid_price_snapshot = PRICE
    args.historical_settlement = historical["path"]
    frozen = cli.freeze(args)
    assert frozen["paid_budget"]["historical_settlement"] == historical["reference"]


def priced_development(development: dict[str, Any], historical: dict[str, Any]) -> None:
    development["manifest"]["paid_budget"] = policy(historical)
    for index, row in enumerate(development["records"], 1):
        facts = record(index)
        row.update({key: facts[key] for key in ("job_dir", "request_sha256", "usage")})
        row.update(endpoint="remote", input_tokens=100, output_tokens=10)
    write_json(development["manifest_path"], development["manifest"])
    save_records(development)


def test_candidate_and_publication_keep_same_debit_and_no_private_receipt_body(
    development: dict[str, Any],
    historical: dict[str, Any],
    tmp_path: Path,
) -> None:
    priced_development(development, historical)
    assert lock(development)["selected"] == "revised"
    raw = study.phase_summary(development["manifest"], development["records"])
    exported = export_results(
        development["manifest_path"], development["records_path"], tmp_path / "public"
    )
    assert (
        exported["paid_budget"]["budget_consumed_cny"]
        == raw["paid_budget"]["budget_consumed_cny"]
        == pytest.approx(0.62224)
    )
    assert exported["paid_budget"]["historical_settlement"]["raw_usage_complete"] is False
    public_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "public").iterdir()
    )
    for private in (str(tmp_path), "不应公开", "C:/old/shared-job", "source-0.jsonl"):
        assert private not in public_text


@pytest.mark.parametrize("change", ["omit", "other_receipt", "new_budget", "new_fraction"])
def test_final_candidate_cannot_drop_or_replace_settlement(
    development: dict[str, Any],
    historical: dict[str, Any],
    change: str,
) -> None:
    priced_development(development, historical)
    lock(development)
    final = final_manifest(development)
    if change == "omit":
        final["paid_budget"].pop("historical_settlement")
    elif change == "other_receipt":
        final["paid_budget"]["historical_settlement"]["sha256"] = "f" * 64
    else:
        final["paid_budget"]["limit_cny" if change == "new_budget" else "stop_fraction"] = (
            200 if change == "new_budget" else 0.9
        )
    with pytest.raises(ValueError, match="同一历史核销"):
        validate_candidate_receipt(development["receipt_path"], final)


def refreeze_sharded(
    sharded: Any, historical: dict[str, Any], *, prior: list[Path] | None = None
) -> None:
    sharded.manifest["paid_budget"] = policy(historical)
    write_json(sharded.manifest_path, sharded.manifest)
    write_json(
        sharded.authorization,
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(sharded.manifest_path),
        },
    )
    sharded.plan_path = sharded.bundle / "settled-plan.json"
    sharded.plan = shards.freeze_execution_plan(
        sharded.manifest_path,
        sharded.runner,
        sharded.authorization,
        sharded.plan_path,
        bundle_root=sharded.bundle,
        paid_record_paths=prior or [],
    )


async def test_sharded_full_merge_counts_historical_once(
    sharded: Any,
    historical: dict[str, Any],
) -> None:
    refreeze_sharded(sharded, historical)
    previous = None
    for index in range(8):
        receipt, previous = await run_shard(sharded, index, previous)
        assert receipt["complete"] is True
    merged_dir = sharded.bundle / "merged" / "settled"
    merged = shards.merge_shards(sharded.plan_path, [previous], merged_dir)
    assert merged["complete"] is True
    assert merged["summary"]["paid_budget"]["historical_settled_cny"] == 0.62
    assert merged["summary"]["paid_budget"]["budget_consumed_cny"] == pytest.approx(0.62224)
    assert merged["summary"]["paid_budget"]["historical_settlement"]["raw_usage_complete"] is False


def test_shard_initial_paid_records_cannot_reintroduce_settled_request(
    sharded: Any,
    historical: dict[str, Any],
) -> None:
    path = sharded.inputs / "reintroduced.jsonl"
    path.write_text(json.dumps(historical["rows"][0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不能再次进入"):
        refreeze_sharded(sharded, historical, prior=[path])


def test_observed_cache_and_historical_debit_are_independent(
    historical: dict[str, Any],
    tmp_path: Path,
) -> None:
    row = cached(tmp_path)
    arguments = {
        "historical_settlement": historical["reference"],
        "pricing_method": "observed_cache_v1",
    }
    current = budget.estimate_paid_usage([row], **arguments)
    assert current["known_estimate_cny"] == 3.02
    assert current["budget_consumed_cny"] == 3.64
    row["cache_usage"]["status"] = "invalid"
    assert budget.budget_reason([row], limit_cny=100, **arguments) == "paid_usage_incomplete"
