"""统计层单元测试：所有数字都是合成数据，不是模型成绩。"""

from __future__ import annotations

import pytest

from sayacode_bench.formal_stats import (
    SAMPLES,
    SEED,
    mcnemar_task_level,
    pass_at_k,
    repository_cluster_bootstrap,
    summarize_stats,
    task_rates,
    wilson_interval,
)


def trial(task_id: str, repeat: int, value: float | None, repo: str = "r") -> dict:
    return {
        "task_id": task_id,
        "repeat": repeat,
        "effective_reward": value,
        "repo": repo,
    }


def test_wilson_bounds_and_edges() -> None:
    low, high = wilson_interval(0, 10) or (None, None)
    assert low == 0.0 and 0 < high < 1
    low, high = wilson_interval(10, 10) or (None, None)
    assert 0 < low < 1 and high == 1.0
    assert wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_task_rates_reduce_repeats_and_drop_incomplete() -> None:
    rows = [
        trial("a", 1, 1.0),
        trial("a", 2, 0.0),
        trial("b", 1, 1.0),
        trial("b", 2, 1.0),
        trial("c", 1, 1.0),
        trial("c", 2, None),
    ]
    rates = task_rates(rows, 2)
    assert rates == {"a": 0.5, "b": 1.0}


def test_task_rates_reject_bad_repeats() -> None:
    with pytest.raises(ValueError):
        task_rates([], 0)


def test_repository_cluster_bootstrap_resamples_repositories() -> None:
    rates = {"a1": 1.0, "a2": 0.0, "b1": 0.5, "b2": 0.5}
    repos = {"a1": "a", "a2": "a", "b1": "b", "b2": "b"}
    result = repository_cluster_bootstrap(rates, repos, samples=500, seed=SEED)
    assert result["repositories"] == 2
    assert result["tasks"] == 4
    assert result["estimate"] == pytest.approx(0.5)
    interval = result["interval_95"]
    assert interval is not None and interval[0] <= result["estimate"] <= interval[1]


def test_repository_cluster_bootstrap_needs_two_repositories() -> None:
    result = repository_cluster_bootstrap({"a": 1.0}, {"a": "only"}, samples=500, seed=SEED)
    assert result["interval_95"] is None
    assert result["interval_status"] == "unavailable_fewer_than_two_repositories"


def test_pass_at_k_is_not_pass_at_1() -> None:
    rates = {"a": 1.0, "b": 0.5, "c": 0.0}
    result = pass_at_k(rates, repeats=2, samples=200, seed=SEED)
    assert result["pass_at_2"]["successes"] == 2  # a、b 至少一次
    assert result["pass_pow_2"]["successes"] == 1  # 只有 a 全过
    assert result["pass_at_2"]["rate"] == pytest.approx(2 / 3)
    assert result["pass_at_2"]["definition"] == "至少一次通过"


def test_pass_at_k_unavailable_for_single_repeat() -> None:
    result = pass_at_k({"a": 1.0}, repeats=1)
    assert result["status"] == "unavailable_single_repeat"


def test_mcnemar_task_level_definitions() -> None:
    a = {"t1": 1.0, "t2": 1.0, "t3": 1.0, "t4": 0.0, "t5": 0.5}
    b = {"t1": 0.0, "t2": 0.0, "t3": 0.0, "t4": 1.0, "t5": 0.5}
    strict = mcnemar_task_level(a, b)
    assert strict["definition"] == "all_repeats_pass"
    assert strict["a_only"] == 3
    assert strict["b_only"] == 1
    assert 0 <= strict["p_value"] <= 1
    loose = mcnemar_task_level(a, b, definition="any_repeat_pass")
    assert loose["definition"] == "any_repeat_pass"
    with pytest.raises(ValueError):
        mcnemar_task_level(a, b, definition="bogus")


def test_summarize_stats_uses_task_blocks_and_reports_pairwise() -> None:
    summary = {
        "repeats": 2,
        "agents": {
            "sayacode": {
                "planned": 4,
                "trials": [
                    trial("t1", 1, 1.0, "r1"),
                    trial("t1", 2, 1.0, "r1"),
                    trial("t2", 1, 0.0, "r2"),
                    trial("t2", 2, 0.0, "r2"),
                ],
            },
            "mini-swe": {
                "planned": 4,
                "trials": [
                    trial("t1", 1, 0.0, "r1"),
                    trial("t1", 2, 1.0, "r1"),
                    trial("t2", 1, 1.0, "r2"),
                    trial("t2", 2, 1.0, "r2"),
                ],
            },
        },
    }
    stats = summarize_stats(summary)
    assert stats["parameters"]["samples"] == SAMPLES
    assert stats["parameters"]["seed"] == SEED
    sayacode = stats["agents"]["sayacode"]
    assert sayacode["task_macro"]["complete_tasks"] == 2
    assert sayacode["task_macro"]["mean"] == pytest.approx(0.5)
    assert sayacode["wilson_task_level"]["n"] == 2
    assert sayacode["wilson_task_level"]["k"] == 1
    pair = stats["pairwise"]["mini-swe_vs_sayacode"]
    assert pair["common_tasks"] == 2
    assert pair["task_macro_delta"] == pytest.approx(0.25)
