"""只对新冻结策略使用已观测缓存；合成旁证不代表真实供应商账单。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from test_budget import record
from test_locking import experiment as experiment
from test_locking import final_manifest, lock, save_records

from sayacode_bench import budget, study
from sayacode_bench.analysis import select_development_candidate
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.locking import validate_candidate_receipt

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json"
PROFILES = {
    "remote": {
        "protocol": "anthropic_messages",
        "base_url": "https://api.siliconflow.cn",
        "model_id": "deepseek-ai/DeepSeek-V4.1-Flash",
    }
}


def cached(tmp_path: Path, index: int = 1, **changes: Any) -> dict[str, Any]:
    sidecar = tmp_path / str(index) / "usage-details.json"
    audit = sidecar.with_name("audit.jsonl")
    write_json(sidecar, {"offline_synthetic_evidence": True, "index": index})
    audit.write_text("offline callback audit\n", encoding="utf-8")
    row = record(index)
    row["cache_usage"] = {
        "collector": "langchain_callback_usage_v1",
        "status": "complete",
        "reason": None,
        "audit_sha256": file_sha256(audit),
        "model_calls": 10,
        "matched_calls": 10,
        "input_tokens": 1_000_000,
        "output_tokens": 250_000,
        "total_tokens": 1_250_000,
        "cache_read_input_tokens": 500_000,
        "cache_creation_input_tokens": 0,
        "coverage_complete": True,
        **changes,
    }
    row["usage_details"] = {"path": str(sidecar), "sha256": file_sha256(sidecar)}
    return row


def estimate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return budget.estimate_paid_usage(rows, pricing_method="observed_cache_v1")


def snapshot(tmp_path: Path) -> Path:
    value = read_json(OLD)
    value.update(
        pricing_method="observed_cache_v1",
        cache_semantics="input_includes_cache_read_and_creation_v1",
        cache_evidence_collector="langchain_callback_usage_v1",
        pricing_implementation_sha256=file_sha256(Path(budget.__file__)),
        connection_requirements=deepcopy(PROFILES["remote"]),
    )
    value["conservative_estimation"]["cache_read_cny_per_million"] = 0.04
    path = tmp_path / "observed-prices.json"
    write_json(path, value)
    return path


def test_only_new_method_uses_actual_read_counts_without_forecast(tmp_path: Path) -> None:
    row = cached(tmp_path)
    assert budget.estimate_paid_usage([row])["known_estimate_cny"] == 4
    observed = estimate([row])
    assert observed["known_estimate_cny"] == pytest.approx(3.02)
    assert observed["cache_discount_applied"] is observed["usage_complete"] is True
    assert observed["reported_paid_cache_read_tokens"] == 500_000
    assert estimate([record()])["known_estimate_cny"] == 4


@pytest.mark.parametrize("change", ["missing", "coverage", "reference", "sidecar", "audit"])
def test_unavailable_evidence_uses_full_input_price(tmp_path: Path, change: str) -> None:
    row = cached(tmp_path)
    if change == "missing":
        row.pop("cache_usage")
    elif change == "coverage":
        row["cache_usage"]["coverage_complete"] = False
    elif change == "reference":
        row.pop("usage_details")
    elif change == "sidecar":
        Path(row["usage_details"]["path"]).unlink()
    else:
        Path(row["usage_details"]["path"]).with_name("audit.jsonl").unlink()
    result = estimate([row])
    assert result["known_estimate_cny"] == 4 and result["usage_complete"] is True
    assert result["cache_discount_applied"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "invalid"},
        {"input_tokens": 1},
        {"output_tokens": 1},
        {"total_tokens": 1},
        {"model_calls": 9},
        {"matched_calls": 9},
        {"cache_read_input_tokens": 1_000_001},
        {"cache_read_input_tokens": -1},
        {"cache_creation_input_tokens": True},
        {"cache_creation_input_tokens": 10},
        {
            "status": "unavailable",
            "coverage_complete": False,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": 10,
        },
    ],
)
def test_conflicts_or_observed_generic_or_ttl_creation_without_rate_stop(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    row = cached(tmp_path, **changes)
    result = estimate([row])
    assert result["usage_complete"] is False and result["cache_discount_applied"] is False
    assert (
        budget.budget_reason([row], limit_cny=100, pricing_method="observed_cache_v1")
        == "paid_usage_incomplete"
    )


@pytest.mark.parametrize("target", ["usage-details.json", "audit.jsonl"])
def test_changed_hashed_native_evidence_is_invalid_not_a_discount(
    tmp_path: Path, target: str
) -> None:
    row = cached(tmp_path)
    Path(row["usage_details"]["path"]).with_name(target).write_text("changed", encoding="utf-8")
    assert estimate([row])["usage_complete"] is False


def test_base_usage_unknown_stays_unknown_and_does_not_receive_credit(tmp_path: Path) -> None:
    row = cached(tmp_path)
    row["usage_complete"] = False
    result = estimate([row])
    assert result["usage_complete"] is False and result["cache_discount_applied"] is False


def test_deduplication_binds_cache_evidence_and_never_picks_cheaper_version(tmp_path: Path) -> None:
    row = cached(tmp_path)
    replay = {**deepcopy(row), "source_job": row["job_dir"], "replay_reward": 1}
    assert estimate([row, replay])["known_estimate_cny"] == pytest.approx(3.02)
    for field in ("cache_usage", "usage_details"):
        changed = deepcopy(row)
        changed[field] = None
        with pytest.raises(ValueError, match="冲突"):
            estimate([row, changed])


def test_old_calibration_full_price_and_new_observed_cost_share_one_budget(tmp_path: Path) -> None:
    row = cached(tmp_path, 2)
    prior = record(1)
    result = budget.estimate_paid_usage([prior, row], pricing_method="observed_cache_v1")
    assert result["known_estimate_cny"] == pytest.approx(7.02)
    assert (
        budget.budget_reason([row], [prior], limit_cny=8, pricing_method="observed_cache_v1")
        == "paid_estimate_stop_fraction_reached"
    )


def test_freeze_new_policy_binds_peak_rates_actual_profiles_and_implementation(
    tmp_path: Path,
) -> None:
    old_hash = file_sha256(OLD)
    path = snapshot(tmp_path)
    policy = study.freeze_paid_budget(
        limit_cny=100, price_snapshot=path, connection_profiles=PROFILES
    )
    assert policy["pricing_method"] == "observed_cache_v1"
    assert (
        policy["input_cny_per_million"],
        policy["cache_read_cny_per_million"],
        policy["output_cny_per_million"],
    ) == (2, 0.04, 8)
    assert policy["stop_fraction"] == 0.8 and policy["limit_cny"] == 100
    assert policy["connection_bindings"] == PROFILES
    assert policy["pricing_implementation_sha256"] == file_sha256(Path(budget.__file__))
    row = cached(tmp_path)
    manifest = {"paid_budget": policy, "connection_profiles": PROFILES}
    assert study.paid_budget_report(manifest, [row])["known_estimate_cny"] == pytest.approx(3.02)
    assert file_sha256(OLD) == old_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_url", "http://127.0.0.1:8787"),
        ("model_id", "DeepSeek-V4.1-Flash"),
        ("protocol", "openai_chat_completions"),
    ],
)
def test_same_alias_and_canonical_model_do_not_license_other_connection_prices(
    tmp_path: Path, field: str, value: str
) -> None:
    profiles = deepcopy(PROFILES)
    profiles["remote"][field] = value
    path = snapshot(tmp_path)
    with pytest.raises(ValueError, match="实际连接"):
        study.freeze_paid_budget(limit_cny=100, price_snapshot=path, connection_profiles=profiles)
    policy = study.freeze_paid_budget(
        limit_cny=100, price_snapshot=path, connection_profiles=PROFILES
    )
    with pytest.raises(ValueError, match="实际连接"):
        study._paid_inputs({"paid_budget": policy, "connection_profiles": profiles})
    report = study.paid_budget_report(
        {"paid_budget": policy, "connection_profiles": profiles}, [], prior_records=[]
    )
    assert report["evidence_valid"] is False


def test_observed_policy_requires_profiles_and_rejects_nonpeak_or_drifted_implementation(
    tmp_path: Path,
) -> None:
    path = snapshot(tmp_path)
    with pytest.raises(ValueError, match="连接配置"):
        study.freeze_paid_budget(limit_cny=100, price_snapshot=path)
    value = read_json(path)
    value["conservative_estimation"]["cache_read_cny_per_million"] = 0.02
    write_json(path, value)
    with pytest.raises(ValueError, match="最高读取费率"):
        study.freeze_paid_budget(limit_cny=100, price_snapshot=path, connection_profiles=PROFILES)
    path = snapshot(tmp_path)
    value = read_json(path)
    value["pricing_implementation_sha256"] = "0" * 64
    write_json(path, value)
    with pytest.raises(ValueError, match="当前实现"):
        study.freeze_paid_budget(limit_cny=100, price_snapshot=path, connection_profiles=PROFILES)


def test_old_full_price_method_still_allows_explicit_zero_input_rate() -> None:
    assert (
        budget.estimate_paid_usage([record()], input_cny_per_million=0)["known_estimate_cny"] == 2
    )


def priced_development(experiment: dict[str, Any], tmp_path: Path, *, invalid: bool) -> None:
    plan = experiment["manifest"]
    plan["connection_profiles"] = deepcopy(PROFILES)
    plan["paid_budget"] = study.freeze_paid_budget(
        limit_cny=100,
        price_snapshot=snapshot(tmp_path),
        connection_profiles=PROFILES,
    )
    for index, row in enumerate(experiment["records"], 1):
        facts = record(index)
        row.update({key: facts[key] for key in ("job_dir", "request_sha256", "usage")})
        row.update(endpoint="remote", input_tokens=6_000_000, output_tokens=250_000)
    last = experiment["records"][-1]
    native = cached(tmp_path, 99, **({"status": "invalid"} if invalid else {}))
    last.update(
        {
            key: native[key]
            for key in ("cache_usage", "usage_details", "input_tokens", "output_tokens")
        }
    )
    write_json(experiment["manifest_path"], plan)
    save_records(experiment)


def test_last_cache_invalid_keeps_complete_scores_but_blocks_direct_candidate_lock(
    experiment: dict[str, Any], tmp_path: Path
) -> None:
    priced_development(experiment, tmp_path, invalid=True)
    assert (
        select_development_candidate(experiment["manifest"], experiment["records"])["status"]
        == "selected"
    )
    assert not (experiment["records_path"].parent / "invalid.json").exists()
    with pytest.raises(ValueError, match="费用证据"):
        lock(experiment)


def test_complete_budget_threshold_does_not_block_lock_but_native_evidence_drift_blocks_revalidation(
    experiment: dict[str, Any], tmp_path: Path
) -> None:
    priced_development(experiment, tmp_path, invalid=False)
    report = study.paid_budget_report(experiment["manifest"], experiment["records"])
    assert report["usage_complete"] is True
    assert report["stop_reason"] == "paid_estimate_stop_fraction_reached"
    lock(experiment)
    validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))
    Path(experiment["records"][-1]["usage_details"]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="费用证据"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))
