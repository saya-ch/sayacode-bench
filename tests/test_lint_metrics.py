"""指标口径 lint 的单元测试；fixture 是合成汇总，不是真实成绩。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import lint_metrics


def _agent_stats() -> dict:
    return {
        "pass_at_k": {
            "repeats": 2,
            "tasks": 2,
            "pass_at_2": {"definition": "至少一次通过"},
            "pass_pow_2": {"definition": "所有重复都通过"},
        }
    }


def good_summary() -> dict:
    return {
        "schema_version": 2,
        "sample": {"size": 2},
        "repeats": 2,
        "agents": {
            "sayacode": {
                "planned": 4,
                "observed": 3,
                "passes": 2,
                "missing": 1,
                "missing_trials": [],
            },
            "mini-swe": {
                "planned": 4,
                "observed": 3,
                "passes": 2,
                "missing": 1,
                "missing_trials": [],
            },
        },
        "totals": {"planned": 8, "observed": 6, "passes": 4, "missing": 2},
        "stats": {
            "agents": {"sayacode": _agent_stats(), "mini-swe": _agent_stats()},
            "pairwise": {
                "mini-swe_vs_sayacode": {
                    "a": "mini-swe",
                    "b": "sayacode",
                    "common_tasks": 2,
                    "mcnemar_all_repeats_pass": {
                        "definition": "all_repeats_pass",
                        "common_tasks": 2,
                        "a_only": 1,
                        "b_only": 1,
                        "p_value": 1.0,
                    },
                    "mcnemar_any_repeat_pass": {
                        "definition": "any_repeat_pass",
                        "common_tasks": 2,
                        "a_only": 0,
                        "b_only": 1,
                        "p_value": 1.0,
                    },
                }
            },
        },
    }


def test_good_summary_passes() -> None:
    assert lint_metrics.lint_summary(good_summary()) == []


def test_split_denominators_reported() -> None:
    summary = good_summary()
    summary["agents"]["sayacode"]["planned"] = 5
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "denominator_split" in codes


def test_observed_exceeds_planned() -> None:
    summary = good_summary()
    summary["agents"]["sayacode"]["observed"] = 9
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "observed_exceeds_planned" in codes


def test_missing_stats_reported() -> None:
    summary = good_summary()
    del summary["stats"]
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "stats_missing" in codes


def test_mcnemar_without_task_level_fields() -> None:
    summary = good_summary()
    pair = summary["stats"]["pairwise"]["mini-swe_vs_sayacode"]
    del pair["common_tasks"]
    pair["mcnemar_all_repeats_pass"].pop("common_tasks", None)
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "mcnemar_not_task_level" in codes


def test_mcnemar_bad_definition() -> None:
    summary = good_summary()
    summary["stats"]["pairwise"]["mini-swe_vs_sayacode"]["mcnemar_all_repeats_pass"][
        "definition"
    ] = "best_of_2"
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "mcnemar_definition" in codes


def test_pass_at_k_shape_reported() -> None:
    summary = good_summary()
    del summary["stats"]["agents"]["sayacode"]["pass_at_k"]["pass_at_2"]
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "pass_at_k_shape" in codes


def test_totals_mismatch_reported() -> None:
    summary = good_summary()
    summary["totals"]["planned"] = 99
    codes = [issue.code for issue in lint_metrics.lint_summary(summary)]
    assert "totals_mismatch" in codes


def test_cli_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(good_summary()), encoding="utf-8")
    assert lint_metrics.main(["--summary", str(good)]) == 0

    bad_summary = copy.deepcopy(good_summary())
    bad_summary["agents"]["sayacode"]["planned"] = 5
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_summary), encoding="utf-8")
    assert lint_metrics.main(["--summary", str(bad)]) == 1
