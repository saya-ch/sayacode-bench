"""从原始产物重建 RESULTS-LEDGER 的主表：planned / observed / partial / 题级统计。

默认根是当前主力批次 ``C:\\sb\\hard\\v2-325``（四组：sayacode / mini-swe / claude-code / opencode）。
**v4-327 批次必须显式传 ``--root``**（默认只覆盖 v2-325；两批不可合并排名，见 RESULTS-LEDGER §2.3）。

重建 ledger 主表的完整命令::

    uv run --no-sync python scripts/final_summary.py \\
        --root C:\\sb\\hard\\v2-325 \\
        --agents sayacode mini-swe claude-code opencode \\
        --out C:\\sb\\bp-tmp\\rebuild-v2.json

    # 3.2.7 批次（只跑 sayacode）
    uv run --no-sync python scripts/final_summary.py \\
        --root C:\\sb\\hard\\v4-327 --agents sayacode --out C:\\sb\\bp-tmp\\rebuild-v4.json

口径：``planned`` 是冻结题集每题 × 计划重复数（默认 40×2=80），缺失按未通过计入；
``observed`` 只统计真正拿到 reward 或显式终态标记的 trial；``partial`` 从
``verifier/output.json`` 的 required 测试通过比例汇总（与 RESULTS-LEDGER §2 同源），
不取 ``trials[].partial``（该字段按 test-stdout 解析、覆盖不全，仅作参考）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sayacode_bench import trialdir  # noqa: E402
from sayacode_bench.formal import (  # noqa: E402
    missing_gap_report,
    summarize,
    write_summary,
)
from sayacode_bench.formal_stats import summarize_stats  # noqa: E402

DEFAULT_ROOT = Path(r"C:\sb\hard\v2-325")
DEFAULT_AGENTS = ["sayacode", "mini-swe", "claude-code", "opencode"]


def _fmt_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _print_table(summary: dict) -> None:
    print("=" * 96)
    print(
        f"批次汇总（{len(summary['agents'])} 组 agent）· 计划 {summary['sample']['size']} 题 × "
        f"{summary['repeats']} 重复 = {summary['sample']['size'] * summary['repeats']} trial/agent"
    )
    print("=" * 96)
    header = (
        f"{'agent':<10}{'planned':>9}{'observed':>10}{'pass':>7}"
        f"{'planned%':>11}{'observed%':>12}{'worst':>9}{'best':>9}"
    )
    print(header)
    for agent, data in summary["agents"].items():
        rates = data["rates"]
        print(
            f"{agent:<10}{data['planned']:>9}{data['observed']:>10}{data['passes']:>7}"
            f"{_fmt_rate(rates['planned_pass_rate']):>11}"
            f"{_fmt_rate(rates['observed_pass_rate']):>12}"
            f"{_fmt_rate(rates['worst_bound']):>9}"
            f"{_fmt_rate(rates['best_bound']):>9}"
        )


def _partial_from_output(path: Path) -> float | None:
    """required 测试通过比例；output.json 缺失或无 tests 时返回 None。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tests = payload.get("tests") if isinstance(payload, dict) else None
    if not isinstance(tests, list) or not tests:
        return None
    passed = sum(
        1
        for test in tests
        if isinstance(test, dict) and str(test.get("status", "")).upper() == "PASSED"
    )
    return passed / len(tests)


AGENT_PREFIXES = ("sayacode", "mini-swe", "claude-code", "opencode", "codex")


def _job_meta(name: str) -> tuple[str, int] | None:
    """job 名 → (task stem, repeat)；与 build_analysis_dataset 同口径。"""
    match = re.search(r"-r(\d+)$", name)
    if not match:
        return None
    stem = name[: match.start()]
    if stem.startswith("verify-"):
        stem = stem[len("verify-") :]
    for prefix in AGENT_PREFIXES:
        if stem.startswith(prefix + "-"):
            stem = stem[len(prefix) + 1 :]
            break
    return stem, int(match.group(1))


def partial_summary(root: Path, agents: list[str]) -> dict:
    """按 ``verifier/output.json`` 汇总 partial（trial 级均值 + 题级均值）。

    与 RESULTS-LEDGER §2 同源：直接扫描 ``<root>/<agent>/{jobs,verify/jobs}/*``，
    优先 native、缺失时回退 verify（SAYACODE 的 output.json 只在 verify 阶段产生）。
    不读取 ``trials[].partial``——那个字段按 test-stdout 解析、覆盖不全（ledger §5.1）。
    """
    out: dict[str, dict] = {}
    for agent in agents:
        seen: set[tuple[str, int]] = set()
        by_task: dict[str, list[float]] = defaultdict(list)
        for base in (root / agent / "jobs", root / agent / "verify" / "jobs"):
            if not base.is_dir():
                continue
            for job in sorted(base.iterdir()):
                if not job.is_dir():
                    continue
                meta = _job_meta(job.name)
                if meta is None or meta in seen:
                    continue
                inner = trialdir.find_trial_dir(job)
                if inner is None:
                    continue
                value = _partial_from_output(inner / "verifier" / "output.json")
                if value is None:
                    continue
                seen.add(meta)
                by_task[meta[0]].append(value)
        values = [item for items in by_task.values() for item in items]
        task_means = [statistics.mean(items) for items in by_task.values()]
        out[agent] = {
            "source": "verifier/output.json",
            "n": len(values),
            "trial_mean": statistics.mean(values) if values else None,
            "task_n": len(task_means),
            "task_mean": statistics.mean(task_means) if task_means else None,
        }
    return out


