"""正式对比的统计层：题级 Wilson、任务块与仓库簇 bootstrap、pass@2 与题级 McNemar。

所有区间都以**任务块**为重抽样单位：同一题跑 2 次仍是 1 个任务块，不能把 trial 当独立样本。
样本量小、仓库簇少，区间只描述观察样本，不认证外部代表性。
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .analysis import paired_bootstrap

SAMPLES = 10_000
SEED = 20261022
Z_95 = 1.96


def _all_pass(value: float) -> bool:
    return value == 1.0


def _any_pass(value: float) -> bool:
    return value > 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson_interval(successes: int, total: int, z: float = Z_95) -> list[float] | None:
    """二项 Wilson 区间；total 必须是独立单位数（任务块），不是 trial 数。"""
    if total <= 0:
        return None
    if successes < 0 or successes > total:
        raise ValueError("successes 必须落在 [0, total]")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def task_rates(trials: Sequence[Mapping[str, Any]], repeats: int) -> dict[str, float]:
    """把 trial 归约为「每题一个观察值」；缺任一重复的题不给出完整值。"""
    if repeats < 1:
        raise ValueError("repeats 必须至少为 1")
    buckets: dict[str, list[float | None]] = defaultdict(lambda: [None] * repeats)
    for row in trials:
        task_id = row.get("task_id")
        repeat = row.get("repeat")
        if not isinstance(task_id, str) or not task_id:
            continue
        if not isinstance(repeat, int) or repeat < 1 or repeat > repeats:
            continue
        value = row.get("effective_reward")
        buckets[task_id][repeat - 1] = float(value) if isinstance(value, (int, float)) else None
    rates: dict[str, float] = {}
    for task_id, values in buckets.items():
        if all(value is not None for value in values):
            rates[task_id] = sum(value for value in values if value is not None) / repeats
    return rates


def repository_of(trials: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in trials:
        task_id, repo = row.get("task_id"), row.get("repo")
        if isinstance(task_id, str) and isinstance(repo, str) and repo:
            result[task_id] = repo
    return result


def repository_cluster_bootstrap(
    rates: Mapping[str, float],
    repositories: Mapping[str, str],
    *,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """以整个仓库为簇重抽：抽中的仓库保留其全部任务，分母随抽中任务数变化。"""
    if samples < 100 or seed < 0:
        raise ValueError("bootstrap 需要至少 100 次抽样与非负 seed")
    groups: dict[str, list[float]] = defaultdict(list)
    for task_id in sorted(rates):
        value = float(rates[task_id])
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("题级成功率必须在 [0, 1] 内")
        groups[repositories[task_id]].append(value)
    names = sorted(groups)
    result: dict[str, Any] = {
        "method": "percentile_repository_cluster_bootstrap_task_macro",
        "sampling_unit": "repository",
        "tasks": sum(len(group) for group in groups.values()),
        "repositories": len(names),
        "cluster_sizes": {name: len(groups[name]) for name in names},
        "estimate": statistics.mean(rates.values()) if rates else None,
        "repository_equal_weight_mean": statistics.mean(
            statistics.mean(groups[name]) for name in names
        ) if names else None,
        "repository_rates": {name: statistics.mean(groups[name]) for name in names},
        "interval_95": None,
        "samples": samples,
        "seed": seed,
    }
    if len(names) < 2:
        result["interval_status"] = "unavailable_fewer_than_two_repositories"
        return result
    generator = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        sampled = generator.choices(names, k=len(names))
        values = [value for name in sampled for value in groups[name]]
        estimates.append(statistics.mean(values))
    result["interval_95"] = [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]
    result["interval_status"] = "available"
    return result


def binary_task_block_bootstrap(
    values: Mapping[str, float], *, samples: int = SAMPLES, seed: int = SEED
) -> dict[str, Any]:
    """对题级二值结果（0/1）重抽任务块；复用主分析的均值抽样。"""
    return paired_bootstrap(values, samples=samples, seed=seed)


def pass_at_k(
    rates: Mapping[str, float],
    *,
    repeats: int,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """pass@2 = 至少一次通过；pass^2 = 所有重复都通过。两者都不是 pass@1。"""
    if repeats < 2:
        return {"repeats": repeats, "status": "unavailable_single_repeat"}
    any_pass = {task_id: 1.0 if value > 0 else 0.0 for task_id, value in rates.items()}
    all_pass = {task_id: 1.0 if value == 1.0 else 0.0 for task_id, value in rates.items()}
    any_count = sum(any_pass.values())
    all_count = sum(all_pass.values())
    tasks = len(rates)
    return {
        "repeats": repeats,
        "tasks": tasks,
        "pass_at_2": {
            "definition": "至少一次通过",
            "successes": int(any_count),
            "rate": any_count / tasks if tasks else None,
            "bootstrap": binary_task_block_bootstrap(any_pass, samples=samples, seed=seed),
            "wilson": wilson_interval(int(any_count), tasks),
        },
        "pass_pow_2": {
            "definition": "所有重复都通过",
            "successes": int(all_count),
            "rate": all_count / tasks if tasks else None,
            "bootstrap": binary_task_block_bootstrap(all_pass, samples=samples, seed=seed),
            "wilson": wilson_interval(int(all_count), tasks),
        },
    }


def mcnemar_task_level(
    rates_a: Mapping[str, float],
    rates_b: Mapping[str, float],
    *,
    definition: str = "all_repeats_pass",
) -> dict[str, Any]:
    """题级配对 McNemar；二值化定义显式标注，不用 best-of-2 冒充 pass@1。"""
    if definition == "all_repeats_pass":
        to_binary = _all_pass
    elif definition == "any_repeat_pass":
        to_binary = _any_pass
    else:
        raise ValueError("definition 必须是 all_repeats_pass 或 any_repeat_pass")
    common = sorted(set(rates_a) & set(rates_b))
    a_only = b_only = 0
    for task_id in common:
        left, right = to_binary(rates_a[task_id]), to_binary(rates_b[task_id])
        if left and not right:
            a_only += 1
        elif right and not left:
            b_only += 1
    discordant = a_only + b_only
    if discordant == 0:
        p_value = 1.0
    else:
        smaller = min(a_only, b_only)
        tail = sum(math.comb(discordant, x) for x in range(0, smaller + 1)) / (2 ** discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "definition": definition,
        "common_tasks": len(common),
        "a_only": a_only,
        "b_only": b_only,
        "discordant": discordant,
        "p_value": p_value,
        "test": "exact_binomial_two_sided",
    }


def _agent_stats(agent_data: Mapping[str, Any], repeats: int) -> dict[str, Any]:
    trials = agent_data.get("trials", [])
    if not isinstance(trials, list):
        raise ValueError("trials 必须是列表")
    rates = task_rates(trials, repeats)
    repositories = repository_of(trials)
    all_pass = {task_id: 1.0 if value == 1.0 else 0.0 for task_id, value in rates.items()}
    return {
        "task_macro": {
            "definition": "先按题归约重复，再对题取算术平均（每题的重复不增加独立样本）",
            "planned_tasks": agent_data.get("planned", 0) // repeats if repeats else 0,
            "complete_tasks": len(rates),
            "mean": statistics.mean(rates.values()) if rates else None,
        },
        "task_block_bootstrap": paired_bootstrap(rates, samples=SAMPLES, seed=SEED),
        "wilson_task_level": {
            "definition": "任务块全重复通过率（不是 pass@1，也不是 trial 级）",
            "n": len(all_pass),
            "k": int(sum(all_pass.values())),
            "rate": (sum(all_pass.values()) / len(all_pass)) if all_pass else None,
            "interval_95": wilson_interval(int(sum(all_pass.values())), len(all_pass)),
        },
        "pass_at_k": pass_at_k(rates, repeats=repeats),
        "repository_cluster_bootstrap": repository_cluster_bootstrap(rates, repositories),
        "task_rates": rates,
    }


def summarize_stats(summary: Mapping[str, Any]) -> dict[str, Any]:
    """从 formal.summarize 的产物计算统计；只读已归约的 trial 行。"""
    repeats = int(summary.get("repeats", 2))
    agents = summary.get("agents", {})
    if not isinstance(agents, Mapping):
        raise ValueError("agents 必须是对象")
    per_agent: dict[str, Any] = {}
    for agent, data in agents.items():
        if not isinstance(data, Mapping):
            raise ValueError("每个 agent 必须是对象")
        per_agent[str(agent)] = _agent_stats(data, repeats)
    names = sorted(per_agent)
    pairwise: dict[str, Any] = {}
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            rates_left = per_agent[left]["task_rates"]
            rates_right = per_agent[right]["task_rates"]
            common = sorted(set(rates_left) & set(rates_right))
            deltas = {
                task_id: rates_left[task_id] - rates_right[task_id] for task_id in common
            }
            pairwise[f"{left}_vs_{right}"] = {
                "a": left,
                "b": right,
                "common_tasks": len(common),
                "task_macro_delta": statistics.mean(deltas.values()) if deltas else None,
                "paired_bootstrap": paired_bootstrap(deltas, samples=SAMPLES, seed=SEED),
                "mcnemar_all_repeats_pass": mcnemar_task_level(rates_left, rates_right),
                "mcnemar_any_repeat_pass": mcnemar_task_level(
                    rates_left, rates_right, definition="any_repeat_pass"
                ),
            }
    return {
        "parameters": {"samples": SAMPLES, "seed": SEED, "unit": "task block"},
        "agents": per_agent,
        "pairwise": pairwise,
        "cautions": [
            "区间以任务块为独立单位；重复次数不增加独立样本数。",
            "pass@2 与 pass^2 都不是 pass@1；题级 McNemar 的二值定义已显式标注。",
            "全成全败时经验 bootstrap 可能退化为零宽区间，不表示总体概率确定。",
            "仓库簇只有 9 个，簇 bootstrap 仅作敏感性观察，不能独立证明生产泛化。",
        ],
    }


__all__ = [
    "SAMPLES",
    "SEED",
    "binary_task_block_bootstrap",
    "mcnemar_task_level",
    "pass_at_k",
    "repository_cluster_bootstrap",
    "repository_of",
    "summarize_stats",
    "task_rates",
    "wilson_interval",
]
