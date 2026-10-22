"""固定的绝对成功率区间与仓库簇敏感性分析，不重新判分或挑选有利区间。"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import sayacode_bench.analysis as analysis_module
import sayacode_bench.artifacts as artifacts_module
import sayacode_bench.budget as budget_module
import sayacode_bench.study as study_module
from sayacode_bench.analysis import paired_bootstrap
from sayacode_bench.artifacts import file_sha256, read_json, report_manifest, write_json

SAMPLES = 10_000
SEED = 20261022


def protocol_identity() -> dict[str, Any]:
    """在正式模型调用前保存此身份；函数不读取任务正文、答案或成绩。"""
    return {
        "schema_version": 1,
        "script_sha256": file_sha256(Path(__file__)),
        "analysis_sha256": file_sha256(Path(analysis_module.__file__)),
        "validity_rules_sha256": file_sha256(Path(artifacts_module.__file__)),
        "validation_sha256": file_sha256(Path(study_module.__file__)),
        "budget_sha256": file_sha256(Path(budget_module.__file__)),
        "samples": SAMPLES,
        "seed": SEED,
        "absolute_unit": "task mean across planned repeats; resample tasks",
        "cluster_unit": "whole repository; retain all tasks and their repeat means",
        "cluster_estimator": "task-macro delta with varying sampled cluster sizes",
        "role": "prespecified sensitivity; never replaces primary task bootstrap",
    }


def _cluster_bootstrap(
    differences: Mapping[str, float],
    repositories: Mapping[str, str],
    *,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """重抽整个仓库，按抽中的任务数归一；不把每仓库强行变成等大簇。"""
    if type(samples) is not int or samples < 100 or type(seed) is not int or seed < 0:
        raise ValueError("bootstrap 需要至少 100 次抽样与非负整数 seed")
    groups: dict[str, list[float]] = defaultdict(list)
    for task in sorted(differences):
        value = float(differences[task])
        if not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError("任务成功率差必须是 [-1,1] 内有限数")
        groups[repositories[task]].append(value)
    names = sorted(groups)
    task_count = sum(len(group) for group in groups.values())
    repo_means = {name: statistics.mean(groups[name]) for name in names}
    result: dict[str, Any] = {
        "method": "percentile_repository_cluster_bootstrap_task_macro",
        "tasks": task_count,
        "repositories": len(names),
        "cluster_sizes": {name: len(groups[name]) for name in names},
        "estimate": statistics.mean(differences.values()) if differences else None,
        "repository_equal_weight_delta": statistics.mean(repo_means.values()) if names else None,
        "repository_deltas": repo_means,
        "interval_95": None,
        "samples": samples,
        "seed": seed,
        "sampling_unit": "repository",
    }
    if len(names) < 2:
        result["interval_status"] = "unavailable_fewer_than_two_repositories"
        return result
    generator = random.Random(seed)
    estimates = []
    for _ in range(samples):
        sampled = generator.choices(names, k=len(names))
        values = [value for name in sampled for value in groups[name]]
        estimates.append(statistics.mean(values))
    # inclusive 分位数与主分析的 (n-1)*p 线性插值保持一致。
    quantiles = statistics.quantiles(estimates, n=40, method="inclusive")
    result["interval_95"] = [quantiles[0], quantiles[-1]]
    result["interval_status"] = "available"
    return result


def analyze_sensitivity(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """复用正式结果验证，描述值与满足最终条件的区间分别标明。"""
    samples, seed = SAMPLES, SEED
    # phase_summary 内部复用 analyze_experiment，并继承预算等已有正式资格检查。
    result = study_module.phase_summary(dict(manifest), list(records))
    task_repositories = {task["task_id"]: task["repository"] for task in manifest["tasks"]}
    eligible = result["final_result_eligible"] is True
    configurations = {}
    for label in manifest["configurations"]:
        raw_rates = result["task_success_rates"][label]
        rates = {task: value for task, value in raw_rates.items() if value is not None}
        by_repo: dict[str, list[float]] = defaultdict(list)
        planned_by_repo: dict[str, int] = defaultdict(int)
        for task, repo in task_repositories.items():
            planned_by_repo[repo] += 1
            if task in rates:
                by_repo[repo].append(rates[task])
        absolute = (
            paired_bootstrap(rates, samples=samples, seed=seed)
            if eligible
            else {
                "tasks": len(rates),
                "estimate": statistics.mean(rates.values()) if rates else None,
                "interval_95": None,
            }
        )
        absolute.update(
            method="percentile_task_bootstrap_absolute_success",
            sampling_unit="task",
            formal_interval_eligible=eligible and absolute["interval_95"] is not None,
            status="formal"
            if eligible and absolute["interval_95"] is not None
            else "descriptive_ineligible",
        )
        configurations[label] = {
            "planned_tasks": len(task_repositories),
            "complete_tasks": len(rates),
            "planned_repeats_per_task": result["repeats"],
            "observed_attempts": result["groups"][label]["recorded"],
            "task_macro_success_rate": result["groups"][label]["task_macro_success_rate"],
            "observed_complete_task_mean": statistics.mean(rates.values()) if rates else None,
            "absolute_success_bootstrap": absolute,
            "repositories": {
                repo: {
                    "planned_tasks": planned_by_repo[repo],
                    "complete_tasks": len(by_repo[repo]),
                    "task_macro_success_rate": statistics.mean(by_repo[repo])
                    if len(by_repo[repo]) == planned_by_repo[repo]
                    else None,
                    "observed_complete_task_mean": statistics.mean(by_repo[repo])
                    if by_repo[repo]
                    else None,
                }
                for repo in sorted(planned_by_repo)
            },
        }
    comparison = result["comparison"]
    sensitivity = None
    if comparison is not None:
        differences = comparison["task_differences"]
        paired_eligible = result["formal_comparison_eligible"] is True
        if paired_eligible:
            sensitivity = _cluster_bootstrap(
                differences, task_repositories, samples=samples, seed=seed
            )
        else:
            groups: dict[str, list[float]] = defaultdict(list)
            for task, difference in differences.items():
                groups[task_repositories[task]].append(difference)
            sensitivity = {
                "tasks": len(differences),
                "repositories": len(groups),
                "estimate": comparison["descriptive_delta"],
                "repository_equal_weight_delta": statistics.mean(
                    statistics.mean(group) for group in groups.values()
                )
                if groups
                else None,
                "repository_deltas": {
                    repo: statistics.mean(group) for repo, group in sorted(groups.items())
                },
                "interval_95": None,
                "interval_status": "descriptive_ineligible",
            }
        sensitivity.update(
            role="sensitivity_not_primary",
            formal_interval_eligible=paired_eligible and sensitivity["interval_95"] is not None,
            status="formal_sensitivity"
            if paired_eligible and sensitivity["interval_95"] is not None
            else "descriptive_ineligible",
        )
    return {
        "schema_version": 1,
        "protocol": protocol_identity(),
        "parameters": {"samples": samples, "seed": seed},
        "phase": result["phase"],
        "tasks": result["tasks"],
        "repositories": result["repositories"],
        "repeats": result["repeats"],
        "final_result_eligible": eligible,
        "status": "formal" if eligible else "descriptive_ineligible",
        "validity_issues": result["validity_issues"],
        "missing_trials": result["missing_trials"],
        "configurations": configurations,
        "primary_task_difference_bootstrap": comparison["bootstrap"]
        if comparison and result["formal_comparison_eligible"] is True
        else None,
        "paired_repository_sensitivity": sensitivity,
        "cautions": [
            "任务与仓库数来自冻结的公开元数据；重复试验不增加独立任务或仓库数。",
            "仓库簇敏感性不能替换主任务区间，不能按显著与否挑选报告。",
            "11 个仓库簇仍少；24 道任务不足以支持可靠的 2–5 个百分点细微收益结论。",
            "bootstrap 反映观察样本与已跑重复的变异，不认证无污染、外部代表性或执行环境正确。",
            "全成全败时经验 bootstrap 可退化为零宽区间，不表示总体成功概率没有不确定性。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--freeze-protocol", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.freeze_protocol:
        if args.manifest is not None or args.records is not None:
            parser.error("协议冻结不读取 manifest 或成绩")
        value = protocol_identity()
    else:
        if args.manifest is None or args.records is None:
            parser.error("分析需要 --manifest 和 --records")
        manifest = report_manifest(read_json(args.manifest), args.records.parent)
        records = [
            json.loads(line)
            for line in args.records.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        value = analyze_sensitivity(manifest, records)
        value["inputs"] = {
            "manifest_sha256": file_sha256(args.manifest),
            "records_sha256": file_sha256(args.records),
        }
    write_json(args.output, value, exclusive=True)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "script_sha256": value.get(
                    "script_sha256", value.get("protocol", {}).get("script_sha256")
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