def _print_partial(partial: dict) -> None:
    print("\n=== partial（verifier/output.json，required 测试通过比例；与 ledger §2 同源）===")
    print(f"{'agent':<12}{'n':>5}{'trial级':>10}{'题级':>10}{'题数':>6}")
    for agent, data in partial.items():
        print(
            f"{agent:<12}{data['n']:>5}{_fmt_rate(data['trial_mean']):>10}"
            f"{_fmt_rate(data['task_mean']):>10}{data['task_n']:>6}"
        )


def _print_gaps(summary: dict) -> None:
    gaps = missing_gap_report(summary)
    print("\n=== 缺口分类（共 %d 条）===" % gaps["total"])
    print(f"{'agent':<10}" + "".join(f"{name:>14}" for name in sorted(gaps["by_class"])))
    for agent, data in gaps["by_agent"].items():
        cells = "".join(f"{data['classes'].get(name, 0):>14}" for name in sorted(gaps["by_class"]))
        print(f"{agent:<10}{cells}")
    print(
        f"{'合计':<10}"
        + "".join(f"{gaps['by_class'][name]:>14}" for name in sorted(gaps["by_class"]))
    )
    print("\n缺失明细：")
    for agent, data in summary["agents"].items():
        for item in data["missing_trials"]:
            print(
                f"  [{agent}] {item['class']:<11} {item['task'][:52]:<52} "
                f"r{item['repeat']}  {item['detail']}"
            )
    accounting = summary.get("fault_accounting") or []
    if accounting:
        print("\nMODEL-FAULTS 归因落点：")
        for item in accounting:
            print(
                f"  [{item['agent']}] {item['job']}  faults={','.join(item['faults'])} "
                f"-> {item['outcome']}"
            )


def _print_stats(stats: dict) -> None:
    print("\n=== 题级统计（任务块为独立单位，重复不增加样本量）===")
    for agent, data in stats["agents"].items():
        macro = data["task_macro"]
        boot = data["task_block_bootstrap"]
        wilson = data["wilson_task_level"]
        interval = boot.get("interval_95")
        text = "—" if interval is None else f"[{interval[0]:.1%}, {interval[1]:.1%}]"
        print(
            f"  {agent:<10} 完整题 {macro['complete_tasks']:>2}/{macro['planned_tasks']:<2} "
            f"task-macro={_fmt_rate(macro['mean'])}  bootstrap95={text}"
        )
        print(
            f"  {'':<10} 题级全通过 {wilson['k']}/{wilson['n']} = {_fmt_rate(wilson['rate'])} "
            f"Wilson={_fmt_rate(wilson['interval_95'][0] if wilson['interval_95'] else None)}"
            f"–{_fmt_rate(wilson['interval_95'][1] if wilson['interval_95'] else None)}"
        )
        pass_at = data["pass_at_k"]
        if "pass_at_2" in pass_at:
            any_pass = pass_at["pass_at_2"]
            all_pass = pass_at["pass_pow_2"]
            print(
                f"  {'':<10} pass@2={any_pass['successes']}/{pass_at['tasks']}="
                f"{_fmt_rate(any_pass['rate'])}  pass^2={all_pass['successes']}/{pass_at['tasks']}="
                f"{_fmt_rate(all_pass['rate'])}"
            )
    print("\n=== 两两配对（题级，非 best-of-2 冒充 pass@1）===")
    for name, data in stats["pairwise"].items():
        mcnemar = data["mcnemar_all_repeats_pass"]
        print(
            f"  {data['a']} vs {data['b']}：共同题 {data['common_tasks']}，"
            f"delta={_fmt_rate(data['task_macro_delta'])}，"
            f"全通过 McNemar a独过 {mcnemar['a_only']} / b独过 {mcnemar['b_only']} "
            f"p={mcnemar['p_value']:.3f}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例（从原始产物重建 ledger 主表）：\n"
            "  uv run --no-sync python scripts/final_summary.py --root C:\\sb\\hard\\v2-325 "
            "--out C:\\sb\\bp-tmp\\rebuild-v2.json\n"
            "  uv run --no-sync python scripts/final_summary.py --root C:\\sb\\hard\\v4-327 "
            "--agents sayacode --out C:\\sb\\bp-tmp\\rebuild-v4.json\n"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_FORMAL_ROOT", DEFAULT_ROOT)),
        help="结果根目录；默认 v2-325。v4-327 批次请显式传 --root（两批不可合并排名）",
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=ROOT / "studies" / "sample-40-final.json",
        help="冻结题集；计划分母只由它决定",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(DEFAULT_AGENTS),
        help="默认四组 sayacode mini-swe claude-code opencode；codex 组已作废，仅历史复现时显式传",
    )
    parser.add_argument(
        "--faults", type=Path, default=None, help="默认读取 <root>/MODEL-FAULTS.json"
    )
    parser.add_argument("--out", type=Path, default=None, help="默认写 <root>/FINAL-SUMMARY.json")
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        parser.error(f"结果根目录不存在：{args.root}；用 --root 或 SAYACODE_BENCH_FORMAL_ROOT 指定")
    if not args.sample.is_file():
        parser.error(f"题集不存在：{args.sample}")

    summary = summarize(
        args.root,
        sample=args.sample,
        repeats=args.repeats,
        agents=args.agents,
        faults_path=args.faults,
    )
    stats = summarize_stats(summary)
    partial = partial_summary(args.root, args.agents)
    summary["stats"] = stats
    summary["partial"] = partial
    summary["gaps"] = missing_gap_report(summary)

    _print_table(summary)
    _print_partial(partial)
    _print_gaps(summary)
    _print_stats(stats)

    if not args.no_write:
        out = args.out or args.root / "FINAL-SUMMARY.json"
        write_summary(out, summary)
        print(f"\n明细已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
