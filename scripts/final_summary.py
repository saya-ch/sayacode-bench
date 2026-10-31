"""最终汇总：计划分母、缺失分类、三口径与题级统计。

用法::

    uv run --no-sync python scripts/final_summary.py \\
        --root C:\\sb\\hard\\formal-240 \\
        --sample studies/sample-40-final.json \\
        --out C:\\sb\\hard\\formal-240\\FINAL-SUMMARY.json

口径：``planned`` 是冻结题集每题 × 计划重复数（默认 40×2=80），缺失按未通过计入；
``observed`` 只统计真正拿到 reward 或显式终态标记的 trial。禁止把 65 当 80 用。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sayacode_bench.formal import (  # noqa: E402
    missing_gap_report,
    summarize,
    write_summary,
)
from sayacode_bench.formal_stats import summarize_stats  # noqa: E402

DEFAULT_ROOT = Path(r"C:\sb\hard\formal-240")


def _fmt_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _print_table(summary: dict) -> None:
    print("=" * 96)
    print(
        f"三 agent 正式对比 · 计划 {summary['sample']['size']} 题 × "
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


def _print_gaps(summary: dict) -> None:
    gaps = missing_gap_report(summary)
    print("\n=== 缺口分类（共 %d 条）===" % gaps["total"])
    print(f"{'agent':<10}" + "".join(f"{name:>14}" for name in sorted(gaps["by_class"])))
    for agent, data in gaps["by_agent"].items():
        cells = "".join(f"{data['classes'].get(name, 0):>14}" for name in sorted(gaps["by_class"]))
        print(f"{agent:<10}{cells}")
    print(f"{'合计':<10}" + "".join(f"{gaps['by_class'][name]:>14}" for name in sorted(gaps["by_class"])))
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_FORMAL_ROOT", DEFAULT_ROOT)),
        help="结果根目录（含 sayacode/mini-swe/codex 子目录）",
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=ROOT / "studies" / "sample-40-final.json",
        help="冻结题集；计划分母只由它决定",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--agents", nargs="+", default=["sayacode", "mini-swe", "codex"])
    parser.add_argument("--faults", type=Path, default=None, help="默认读取 <root>/MODEL-FAULTS.json")
    parser.add_argument("--out", type=Path, default=None, help="默认写 <root>/FINAL-SUMMARY.json")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

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
    summary["stats"] = stats
    summary["gaps"] = missing_gap_report(summary)

    _print_table(summary)
    _print_gaps(summary)
    _print_stats(stats)

    if not args.no_write:
        out = args.out or args.root / "FINAL-SUMMARY.json"
        write_summary(out, summary)
        print(f"\n明细已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
