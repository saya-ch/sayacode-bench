"""指标口径 lint：检查 ``FINAL-SUMMARY.json``（含 ``final_stats`` 段）是否口径自洽。

规则：

- 各 agent 的 planned 分母必须相同（检测「三套分母」）；planned = 题数 × 重复；
- observed ≤ planned，且 observed + missing = planned；
- totals 与各 agent 求和一致；
- 缺失分类只允许固定集合；
- McNemar 必须是**题级**：存在 ``common_tasks`` 等配对题数，二值定义明确为
  ``all_repeats_pass``/``any_repeat_pass``，不是 best-of-2 冒充 pass@1；
- pass@2 / pass^2 必须是独立结构，不能被当成 pass@1。

有 issue 时返回非零（门禁）；v2 数据应通过。

用法::

    uv run --no-sync python scripts/lint_metrics.py --summary C:\\sb\\hard\\v2-325\\FINAL-SUMMARY.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile_results import ALLOWED_MISSING  # noqa: E402

MCNEMAR_DEFINITIONS = {"all_repeats_pass", "any_repeat_pass"}


@dataclass(frozen=True)
class Issue:
    code: str
    agent: str
    subject: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "agent": self.agent,
            "subject": self.subject,
            "message": self.message,
        }


def _sample_size(summary: dict[str, Any]) -> int | None:
    size = (summary.get("sample") or {}).get("size")
    return size if isinstance(size, int) and size > 0 else None


def _check_denominators(
    summary: dict[str, Any], agents: dict[str, Any], issues: list[Issue]
) -> None:
    repeats = summary.get("repeats")
    size = _sample_size(summary)
    expected = size * repeats if size and isinstance(repeats, int) else None
    planned_values = {
        agent: data.get("planned") for agent, data in agents.items() if isinstance(data, dict)
    }
    distinct = {value for value in planned_values.values() if isinstance(value, int)}
    if len(distinct) > 1:
        issues.append(
            Issue(
                "denominator_split",
                "*",
                "planned",
                "各 agent planned 不一致（三套分母特征）："
                + "、".join(f"{agent}={value}" for agent, value in planned_values.items()),
            )
        )
    for agent, planned in planned_values.items():
        if expected is not None and planned != expected:
            issues.append(
                Issue(
                    "planned_not_task_times_repeat",
                    agent,
                    "planned",
                    f"planned={planned}，应等于 题数({size})×重复({repeats})={expected}",
                )
            )
        data = agents[agent]
        observed, missing = data.get("observed"), data.get("missing")
        if isinstance(planned, int) and isinstance(observed, int):
            if observed > planned:
                issues.append(
                    Issue(
                        "observed_exceeds_planned",
                        agent,
                        "observed",
                        f"observed={observed} > planned={planned}",
                    )
                )
            if isinstance(missing, int) and observed + missing != planned:
                issues.append(
                    Issue(
                        "observed_plus_missing",
                        agent,
                        "observed/missing",
                        f"observed({observed}) + missing({missing}) != planned({planned})",
                    )
                )
        for entry in data.get("missing_trials", []):
            if isinstance(entry, dict) and entry.get("class") not in ALLOWED_MISSING:
                issues.append(
                    Issue(
                        "missing_class_invalid",
                        agent,
                        str(entry.get("job") or entry.get("task_id")),
                        f"允许集合外的缺失分类：{entry.get('class')}",
                    )
                )


def _check_totals(summary: dict[str, Any], agents: dict[str, Any], issues: list[Issue]) -> None:
    totals = summary.get("totals")
    if not isinstance(totals, dict):
        return
    expected = {
        "planned": sum(
            int(data["planned"]) for data in agents.values() if isinstance(data.get("planned"), int)
        ),
        "observed": sum(
            int(data["observed"])
            for data in agents.values()
            if isinstance(data.get("observed"), int)
        ),
        "passes": sum(
            int(data["passes"]) for data in agents.values() if isinstance(data.get("passes"), int)
        ),
        "missing": sum(
            int(data["missing"]) for data in agents.values() if isinstance(data.get("missing"), int)
        ),
    }
    for key, value in expected.items():
        if isinstance(totals.get(key), int) and totals[key] != value:
            issues.append(
                Issue("totals_mismatch", "*", key, f"totals.{key}={totals[key]}，求和={value}")
            )


def _check_mcnemar(summary: dict[str, Any], issues: list[Issue]) -> None:
    stats = summary.get("stats")
    if not isinstance(stats, dict):
        issues.append(Issue("stats_missing", "*", "stats", "缺少 final_stats 段，无法核对 McNemar"))
        return
    pairwise = stats.get("pairwise")
    if not isinstance(pairwise, dict) or not pairwise:
        issues.append(Issue("mcnemar_missing", "*", "stats.pairwise", "缺少两两配对统计"))
        return
    for name, pair in pairwise.items():
        if not isinstance(pair, dict):
            issues.append(Issue("mcnemar_not_task_level", "*", name, "pair 不是对象"))
            continue
        common = pair.get("common_tasks")
        if not isinstance(common, int) or common <= 0:
            issues.append(
                Issue(
                    "mcnemar_not_task_level",
                    "*",
                    name,
                    "缺少配对题数 common_tasks（可能是 trial 级 best-of-2）",
                )
            )
        for key in ("mcnemar_all_repeats_pass", "mcnemar_any_repeat_pass"):
            entry = pair.get(key)
            if not isinstance(entry, dict):
                issues.append(
                    Issue("mcnemar_not_task_level", "*", f"{name}.{key}", "缺少题级 McNemar 结果")
                )
                continue
            if entry.get("definition") not in MCNEMAR_DEFINITIONS:
                issues.append(
                    Issue(
                        "mcnemar_definition",
                        "*",
                        f"{name}.{key}",
                        f"二值定义未标注题级语义：{entry.get('definition')}",
                    )
                )
            if isinstance(common, int) and entry.get("common_tasks") != common:
                issues.append(
                    Issue(
                        "mcnemar_common_tasks_mismatch",
                        "*",
                        f"{name}.{key}",
                        f"McNemar common_tasks={entry.get('common_tasks')} 与 pair={common} 不一致",
                    )
                )


def _check_pass_at_k(summary: dict[str, Any], issues: list[Issue]) -> None:
    agents_stats = (summary.get("stats") or {}).get("agents")
    if not isinstance(agents_stats, dict):
        return
    for agent, data in agents_stats.items():
        pass_at_k = data.get("pass_at_k") if isinstance(data, dict) else None
        if not isinstance(pass_at_k, dict):
            issues.append(Issue("pass_at_k_shape", agent, "pass_at_k", "缺少 pass@k 结构"))
            continue
        if "status" in pass_at_k:
            continue  # 单重复时明确 unavailable
        for key in ("pass_at_2", "pass_pow_2"):
            entry = pass_at_k.get(key)
            if not isinstance(entry, dict) or not entry.get("definition"):
                issues.append(
                    Issue(
                        "pass_at_k_shape",
                        agent,
                        f"pass_at_k.{key}",
                        "缺少独立结构与定义，可能被当成 pass@1",
                    )
                )
                continue
            definition = str(entry.get("definition"))
            if "pass@1" in definition.lower() or "best" in definition.lower():
                issues.append(
                    Issue(
                        "pass_at_k_confused",
                        agent,
                        f"pass_at_k.{key}",
                        f"定义混入 pass@1/best-of：{definition}",
                    )
                )


def lint_summary(summary: dict[str, Any], *, sample_size: int | None = None) -> list[Issue]:
    issues: list[Issue] = []
    agents = summary.get("agents")
    if not isinstance(agents, dict) or not agents:
        return [Issue("agents_missing", "*", "summary", "缺少 agents")]
    if sample_size is not None and isinstance(summary.get("sample"), dict):
        summary = {**summary, "sample": {**summary["sample"], "size": sample_size}}
    _check_denominators(summary, agents, issues)
    _check_totals(summary, agents, issues)
    _check_mcnemar(summary, issues)
    _check_pass_at_k(summary, issues)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"[错误] 找不到汇总文件：{args.summary}", file=sys.stderr)
        return 2
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[错误] 汇总文件不可读：{exc}", file=sys.stderr)
        return 2
    if not isinstance(summary, dict):
        print("[错误] 汇总文件必须是 JSON 对象", file=sys.stderr)
        return 2

    issues = lint_summary(summary)
    print(f"[lint] summary={args.summary}")
    if not issues:
        print("  结论：口径自洽（0 个问题）")
    else:
        print(f"  发现 {len(issues)} 个问题：")
        for issue in issues:
            print(f"  - [{issue.code}] {issue.agent}/{issue.subject}: {issue.message}")

    payload = {
        "schema_version": 1,
        "summary": str(args.summary),
        "issue_count": len(issues),
        "issues": [issue.as_dict() for issue in issues],
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[json] 已写 {args.json_out}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
