"""统计补充的抽样单位与资格测试；所有成绩均为人工构造的已知结果。"""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture
def sensitivity() -> ModuleType:
    source = Path(__file__).parents[1] / "scripts" / "analyze_sensitivity.py"
    spec = importlib.util.spec_from_file_location("saya_sensitivity_test", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example(
    *, phase: str = "holdout", repeats: int = 2
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = [
        {"task_id": "one", "repository": "repo-small"},
        *[{"task_id": name, "repository": "repo-large"} for name in ("two", "three", "four")],
    ]
    labels = ["baseline"] if phase == "validation" else ["baseline", "candidate"]
    manifest = {
        "phase": phase,
        "frozen": True,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "configurations": labels,
        "baseline": "baseline",
        "candidate": None if phase == "validation" else "candidate",
        "repeats": repeats,
        "tasks": tasks,
    }
    rows = [
        {
            "task_id": task["task_id"],
            "configuration": label,
            "repeat": repeat,
            "status": "completed",
            "verified": True,
            "success": task["task_id"] == "one"
            if label == "candidate"
            else task["task_id"] in {"one", "two"},
            "canonical_model": manifest["canonical_model"],
            "endpoint": "remote",
            "input_tokens": 1,
            "output_tokens": 1,
            "usage_complete": True,
        }
        for task in tasks
        for label in labels
        for repeat in range(1, repeats + 1)
    ]
    return manifest, rows


def test_validation_has_prespecified_absolute_task_interval(sensitivity: ModuleType) -> None:
    manifest, rows = example(phase="validation")
    result = sensitivity.analyze_sensitivity(manifest, rows)
    baseline = result["configurations"]["baseline"]
    assert result["final_result_eligible"] is True
    assert baseline["task_macro_success_rate"] == 0.5
    assert baseline["absolute_success_bootstrap"]["interval_95"] == [0.0, 1.0]
    assert baseline["absolute_success_bootstrap"]["sampling_unit"] == "task"
    assert baseline["absolute_success_bootstrap"]["tasks"] == 4
    assert baseline["absolute_success_bootstrap"]["formal_interval_eligible"] is True
    assert result["paired_repository_sensitivity"] is None


def test_repository_macro_preserves_unequal_task_counts(sensitivity: ModuleType) -> None:
    manifest, rows = example()
    result = sensitivity.analyze_sensitivity(manifest, rows)
    repos = result["configurations"]["candidate"]["repositories"]
    assert repos["repo-small"]["planned_tasks"] == 1
    assert repos["repo-small"]["task_macro_success_rate"] == 1
    assert repos["repo-large"]["planned_tasks"] == 3
    assert repos["repo-large"]["task_macro_success_rate"] == 0
    assert result["configurations"]["candidate"]["task_macro_success_rate"] == 0.25


def test_twenty_four_task_validation_reports_24_units_not_72_attempts(
    sensitivity: ModuleType,
) -> None:
    manifest, _ = example(phase="validation", repeats=3)
    manifest["tasks"] = [
        {"task_id": f"task-{index}", "repository": f"repo-{index % 11}"} for index in range(24)
    ]
    rows = [
        {
            "task_id": task["task_id"],
            "configuration": "baseline",
            "repeat": repeat,
            "status": "completed",
            "verified": True,
            "success": index < 12,
            "canonical_model": manifest["canonical_model"],
            "endpoint": "remote",
        }
        for index, task in enumerate(manifest["tasks"])
        for repeat in range(1, 4)
    ]
    result = sensitivity.analyze_sensitivity(manifest, rows)
    group = result["configurations"]["baseline"]
    assert result["tasks"] == 24 and result["repositories"] == 11
    assert group["observed_attempts"] == 72
    assert group["absolute_success_bootstrap"]["tasks"] == 24
    assert group["absolute_success_bootstrap"]["estimate"] == 0.5
    assert group["absolute_success_bootstrap"]["interval_95"] is not None


def test_repeating_same_results_does_not_inflate_task_or_cluster_sample_size(
    sensitivity: ModuleType,
) -> None:
    first = sensitivity.analyze_sensitivity(*example(repeats=1))
    repeated = sensitivity.analyze_sensitivity(*example(repeats=20))
    assert first["tasks"] == repeated["tasks"] == 4
    assert first["repositories"] == repeated["repositories"] == 2
    assert repeated["configurations"]["baseline"]["observed_attempts"] == 80
    assert (
        first["configurations"]["baseline"]["absolute_success_bootstrap"]
        == repeated["configurations"]["baseline"]["absolute_success_bootstrap"]
    )
    assert first["paired_repository_sensitivity"] == repeated["paired_repository_sensitivity"]


def test_cluster_known_two_repo_distribution_and_equal_weight_estimand(
    sensitivity: ModuleType,
) -> None:
    differences = {"small": 1.0, "large-a": 0.0, "large-b": 0.0, "large-c": 0.0}
    repos = {
        "small": "repo-small",
        "large-a": "repo-large",
        "large-b": "repo-large",
        "large-c": "repo-large",
    }
    result = sensitivity._cluster_bootstrap(differences, repos)
    # 两簇重抽样的可能值为 0、1/4、1，而不是将两仓库永远等权平均。
    assert result["estimate"] == 0.25
    assert result["repository_equal_weight_delta"] == 0.5
    assert result["interval_95"] == [0.0, 1.0]
    assert result["cluster_sizes"] == {"repo-large": 3, "repo-small": 1}
    assert result["repositories"] == 2 and result["tasks"] == 4


def test_resampling_unit_is_whole_repository_and_mixed_draw_uses_task_denominator(
    sensitivity: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class FixedRandom:
        def __init__(self, seed: int) -> None:
            assert seed == 20261022

        def choices(self, population: list[str], *, k: int) -> list[str]:
            assert population == ["large", "small"]
            assert k == 2
            calls.append(tuple(population))
            return population

    monkeypatch.setattr(sensitivity.random, "Random", FixedRandom)
    differences = {"a": 0.0, "b": 0.0, "c": 0.0, "d": 1.0}
    repos = {"a": "large", "b": "large", "c": "large", "d": "small"}
    result = sensitivity._cluster_bootstrap(differences, repos, samples=100)
    assert result["interval_95"] == [0.25, 0.25]
    assert len(calls) == 100


def test_one_repository_has_no_cluster_interval(sensitivity: ModuleType) -> None:
    manifest, rows = example()
    for task in manifest["tasks"]:
        task["repository"] = "single-repo"
    result = sensitivity.analyze_sensitivity(manifest, rows)
    cluster = result["paired_repository_sensitivity"]
    assert cluster["repositories"] == 1
    assert cluster["interval_95"] is None
    assert cluster["interval_status"] == "unavailable_fewer_than_two_repositories"
    assert cluster["formal_interval_eligible"] is False


@pytest.mark.parametrize(
    "kind", ["missing", "unknown", "invalid", "endpoint", "dev", "calibration"]
)
def test_incomplete_unknown_or_ineligible_data_has_no_formal_intervals(
    sensitivity: ModuleType,
    kind: str,
) -> None:
    manifest, rows = example()
    if kind == "missing":
        rows.pop()
    elif kind == "unknown":
        rows[0]["success"] = None
    elif kind == "invalid":
        manifest["validity_issues"] = ["experiment_invalid"]
    elif kind == "endpoint":
        rows[0]["endpoint"] = "different"
    else:
        manifest["phase"] = kind
    result = sensitivity.analyze_sensitivity(manifest, rows)
    assert result["status"] == "descriptive_ineligible"
    assert result["final_result_eligible"] is False
    assert all(
        group["absolute_success_bootstrap"]["interval_95"] is None
        for group in result["configurations"].values()
    )
    assert result["paired_repository_sensitivity"]["interval_95"] is None
    assert result["paired_repository_sensitivity"]["formal_interval_eligible"] is False


def test_unknown_task_is_not_silently_dropped(sensitivity: ModuleType) -> None:
    manifest, rows = example()
    rows[0]["task_id"] = "not-in-manifest"
    with pytest.raises(ValueError, match="不在清单"):
        sensitivity.analyze_sensitivity(manifest, rows)


@pytest.mark.parametrize("phase", ["validation", "holdout"])
def test_invalid_budget_evidence_cannot_restore_formal_interval(
    sensitivity: ModuleType, tmp_path: Path, phase: str
) -> None:
    manifest, rows = example(phase=phase)
    manifest["paid_budget"] = {
        "limit_cny": 100,
        "stop_fraction": 0.8,
        "paid_endpoints": ["remote"],
        "input_cny_per_million": 2,
        "output_cny_per_million": 8,
        "prior_records": [],
        "price_snapshot": {"path": str(tmp_path / "missing-price.json"), "sha256": "a" * 64},
    }
    result = sensitivity.analyze_sensitivity(manifest, rows)
    assert result["final_result_eligible"] is False
    assert "paid_budget_evidence_invalid" in result["validity_issues"]
    assert result["configurations"]["baseline"]["absolute_success_bootstrap"]["interval_95"] is None
    assert result["primary_task_difference_bootstrap"] is None


def test_fixed_seed_is_order_independent_and_does_not_mutate_inputs(
    sensitivity: ModuleType,
) -> None:
    manifest, rows = example()
    original = deepcopy((manifest, rows))
    first = sensitivity.analyze_sensitivity(manifest, rows)
    second = sensitivity.analyze_sensitivity(manifest, list(reversed(rows)))
    assert first == second
    assert (manifest, rows) == original
    assert first["parameters"] == {"samples": 10_000, "seed": 20261022}
    assert first["paired_repository_sensitivity"]["role"] == "sensitivity_not_primary"
    assert first["primary_task_difference_bootstrap"] is not None


def test_cli_inherits_abort_marker_and_only_exports_input_hashes(
    sensitivity: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = example()
    manifest_path, records_path = tmp_path / "manifest.json", tmp_path / "records.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    records_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    (tmp_path / "abort.json").write_text('{"reason":"test_abort"}', encoding="utf-8")
    output = tmp_path / "sensitivity.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sensitivity",
            "--manifest",
            str(manifest_path),
            "--records",
            str(records_path),
            "--output",
            str(output),
        ],
    )
    assert sensitivity.main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "descriptive_ineligible"
    assert "experiment_aborted" in result["validity_issues"]
    assert set(result["inputs"]) == {"manifest_sha256", "records_sha256"}


def test_protocol_freeze_does_not_require_or_read_results(
    sensitivity: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "protocol.json"
    monkeypatch.setattr(sys, "argv", ["sensitivity", "--freeze-protocol", "--output", str(output)])
    assert sensitivity.main() == 0
    frozen = json.loads(output.read_text(encoding="utf-8"))
    assert len(frozen["script_sha256"]) == 64
    assert len(frozen["analysis_sha256"]) == 64
    assert frozen["validity_rules_sha256"] == sensitivity.file_sha256(
        Path(sensitivity.artifacts_module.__file__)
    )
    assert frozen["samples"] == 10_000 and frozen["seed"] == 20261022
    assert "records" not in frozen
    with pytest.raises(FileExistsError):
        sensitivity.main()
