"""费用估价与派发停止的行为测试，不调用模型或供应商账户接口。"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from sayacode_bench.budget import budget_reason, estimate_paid_usage


def record(index: int = 1, **updates: Any) -> dict[str, Any]:
    row = {
        "job_dir": f"C:/experiment/jobs/task-{index}",
        "request_sha256": f"{index:064x}",
        "endpoint": "remote",
        "task_id": f"task-{index}",
        "configuration": "baseline",
        "repeat": 1,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "input_tokens": 1_000_000,
        "output_tokens": 250_000,
        "usage_complete": True,
        "usage": {
            "model_calls": 10,
            "reported_calls": 10,
            "missing_usage_calls": 0,
            "damaged_audit_lines": 0,
        },
    }
    row.update(updates)
    return row


def test_estimate_uses_peak_prices_and_ignores_cache_discount() -> None:
    row = record(input_token_details={"cache_read": 1_000_000})
    result = estimate_paid_usage([row])
    assert result["known_estimate_cny"] == 4
    assert result["usage_complete"] is True
    assert result["paid_model_calls"] == 10
    assert result["missing_usage_calls"] == 0
    assert result["cache_discount_applied"] is False
    assert result["total_bill_cny"] is None


def test_no_observations_does_not_claim_zero_total_bill() -> None:
    result = estimate_paid_usage([])
    assert result["known_estimate_cny"] == 0
    assert result["paid_records"] == 0
    assert result["usage_complete"] is True
    assert result["total_bill_cny"] is None
    assert "zero observations" in result["scope"]


def test_local_cost_is_unknown_without_blocking_complete_paid_usage() -> None:
    result = estimate_paid_usage([record(1, endpoint="local", usage_complete=False), record(2)])
    assert result["known_estimate_cny"] == 4
    assert result["paid_records"] == 1
    assert result["unpriced_endpoints"] == ["local"]
    assert result["local_cost_cny"] is None
    assert result["usage_complete"] is True


def test_partial_usage_keeps_known_cost_and_stops_new_paid_tasks() -> None:
    row = record(
        output_tokens=None,
        usage_complete=False,
        usage={
            "model_calls": 10,
            "reported_calls": 8,
            "missing_usage_calls": 2,
            "damaged_audit_lines": 0,
        },
    )
    result = estimate_paid_usage([row])
    assert result["known_estimate_cny"] == 2
    assert result["usage_complete"] is False
    assert result["incomplete_paid_records"] == 1
    assert result["missing_usage_calls"] == 2
    assert budget_reason([row], limit_cny=1000) == "paid_usage_incomplete"


def test_unknown_call_count_is_not_invented() -> None:
    row = record(usage=None, input_tokens=None, output_tokens=None, usage_complete=None)
    result = estimate_paid_usage([row])
    assert result["known_estimate_cny"] == 0
    assert result["usage_complete"] is False
    assert result["paid_model_calls"] is None
    assert result["missing_usage_calls"] is None


@pytest.mark.parametrize(
    "usage",
    [None, {}, {"model_calls": 10}, {"reported_calls": 10}]
    + [
        {
            key: value
            for key, value in {
                "model_calls": 10,
                "reported_calls": 10,
                "missing_usage_calls": 0,
                "damaged_audit_lines": 0,
            }.items()
            if key != missing
        }
        for missing in (
            "model_calls",
            "reported_calls",
            "missing_usage_calls",
            "damaged_audit_lines",
        )
    ],
)
def test_complete_flag_cannot_replace_missing_call_coverage(usage: Any) -> None:
    row = record(usage=usage)
    result = estimate_paid_usage([row])
    assert result["known_estimate_cny"] == 4
    assert result["usage_complete"] is False
    assert result["missing_usage_calls"] is None
    assert budget_reason([row], limit_cny=1000) == "paid_usage_incomplete"


def test_damaged_audit_lines_make_missing_call_count_unknown() -> None:
    row = record(usage={"model_calls": 10, "reported_calls": 10, "damaged_audit_lines": 1})
    result = estimate_paid_usage([row])
    assert result["usage_complete"] is False
    assert result["missing_usage_calls"] is None


def test_same_original_and_replay_are_charged_once() -> None:
    original = record()
    replay = {**original, "source_job": original["job_dir"], "verified": True, "replay_reward": 1}
    result = estimate_paid_usage([original, replay])
    assert result["known_estimate_cny"] == 4
    assert result["unique_records"] == 1
    assert result["duplicate_records"] == 1


def test_windows_path_spelling_and_request_identity_are_deduplicated() -> None:
    original = record()
    copy = {**original, "job_dir": r"c:\experiment\JOBS\task-1\."}
    result = estimate_paid_usage([original, copy])
    assert result["unique_records"] == 1
    assert result["known_estimate_cny"] == 4
    request_only = {key: value for key, value in original.items() if key != "job_dir"}
    assert estimate_paid_usage([original, request_only])["unique_records"] == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"endpoint": "local"},
        {"input_tokens": 123},
        {"usage_complete": False},
        {"request_sha256": "f" * 64},
        {"task_id": "different-task"},
    ],
)
def test_conflicting_duplicate_identity_is_rejected(updates: dict[str, Any]) -> None:
    original = record()
    with pytest.raises(ValueError, match="冲突"):
        estimate_paid_usage([original, {**original, **updates}])


def test_record_cannot_silently_merge_two_existing_independent_jobs() -> None:
    left, right = record(1), record(2)
    bridge = {**left, "source_job": right["job_dir"]}
    with pytest.raises(ValueError, match="两个"):
        estimate_paid_usage([left, right, bridge])


def test_prior_phases_and_current_records_share_one_estimated_budget() -> None:
    prior, current = record(1), record(2)
    assert budget_reason([current], [prior], limit_cny=10) == "paid_estimate_stop_fraction_reached"
    assert budget_reason([current], limit_cny=10) is None
    assert budget_reason([prior], [prior], limit_cny=10) is None
    assert (
        budget_reason([], [record(usage_complete=False)], limit_cny=10) == "paid_usage_incomplete"
    )


def test_decimal_boundary_stops_at_exact_threshold() -> None:
    row = record(input_tokens=400_000, output_tokens=0)
    assert budget_reason([row], limit_cny=Decimal("1.00")) == "paid_estimate_stop_fraction_reached"
    below = record(input_tokens=399_999, output_tokens=0)
    assert budget_reason([below], limit_cny=1) is None
    assert budget_reason([], limit_cny=0) == "paid_estimate_stop_fraction_reached"


def test_multiple_explicit_paid_aliases_and_custom_prices() -> None:
    rows = [record(1), record(2, endpoint="another_paid")]
    result = estimate_paid_usage(
        iter(rows),
        paid_endpoints=("remote", "another_paid"),
        input_cny_per_million=Decimal("1.5"),
        output_cny_per_million=3,
    )
    assert result["known_estimate_cny"] == 4.5
    assert result["paid_records"] == 2


@pytest.mark.parametrize("value", [-1, True, 1.5, float("nan"), "12"])
def test_invalid_token_values_are_not_used_for_estimation(value: Any) -> None:
    with pytest.raises(ValueError):
        estimate_paid_usage([record(input_tokens=value)])


@pytest.mark.parametrize("value", [-1, True, float("inf"), float("nan")])
def test_invalid_rates_and_limits_are_rejected(value: Any) -> None:
    with pytest.raises(ValueError):
        estimate_paid_usage([], input_cny_per_million=value)
    with pytest.raises(ValueError):
        budget_reason([], limit_cny=value)


@pytest.mark.parametrize("value", [0, -1, 1.1, True, float("nan")])
def test_invalid_stop_fraction_is_rejected(value: Any) -> None:
    with pytest.raises(ValueError):
        budget_reason([], limit_cny=10, stop_fraction=value)


def test_missing_identity_and_contradictory_audit_are_rejected() -> None:
    row = record()
    row.pop("job_dir")
    row.pop("request_sha256")
    with pytest.raises(ValueError, match="身份"):
        estimate_paid_usage([row])
    with pytest.raises(ValueError, match="不能大于"):
        estimate_paid_usage([record(usage={"model_calls": 1, "reported_calls": 2})])


@pytest.mark.parametrize("value", ["remote", (), ("https://secret.invalid",)])
def test_invalid_paid_endpoint_declaration_cannot_silently_mark_remote_as_free(value: Any) -> None:
    with pytest.raises(ValueError, match="paid_endpoints"):
        estimate_paid_usage([record()], paid_endpoints=value)


def test_inputs_are_not_mutated() -> None:
    rows = [record()]
    saved = deepcopy(rows)
    estimate_paid_usage(rows)
    budget_reason(rows, limit_cny=100)
    assert rows == saved
