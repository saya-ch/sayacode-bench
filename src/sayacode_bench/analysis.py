"""汇总预先声明的试验，并按任务块计算配对区间。"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import fatal_stop_reason


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} 必须是至少为 {minimum} 的整数")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是非负有限数")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} 必须是非负有限数")
    return result


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_bootstrap(
    differences: Mapping[str, float], *, samples: int = 10_000, seed: int = 20261022
) -> dict[str, Any]:
    """对每题的重复均值之差重抽样，重复次数不增加独立样本数。"""
    _integer(samples, "samples", minimum=100)
    _integer(seed, "seed")
    values = [float(differences[key]) for key in sorted(differences)]
    if any(not math.isfinite(value) or not -1 <= value <= 1 for value in values):
        raise ValueError("每题成功率差必须在 [-1, 1] 内")
    if not values:
        return {"tasks": 0, "estimate": None, "interval_95": None}
    estimate = statistics.mean(values)
    if len(values) == 1:
        return {"tasks": 1, "estimate": estimate, "interval_95": None}
    generator = random.Random(seed)
    resampled = [statistics.mean(generator.choices(values, k=len(values))) for _ in range(samples)]
    return {
        "tasks": len(values),
        "estimate": estimate,
        "interval_95": [_percentile(resampled, 0.025), _percentile(resampled, 0.975)],
        "method": "percentile_task_block_bootstrap",
        "samples": samples,
        "seed": seed,
    }


def _resources(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"attempts": len(rows)}
    for field in ("input_tokens", "output_tokens", "duration_seconds"):
        observed: list[float] = []
        for row in rows:
            value = row.get(field)
            if value is not None:
                observed.append(
                    _number(value, field) if field == "duration_seconds" else _integer(value, field)
                )
        entry: dict[str, Any] = {
            "observed": len(observed),
            "missing": len(rows) - len(observed),
            "reported_sum": sum(observed) if observed else None,
        }
        if field == "duration_seconds":
            entry["median"] = statistics.median(observed) if observed else None
            entry["p95"] = _percentile(observed, 0.95) if observed else None
        summary[field] = entry
    summary["complete_usage_attempts"] = sum(
        row.get("usage_complete") is True
        and row.get("input_tokens") is not None
        and row.get("output_tokens") is not None
        for row in rows
    )
    summary["cost"] = None
    return summary


def analyze_experiment(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    bootstrap_samples: int = 10_000,
    seed: int = 20261022,
) -> dict[str, Any]:
    """按冻结清单汇总；不读取验证材料，也不重新判分。"""
    phase = _text(manifest.get("phase"), "phase")
    if phase not in {"calibration", "dev", "holdout", "validation"}:
        raise ValueError("phase 必须是 calibration、dev、holdout 或 validation")
    model = _text(manifest.get("canonical_model"), "canonical_model")
    labels = manifest.get("configurations")
    if not isinstance(labels, list) or not labels:
        raise ValueError("configurations 必须是非空列表")
    labels = [_text(label, "configuration") for label in labels]
    if len(set(labels)) != len(labels):
        raise ValueError("configuration 重复")
    baseline = _text(manifest.get("baseline"), "baseline")
    candidate = manifest.get("candidate")
    if baseline not in labels or candidate is not None and candidate not in labels:
        raise ValueError("baseline/candidate 必须属于 configurations")
    if candidate == baseline:
        raise ValueError("baseline 与 candidate 必须不同")
    repeats = _integer(manifest.get("repeats"), "repeats", minimum=1)
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks 必须是非空列表")
    task_repositories: dict[str, str] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("每道任务必须是对象")
        task_id = _text(task.get("task_id"), "task_id")
        if task_id in task_repositories:
            raise ValueError(f"任务重复：{task_id}")
        task_repositories[task_id] = _text(task.get("repository"), "repository")

    rows = list(records)
    indexed: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    outcomes: dict[tuple[str, str, int], bool | None] = {}
    raw_issues = manifest.get("validity_issues", [])
    if not isinstance(raw_issues, list) or any(not isinstance(issue, str) for issue in raw_issues):
        raise ValueError("validity_issues 必须是字符串列表")
    issues = list(raw_issues)
    fatal = fatal_stop_reason(rows)
    if fatal:
        issues.append(f"fatal_stop_condition:{fatal}")
    endpoints: Counter[str] = Counter()
    for row in rows:
        task_id = _text(row.get("task_id"), "task_id")
        label = _text(row.get("configuration"), "configuration")
        repeat = _integer(row.get("repeat"), "repeat", minimum=1)
        if task_id not in task_repositories or label not in labels or repeat > repeats:
            raise ValueError(f"试验不在清单中：{task_id}/{label}/{repeat}")
        key = (task_id, label, repeat)
        if key in indexed:
            raise ValueError(f"试验重复：{task_id}/{label}/{repeat}")
        indexed[key] = row
        status = _text(row.get("status"), "status")
        success = row.get("success")
        if success is not None and not isinstance(success, bool):
            raise ValueError("success 必须是 bool 或 null")
        outcome = success
        if success is True and (status != "completed" or row.get("verified") is not True):
            outcome = None
            issues.append(f"unverified_success:{task_id}/{label}/{repeat}")
        if success is False and status == "completed" and row.get("verified") is not True:
            outcome = None
            issues.append(f"unverified_grade:{task_id}/{label}/{repeat}")
        if status in {"running", "pending", "queued", "not_started", "blocked", "paused"}:
            outcome = None
            issues.append(f"unfinished_trial:{task_id}/{label}/{repeat}")
        outcomes[key] = outcome
        if row.get("canonical_model") != model:
            issues.append(f"model_mismatch:{task_id}/{label}/{repeat}")
        endpoint = row.get("endpoint")
        if isinstance(endpoint, str) and endpoint:
            endpoints[endpoint] += 1
        else:
            issues.append(f"missing_endpoint:{task_id}/{label}/{repeat}")

    expected = {
        (task_id, label, repeat)
        for task_id in task_repositories
        for label in labels
        for repeat in range(1, repeats + 1)
    }
    missing = sorted(expected - indexed.keys())
    if missing:
        issues.append("missing_trials")
    if any(value is None for value in outcomes.values()):
        issues.append("unknown_outcomes")
    if manifest.get("frozen") is not True:
        issues.append("manifest_not_frozen")
    if phase == "holdout" and len(labels) != 2:
        issues.append("holdout_requires_two_configurations")
    if phase == "validation" and (labels != [baseline] or candidate is not None):
        issues.append("validation_requires_only_baseline")

    endpoint_mismatches: list[dict[str, Any]] = []
    for task_id in task_repositories:
        for label in labels:
            if label == baseline:
                continue
            for repeat in range(1, repeats + 1):
                left = indexed.get((task_id, baseline, repeat))
                right = indexed.get((task_id, label, repeat))
                if left and right and left.get("endpoint") != right.get("endpoint"):
                    endpoint_mismatches.append(
                        {"task_id": task_id, "configuration": label, "repeat": repeat}
                    )
    if endpoint_mismatches:
        issues.append("paired_endpoint_mismatch")

    group_results: dict[str, Any] = {}
    rates: dict[str, dict[str, float | None]] = {}
    for label in labels:
        rows = [row for (_, name, _), row in indexed.items() if name == label]
        known = [
            value for (_, name, _), value in outcomes.items() if name == label and value is not None
        ]
        rates[label] = {}
        for task_id in task_repositories:
            values = [outcomes.get((task_id, label, repeat)) for repeat in range(1, repeats + 1)]
            rates[label][task_id] = (
                sum(value is True for value in values) / repeats
                if all(value is not None for value in values)
                else None
            )
        complete = all(value is not None for value in rates[label].values())
        group_results[label] = {
            "planned": len(task_repositories) * repeats,
            "recorded": len(rows),
            "judged": len(known),
            "successes": sum(value is True for value in known),
            "failures": sum(value is False for value in known),
            "unknown": len(rows) - len(known),
            "missing": len(task_repositories) * repeats - len(rows),
            "judged_attempt_rate": sum(known) / len(known) if known else None,
            "task_macro_success_rate": (
                statistics.mean(value for value in rates[label].values() if value is not None)
                if complete
                else None
            ),
            "status_counts": dict(Counter(str(row["status"]) for row in rows)),
            "resources": _resources(rows),
        }

    comparison: dict[str, Any] | None = None
    if candidate is not None:
        differences: dict[str, float] = {}
        for task_id in task_repositories:
            baseline_rate = rates[baseline][task_id]
            candidate_rate = rates[candidate][task_id]
            if baseline_rate is not None and candidate_rate is not None:
                differences[task_id] = candidate_rate - baseline_rate
        comparison = {
            "baseline": baseline,
            "candidate": candidate,
            "complete_tasks": len(differences),
            "task_differences": differences,
            "descriptive_delta": statistics.mean(differences.values()) if differences else None,
            "endpoint_mismatches": [
                {"task_id": item["task_id"], "repeat": item["repeat"]}
                for item in endpoint_mismatches
                if item["configuration"] == candidate
            ],
            "bootstrap": None,
        }
    elif phase == "holdout":
        issues.append("missing_comparison")

    eligible = phase == "holdout" and not issues
    if eligible and comparison is not None:
        comparison["bootstrap"] = paired_bootstrap(
            comparison["task_differences"], samples=bootstrap_samples, seed=seed
        )
    return {
        "schema_version": 1,
        "phase": phase,
        "canonical_model": model,
        "tasks": len(task_repositories),
        "repositories": len(set(task_repositories.values())),
        "repeats": repeats,
        "formal_comparison_eligible": eligible,
        "formal_validation_eligible": phase == "validation" and not issues,
        "final_result_eligible": phase in {"validation", "holdout"} and not issues,
        "conclusion_scope": "independent_validation"
        if phase == "validation"
        else "paired_comparison"
        if phase == "holdout"
        else "development_only",
        "validity_issues": sorted(set(issues)),
        "missing_trials": [
            {"task_id": task, "configuration": label, "repeat": repeat}
            for task, label, repeat in missing
        ],
        "endpoint_counts": dict(endpoints),
        "endpoint_mismatches": endpoint_mismatches,
        "groups": group_results,
        "task_success_rates": rates,
        "comparison": comparison,
        "cautions": [
            "若生成配对区间，按任务重抽样，不能将重复试验当成独立任务。",
            "公开任务可能被模型训练见过；本结果不证明不存在污染。",
            "小样本和同仓库相关性限制外推；区间不替代任务代表性。",
            "已报告 token 不等于完整请求账本或实际费用。",
        ],
    }


def select_development_candidate(
    manifest: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """只按开发集固定规则选择，缺数据时拒绝生成候选。"""
    if manifest.get("phase") != "dev":
        raise ValueError("候选选择只接受 dev")
    if len(manifest.get("configurations", [])) > 3:
        raise ValueError("开发阶段最多比较基线和两个候选")
    rows = list(records)
    result = analyze_experiment(manifest, rows)
    issues = [issue for issue in result["validity_issues"] if issue != "manifest_not_frozen"]
    if issues:
        return {"selected": None, "status": "incomplete", "validity_issues": issues}
    groups = result["groups"]
    best = max(group["task_macro_success_rate"] for group in groups.values())
    tied = [
        label
        for label in manifest["configurations"]
        if groups[label]["task_macro_success_rate"] == best
    ]
    complete_usage = all(
        group["resources"]["complete_usage_attempts"] == group["recorded"]
        for label, group in groups.items()
        if label in tied
    )
    if len(tied) > 1 and complete_usage:
        totals = {
            label: sum(
                group["resources"][field]["reported_sum"]
                for field in ("input_tokens", "output_tokens")
            )
            for label, group in groups.items()
            if label in tied
        }
        lowest = min(totals.values())
        tied = [label for label in tied if totals[label] == lowest]
    baseline = manifest["baseline"]
    selected = baseline if baseline in tied else tied[0]
    return {
        "selected": selected,
        "status": "selected",
        "dev_task_macro_success_rate": best,
        "token_tiebreak_available": complete_usage,
        "rule": "success_then_complete_reported_tokens_then_declared_order_with_baseline_priority",
    }


def main() -> None:
    from .artifacts import report_manifest

    parser = argparse.ArgumentParser(description="按预注册清单汇总 Agent 评测")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = report_manifest(
        json.loads(args.manifest.read_text(encoding="utf-8")), args.records.parent
    )
    records = [
        json.loads(line)
        for line in args.records.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = analyze_experiment(manifest, records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
