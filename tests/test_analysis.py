"""核查统计边界，测试数据不是模型成绩。"""

import json
import subprocess
import sys
from copy import deepcopy

import pytest
from resource_samples import runtime_evidence

from sayacode_bench.analysis import (
    analyze_experiment,
    paired_bootstrap,
    select_development_candidate,
)
from sayacode_bench.artifacts import implementation_identity


def manifest(*, phase="holdout", repeats=2):
    return {
        "phase": phase,
        "frozen": True,
        "implementation": implementation_identity(),
        "canonical_model": "DeepSeek-V4.1-Flash",
        "configurations": ["reference", "revised"],
        "baseline": "reference",
        "candidate": "revised",
        "repeats": repeats,
        "benchmark": "swe-bench-pro-v2",
        "runtime_evidence_required": True,
        "qualified_runtime_identities": {key: runtime_evidence() for key in ("alpha", "beta")},
        "tasks": [
            {
                "task_id": "alpha",
                "repository": "repo-a",
                "environment": {"cpus": 1, "memory_mb": 4096},
            },
            {
                "task_id": "beta",
                "repository": "repo-b",
                "environment": {"cpus": 1, "memory_mb": 4096},
            },
        ],
    }


def records():
    return [
        {
            "task_id": task,
            "configuration": label,
            "repeat": repeat,
            "status": "completed",
            "success": label == "revised" or task == "alpha",
            "verified": True,
            "canonical_model": "DeepSeek-V4.1-Flash",
            "endpoint": "local_proxy",
            "duration_seconds": 10,
            "input_tokens": 100,
            "output_tokens": 20,
            "usage_complete": True,
            "runtime_identity": runtime_evidence(),
            "replay_runtime_identity": runtime_evidence(),
        }
        for task in ("alpha", "beta")
        for label in ("reference", "revised")
        for repeat in (1, 2)
    ]


def test_complete_generic_labels_and_task_block_bootstrap():
    result = analyze_experiment(manifest(), records(), bootstrap_samples=1000)
    assert result["formal_comparison_eligible"] is True
    assert result["groups"]["reference"]["task_macro_success_rate"] == 0.5
    assert result["comparison"]["descriptive_delta"] == 0.5
    assert result["comparison"]["bootstrap"]["tasks"] == 2
    assert result["comparison"]["bootstrap"]["interval_95"] == [0.0, 1.0]


def test_repeat_rows_do_not_increase_independent_task_count():
    result = analyze_experiment(manifest(), records(), bootstrap_samples=1000)
    assert result["groups"]["reference"]["recorded"] == 4
    assert result["comparison"]["bootstrap"]["tasks"] == 2


@pytest.mark.parametrize("phase", ["dev", "calibration"])
def test_non_holdout_has_no_formal_interval(phase):
    result = analyze_experiment(manifest(phase=phase), records())
    assert result["formal_comparison_eligible"] is False
    assert result["comparison"]["bootstrap"] is None


def test_missing_pair_and_unknown_remain_visible():
    rows = records()[:-1]
    rows[0]["success"] = None
    result = analyze_experiment(manifest(), rows)
    assert result["formal_comparison_eligible"] is False
    assert result["groups"]["revised"]["missing"] == 1
    assert result["groups"]["reference"]["unknown"] == 1
    assert result["groups"]["reference"]["task_macro_success_rate"] is None
    assert result["comparison"]["bootstrap"] is None


@pytest.mark.parametrize(
    "change, issue",
    [
        ({"verified": False}, "unverified_success"),
        ({"status": "timeout"}, "unverified_success"),
        ({"canonical_model": "other"}, "model_mismatch"),
        ({"endpoint": None}, "missing_endpoint"),
    ],
)
def test_unverified_or_changed_model_cannot_support_conclusion(change, issue):
    rows = records()
    rows[0].update(change)
    result = analyze_experiment(manifest(), rows)
    assert result["formal_comparison_eligible"] is False
    assert any(value.startswith(issue) for value in result["validity_issues"])


def test_unverified_completed_failure_is_unknown():
    rows = records()
    rows[4]["verified"] = False
    result = analyze_experiment(manifest(), rows)
    assert result["groups"]["reference"]["unknown"] == 1
    assert result["formal_comparison_eligible"] is False


def test_runtime_failure_stays_in_end_to_end_denominator():
    rows = records()
    rows[0].update(
        status="model_error", success=False, verified=False, input_tokens=None, output_tokens=None
    )
    result = analyze_experiment(manifest(), rows, bootstrap_samples=100)
    assert result["groups"]["reference"]["recorded"] == 4
    assert result["groups"]["reference"]["failures"] == 3
    assert result["groups"]["reference"]["resources"]["input_tokens"]["missing"] == 1
    assert result["formal_comparison_eligible"] is True


