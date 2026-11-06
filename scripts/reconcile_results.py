"""对账：校验 ``FINAL-SUMMARY.json`` 与磁盘 job / reward / 分母 / 缺失分类是否一致。

检查项：

- 每条实际 trial 的 ``<agent>/jobs/<job>``（或 verify 目录）存在；否则报 ``no_job``；
- 有 reward 的 trial，其 reward 与 ``<trial>/verifier/reward.txt`` 一致（trial 目录按内容识别）；
- planned 分母 = 题数 × 重复（每个 agent），且各 agent 相同；
- 缺失分类只允许 ``{no_job, empty_patch, timeout, model_fault, unverified, infra}``；
- 缺失分类与磁盘事实一致：``no_job`` 不应有目录，``empty_patch`` 等应有目录。

默认只报告并返回 0；``--strict`` 在有 issue 时非零退出。``--dry-run`` 不写 JSON。

用法::

    uv run --no-sync python scripts/reconcile_results.py --root C:\\sb\\hard\\v2-325 --dry-run
    uv run --no-sync python scripts/reconcile_results.py --root <root> --strict --json-out <path>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sayacode_bench import trialdir

ALLOWED_MISSING = {"no_job", "empty_patch", "timeout", "model_fault", "unverified", "infra"}
DEFAULT_ROOT = Path(r"C:\sb\hard\v2-325")


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


def planned_job_name(agent: str, task_id: str, repeat: int) -> str:
    short = task_id[len("instance_") :] if task_id.startswith("instance_") else task_id
    return f"{agent}-{short[:34]}-r{repeat}"


def job_dirs(root: Path, agent: str, job: str) -> list[Path]:
    candidates = [root / agent / "jobs" / job, root / agent / "verify" / "jobs" / f"verify-{job}"]
    return [path for path in candidates if path.is_dir()]


def read_reward(job_dir: Path) -> float | None:
    reward = trialdir.find_trial_file(job_dir, *trialdir.REWARD_PARTS)
    if reward is None:
        return None
    try:
        return float(reward.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("FINAL-SUMMARY 必须是 JSON 对象")
    return payload


def resolve_sample_size(root: Path, summary: dict[str, Any], sample: Path | None) -> int | None:
    declared = (summary.get("sample") or {}).get("size")
    if isinstance(declared, int) and declared > 0:
        return declared
    candidates: list[Path] = []
    if sample is not None:
        candidates.append(sample)
    sample_path = (summary.get("sample") or {}).get("path")
    if isinstance(sample_path, str) and sample_path:
        candidates.append(Path(sample_path))
    for candidate in candidates:
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if isinstance(tasks, list) and tasks:
                return len(tasks)
    return None


def reconcile_root(
    root: Path,
    summary: dict[str, Any],
    *,
    sample_size: int | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    repeats = summary.get("repeats")
    if not isinstance(repeats, int) or repeats < 1:
        issues.append(Issue("repeats_invalid", "*", "summary", f"repeats={repeats}"))
        repeats = None
    agents = summary.get("agents")
    if not isinstance(agents, dict) or not agents:
        issues.append(Issue("agents_missing", "*", "summary", "缺少 agents"))
        return issues

    if sample_size is None:
        sample_size = resolve_sample_size(root, summary, None)
        if sample_size is None:
            issues.append(
                Issue("sample_size_unknown", "*", "summary", "无法确定题数，无法核对 planned 分母")
            )
    expected_planned = sample_size * repeats if sample_size and repeats else None

    planned_values: dict[str, int | None] = {}
    observed_total = passes_total = 0
    missing_total = 0
    for agent, data in agents.items():
        planned = data.get("planned") if isinstance(data, dict) else None
        observed = data.get("observed")
        missing = data.get("missing")
        planned_values[agent] = planned if isinstance(planned, int) else None
        if isinstance(observed, int):
            observed_total += observed
        if isinstance(data.get("passes"), int):
            passes_total += int(data["passes"])
        if isinstance(missing, int):
            missing_total += missing

        if expected_planned is not None and planned != expected_planned:
            issues.append(
                Issue(
                    "planned_denominator",
                    agent,
                    "planned",
                    f"planned={planned}，应为 题数×重复={expected_planned}",
                )
            )
        if isinstance(planned, int) and isinstance(observed, int) and observed > planned:
            issues.append(
                Issue(
                    "observed_exceeds_planned",
                    agent,
                    "observed",
                    f"observed={observed} > planned={planned}",
                )
            )
        if isinstance(planned, int) and isinstance(observed, int) and isinstance(missing, int):
            if observed + missing != planned:
                issues.append(
                    Issue(
                        "observed_plus_missing",
                        agent,
                        "observed/missing",
                        f"observed({observed}) + missing({missing}) != planned({planned})",
                    )
                )

        for trial in data.get("trials", []):
            if not isinstance(trial, dict) or not trial.get("job") or not trial.get("kind"):
                continue
            job = str(trial["job"])
            dirs = job_dirs(root, agent, job)
            if not dirs:
                issues.append(Issue("no_job", agent, job, "trial 的 job 目录不存在"))
                continue
            reward = trial.get("reward")
            if reward is not None:
                # native 目录可能只有 patch（无 reward），真正的 reward 在 verify 目录；
                # 依次查找第一个带 reward.txt 的目录，避免把 verify 合并的 trial 误报。
                disk_reward = next(
                    (value for value in (read_reward(path) for path in dirs) if value is not None),
                    None,
                )
                if disk_reward is None:
                    issues.append(
                        Issue(
                            "reward_unverifiable",
                            agent,
                            job,
                            "summary 有 reward 但磁盘无 reward.txt",
                        )
                    )
                elif abs(float(disk_reward) - float(reward)) > 1e-9:
                    issues.append(
                        Issue(
                            "reward_mismatch",
                            agent,
                            job,
                            f"summary reward={reward}，磁盘 reward={disk_reward}",
                        )
                    )

        for missing_entry in data.get("missing_trials", []):
            if not isinstance(missing_entry, dict):
                continue
            missing_class = missing_entry.get("class")
            task_id = str(missing_entry.get("task_id") or "")
            repeat = missing_entry.get("repeat")
            job = missing_entry.get("job")
            subject = str(job or f"{task_id}@r{repeat}")
            if missing_class not in ALLOWED_MISSING:
                issues.append(
                    Issue(
                        "missing_class_invalid",
                        agent,
                        subject,
                        f"允许集合外的缺失分类：{missing_class}",
                    )
                )
                continue
            inferred = (
                str(job)
                if job
                else (
                    planned_job_name(agent, task_id, int(repeat))
                    if task_id and isinstance(repeat, int)
                    else ""
                )
            )
            dirs = job_dirs(root, agent, inferred) if inferred else []
            if missing_class == "no_job" and dirs:
                issues.append(
                    Issue(
                        "missing_job_inconsistent",
                        agent,
                        subject,
                        "class=no_job 但磁盘存在 job 目录",
                    )
                )
            elif missing_class != "no_job" and not dirs:
                issues.append(
                    Issue(
                        "missing_job_inconsistent",
                        agent,
                        subject,
                        f"class={missing_class} 但磁盘找不到 job 目录",
                    )
                )

    distinct_planned = {value for value in planned_values.values() if value is not None}
    if len(distinct_planned) > 1:
        issues.append(
            Issue(
                "denominator_split",
                "*",
                "planned",
                "各 agent planned 分母不同（三套分母特征）："
                + "、".join(f"{agent}={value}" for agent, value in planned_values.items()),
            )
        )

    totals = summary.get("totals")
    if isinstance(totals, dict):
        expected = {
            "planned": sum(value for value in planned_values.values() if value is not None),
            "observed": observed_total,
            "passes": passes_total,
            "missing": missing_total,
        }
        for key, value in expected.items():
            if isinstance(totals.get(key), int) and totals[key] != value:
                issues.append(
                    Issue(
                        "totals_mismatch",
                        "*",
                        key,
                        f"totals.{key}={totals[key]}，按 agents 求和={value}",
                    )
                )
    return issues


def _print(issues: list[Issue], root: Path) -> None:
    print(f"[reconcile] root={root}")
    if not issues:
        print("  结论：一致（0 个不一致项）")
        return
    print(f"  发现 {len(issues)} 个不一致项：")
    for issue in issues:
        print(f"  - [{issue.code}] {issue.agent}/{issue.subject}: {issue.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_FORMAL_ROOT", DEFAULT_ROOT)),
    )
    parser.add_argument("--summary", type=Path, default=None, help="默认 <root>/FINAL-SUMMARY.json")
    parser.add_argument("--sample", type=Path, default=None, help="冻结题集，用于核对 planned 分母")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写 JSON")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", help="有 issue 时非零退出")
    args = parser.parse_args(argv)

    summary_path = args.summary or (args.root / "FINAL-SUMMARY.json")
    if not summary_path.is_file():
        print(f"[错误] 找不到汇总文件：{summary_path}", file=sys.stderr)
        return 2
    try:
        summary = _load_json(summary_path)
    except (OSError, ValueError) as exc:
        print(f"[错误] 汇总文件不可读：{exc}", file=sys.stderr)
        return 2
    sample_size = resolve_sample_size(args.root, summary, args.sample)
    issues = reconcile_root(args.root, summary, sample_size=sample_size)
    _print(issues, args.root)

    payload = {
        "schema_version": 1,
        "root": str(args.root),
        "summary": str(summary_path),
        "sample_size": sample_size,
        "issue_count": len(issues),
        "issues": [issue.as_dict() for issue in issues],
    }
    if args.json_out is not None and not args.dry_run:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[json] 已写 {args.json_out}")
    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