@pytest.mark.parametrize("code", [401, 402, 403, 429])
@pytest.mark.parametrize("phase", ["holdout", "validation", "dev"])
def test_terminal_service_failure_without_abort_marker_cannot_be_formal_or_selected(code, phase):
    plan, rows = manifest(phase=phase), records()
    if phase == "validation":
        plan.update(configurations=["reference"], candidate=None)
        rows = [row for row in rows if row["configuration"] == "reference"]
    rows[-1].update(status="failed", success=False, verified=False, terminal_http_statuses=[code])
    result = analyze_experiment(plan, iter(rows), bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is False
    assert result["formal_validation_eligible"] is False
    assert result["final_result_eligible"] is False
    assert "fatal_stop_condition:model_service_limit" in result["validity_issues"]
    if result["comparison"] is not None:
        assert result["comparison"]["bootstrap"] is None
    if phase == "dev":
        assert select_development_candidate(plan, rows)["status"] == "incomplete"


def test_historical_connection_failure_window_invalidates_complete_offline_report():
    rows = records()
    for index in (0, 2):
        rows[index].update(
            status="failed", success=False, verified=False, failure_category="model_connection"
        )
    assert all(row.get("failure_category") is None for row in rows[-5:])
    result = analyze_experiment(manifest(), rows, bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is False
    assert result["comparison"]["bootstrap"] is None
    assert "fatal_stop_condition:unstable_model_connection" in result["validity_issues"]


def test_authorized_endpoint_switch_between_blocks_is_recorded():
    rows = records()
    for row in rows:
        if row["task_id"] == "beta":
            row["endpoint"] = "siliconflow"
    result = analyze_experiment(manifest(), rows, bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is True
    assert result["endpoint_counts"] == {"local_proxy": 4, "siliconflow": 4}


def test_endpoint_switch_within_pair_invalidates_unqualified_comparison():
    rows = records()
    rows[0]["endpoint"] = "siliconflow"
    result = analyze_experiment(manifest(), rows)
    assert result["formal_comparison_eligible"] is False
    assert "paired_endpoint_mismatch" in result["validity_issues"]
    assert result["comparison"]["endpoint_mismatches"] == [{"task_id": "alpha", "repeat": 1}]


def test_unfrozen_or_invalid_batch_has_no_formal_comparison():
    plan = manifest()
    plan.update(frozen=False, validity_issues=["quota_interrupted"])
    result = analyze_experiment(plan, records())
    assert result["formal_comparison_eligible"] is False
    assert "manifest_not_frozen" in result["validity_issues"]
    assert "quota_interrupted" in result["validity_issues"]


@pytest.mark.parametrize("mutation", ["duplicate", "extra_task", "extra_repeat", "extra_label"])
def test_unplanned_rows_are_rejected(mutation):
    rows = records()
    if mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "extra_task":
        rows[0]["task_id"] = "unplanned"
    elif mutation == "extra_repeat":
        rows[0]["repeat"] = 3
    else:
        rows[0]["configuration"] = "unplanned"
    with pytest.raises(ValueError):
        analyze_experiment(manifest(), rows)


@pytest.mark.parametrize("value", [-1, 1.5, float("nan"), float("inf"), True, "20"])
def test_resource_numbers_are_validated(value):
    rows = records()
    rows[0]["input_tokens"] = value
    with pytest.raises(ValueError):
        analyze_experiment(manifest(), rows)


def test_unknown_usage_is_not_fabricated_as_zero():
    rows = records()
    for row in rows:
        row["input_tokens"] = row["output_tokens"] = None
        row["usage_complete"] = False
    result = analyze_experiment(manifest(), rows, bootstrap_samples=100)
    resource = result["groups"]["reference"]["resources"]
    assert resource["input_tokens"]["reported_sum"] is None
    assert resource["input_tokens"]["missing"] == 4
    assert resource["cost"] is None


def test_bootstrap_is_deterministic_and_does_not_mutate_inputs():
    values = {"c": 0.5, "a": -1.0, "b": 1.0}
    before = deepcopy(values)
    assert paired_bootstrap(values, samples=1000, seed=7) == paired_bootstrap(
        dict(reversed(list(values.items()))), samples=1000, seed=7
    )
    assert values == before


def test_one_task_has_no_confidence_interval():
    assert paired_bootstrap({"one": 1.0})["interval_95"] is None


def test_development_selection_uses_quality_first():
    selected = select_development_candidate(manifest(phase="dev"), records())
    assert selected["selected"] == "revised"


def test_development_selection_uses_tokens_only_if_complete():
    rows = records()
    for row in rows:
        row["success"] = True
        if row["configuration"] == "revised":
            row["input_tokens"] = 50
    assert select_development_candidate(manifest(phase="dev"), rows)["selected"] == "revised"
    rows[0]["usage_complete"] = False
    assert select_development_candidate(manifest(phase="dev"), rows)["selected"] == "reference"


def test_development_selection_rejects_incomplete_or_holdout_data():
    assert (
        select_development_candidate(manifest(phase="dev"), records()[:-1])["status"]
        == "incomplete"
    )
    with pytest.raises(ValueError):
        select_development_candidate(manifest(), records())


def test_development_selection_checks_every_candidate_endpoint_pair():
    plan, rows = manifest(phase="dev"), records()
    plan["configurations"].append("third")
    plan["candidate"] = None
    for row in records():
        if row["configuration"] == "revised":
            row.update(configuration="third", endpoint="siliconflow")
            rows.append(row)
    result = select_development_candidate(plan, rows)
    assert result["status"] == "incomplete"
    assert "paired_endpoint_mismatch" in result["validity_issues"]


@pytest.mark.parametrize(
    "status", ["running", "pending", "queued", "not_started", "blocked", "paused"]
)
def test_unfinished_trial_is_unknown_even_if_incorrectly_marked_failed(status):
    rows = records()
    rows[0].update(status=status, success=False)
    result = analyze_experiment(manifest(), rows)
    assert result["formal_comparison_eligible"] is False
    assert result["groups"]["reference"]["unknown"] == 1


def test_holdout_does_not_allow_extra_candidate_peeking():
    plan = manifest()
    plan["configurations"].append("third")
    result = analyze_experiment(plan, records())
    assert "holdout_requires_two_configurations" in result["validity_issues"]


def test_baseline_validation_has_final_results_without_manufactured_comparison():
    plan = manifest(phase="validation")
    plan.update(configurations=["reference"], candidate=None)
    rows = [row for row in records() if row["configuration"] == "reference"]
    result = analyze_experiment(plan, rows)
    assert result["formal_validation_eligible"] is True
    assert result["final_result_eligible"] is True
    assert result["formal_comparison_eligible"] is False
    assert result["comparison"] is None
    assert result["conclusion_scope"] == "independent_validation"
    assert result["groups"]["reference"]["task_macro_success_rate"] == 0.5


def test_incomplete_validation_cannot_produce_final_conclusion():
    plan = manifest(phase="validation")
    plan.update(configurations=["reference"], candidate=None)
    rows = [row for row in records() if row["configuration"] == "reference"][:-1]
    result = analyze_experiment(plan, rows)
    assert result["formal_validation_eligible"] is False
    assert result["final_result_eligible"] is False
    assert result["comparison"] is None


def test_validation_rejects_hidden_extra_configuration():
    result = analyze_experiment(manifest(phase="validation"), records())
    assert result["formal_validation_eligible"] is False
    assert "validation_requires_only_baseline" in result["validity_issues"]


def test_analysis_does_not_modify_manifest_or_records():
    plan, rows = manifest(), records()
    original = deepcopy((plan, rows))
    analyze_experiment(plan, rows, bootstrap_samples=100)
    assert (plan, rows) == original


def resource_experiment(phase="holdout"):
    plan, rows = manifest(phase=phase), records()
    if phase == "validation":
        plan.update(configurations=["reference"], candidate=None)
        rows = [row for row in rows if row["configuration"] == "reference"]
    plan.update(
        benchmark="swe-bench-pro-v2",
        runtime_evidence_required=True,
        qualified_runtime_identities={
            task["task_id"]: runtime_evidence() for task in plan["tasks"]
        },
    )
    for task in plan["tasks"]:
        task["environment"] = {"cpus": 1, "memory_mb": 4096}
    for row in rows:
        row.update(
            runtime_identity=runtime_evidence(),
            replay_runtime_identity=runtime_evidence(),
            runtime_comparison={"same_image": True, "same_platform": True, "same_resources": True},
            original_reward=int(row["success"]),
            replay_reward=int(row["success"]),
        )
    return plan, rows


def test_required_resource_evidence_accepts_complete_source_pristine_and_qualification():
    plan, rows = resource_experiment()
    result = analyze_experiment(plan, rows, bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is True
    assert result["comparison"]["bootstrap"] is not None


@pytest.mark.parametrize("phase", ["holdout", "validation", "dev"])
@pytest.mark.parametrize("side", ["runtime_identity", "replay_runtime_identity", "qualification"])
def test_offline_resource_drift_blocks_formal_conclusions_without_rewriting_outcomes(phase, side):
    plan, rows = resource_experiment(phase)
    prior = deepcopy(rows)
    target = (
        plan["qualified_runtime_identities"][rows[-1]["task_id"]]
        if side == "qualification"
        else rows[-1][side]
    )
    target["docker_limits"]["MemorySwap"] = 4 * 1024**3
    target["cgroup_v2"]["memory.swap.max"] = "0"
    before = deepcopy(rows)
    result = analyze_experiment(plan, rows, bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is False
    assert result["formal_validation_eligible"] is False
    assert result["final_result_eligible"] is False
    assert any(issue.startswith("runtime_evidence:") for issue in result["validity_issues"])
    assert rows == before
    assert [(row["original_reward"], row["input_tokens"], row["success"]) for row in rows] == [
        (row["original_reward"], row["input_tokens"], row["success"]) for row in prior
    ]
    if result["comparison"] is not None:
        assert result["comparison"]["bootstrap"] is None
    if phase == "dev":
        assert select_development_candidate(plan, rows)["status"] == "incomplete"


@pytest.mark.parametrize("missing", ["cgroup", "qualification", "pristine"])
def test_required_missing_runtime_evidence_stays_ineligible_even_if_saved_flags_say_true(missing):
    plan, rows = resource_experiment()
    if missing == "qualification":
        plan.pop("qualified_runtime_identities")
    elif missing == "pristine":
        rows[-1].pop("replay_runtime_identity")
    else:
        rows[-1]["runtime_identity"].pop("cgroup_v2")
    result = analyze_experiment(plan, rows, bootstrap_samples=100)
    assert result["formal_comparison_eligible"] is False
    assert result["comparison"]["bootstrap"] is None


@pytest.mark.parametrize("phase", ["dev", "holdout", "validation"])
@pytest.mark.parametrize("policy", [None, False])
def test_offline_formal_resource_policy_cannot_be_removed_or_disabled(phase, policy):
    plan, rows = resource_experiment(phase)
    if policy is None:
        plan.pop("runtime_evidence_required")
    else:
        plan["runtime_evidence_required"] = policy
    for row in rows:
        row.pop("runtime_identity")
        row.pop("replay_runtime_identity")
    result = analyze_experiment(plan, rows, bootstrap_samples=100)
    assert result["final_result_eligible"] is False
    assert result["formal_comparison_eligible"] is False
    assert result["formal_validation_eligible"] is False
    assert "runtime_policy_required_for_formal_phase" in result["validity_issues"]
    assert sum(group["recorded"] for group in result["groups"].values()) == len(rows)
    if result["comparison"] is not None:
        assert result["comparison"]["bootstrap"] is None
    if phase == "dev":
        assert select_development_candidate(plan, rows)["status"] == "incomplete"


@pytest.mark.parametrize("phase", ["dev", "holdout", "validation"])
@pytest.mark.parametrize("change", ["missing", "changed", "partial"])
def test_frozen_implementation_required_for_formal_summary_and_candidate(phase, change):
    plan, rows = resource_experiment(phase)
    if change == "missing":
        plan.pop("implementation")
    elif change == "partial":
        plan["implementation"].pop("analysis.py")
    else:
        plan["implementation"]["analysis.py"] = "0" * 64
    original = deepcopy((plan, rows))
    result = analyze_experiment(plan, rows, bootstrap_samples=100)
    assert result["final_result_eligible"] is False
    assert result["formal_comparison_eligible"] is False
    assert result["formal_validation_eligible"] is False
    assert any(issue.startswith("implementation_identity_") for issue in result["validity_issues"])
    assert (plan, rows) == original
    if result["comparison"] is not None:
        assert result["comparison"]["bootstrap"] is None
    if phase == "dev":
        assert select_development_candidate(plan, rows)["status"] == "incomplete"


def test_analysis_cli_preserves_invalid_financial_evidence(tmp_path):
    plan, rows = resource_experiment()
    plan["paid_budget"] = {
        "limit_cny": 100,
        "stop_fraction": 0.8,
        "paid_endpoints": ["remote"],
        "input_cny_per_million": 2,
        "output_cny_per_million": 8,
        "prior_records": [],
        "price_snapshot": {"path": str(tmp_path / "missing-price.json"), "sha256": "a" * 64},
    }
    manifest_path, records_path = tmp_path / "manifest.json", tmp_path / "records.jsonl"
    manifest_path.write_text(json.dumps(plan), encoding="utf-8")
    records_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    original = manifest_path.read_bytes(), records_path.read_bytes()
    output = tmp_path / "analysis.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sayacode_bench.analysis",
            "--manifest",
            str(manifest_path),
            "--records",
            str(records_path),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["final_result_eligible"] is False
    assert "paid_budget_evidence_invalid" in result["validity_issues"]
    assert result["paid_budget"]["evidence_valid"] is False
    assert result["comparison"]["bootstrap"] is None
    assert (manifest_path.read_bytes(), records_path.read_bytes()) == original
