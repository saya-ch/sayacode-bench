"""同题配对比较：两个 FINAL-SUMMARY 的 agent 结果做 trial 级 McNemar + 题块 bootstrap。

用于 RESULTS-LEDGER §3.2「3.2.7 vs 3.2.5（78 个配对 trial）」这类**同一题 × 同一 repeat** 的配对，
只应在同一批次族内使用；跨批次（v2-325 vs v4-327）的配对受制品/时间/served 混杂，结论仅描述。

统计复用仓库既有实现，不重写：
- McNemar 精确检验：``scripts/compare_trials.py:binom_two_sided_p``
- 题块 bootstrap：``sayacode_bench.analysis.paired_bootstrap``（10000 次、seed=20261022）

用法::

    uv run --no-sync python scripts/paired_compare.py \\
        --old C:\\sb\\hard\\v2-325\\FINAL-SUMMARY-V4.json \\
        --new C:\\sb\\hard\\v4-327\\FINAL-SUMMARY-327.json \\
        --out C:\\sb\\bp-tmp\\paired-325-327.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from compare_trials import binom_two_sided_p  # noqa: E402

from sayacode_bench.analysis import paired_bootstrap  # noqa: E402

SAMPLES = 10_000
SEED = 20261022
DEFAULT_OLD = Path(r"C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json")
DEFAULT_NEW = Path(r"C:\sb\hard\v4-327\FINAL-SUMMARY-327.json")


def load_trials(path: Path, agent: str) -> dict[tuple[str, int], bool]:
    """返回 {(task, repeat): pass}，只保留有 effective_reward 的 trial。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    agents = payload.get("agents")
    if not isinstance(agents, dict) or agent not in agents:
        raise ValueError(f"{path} 中找不到 agent={agent}")
    out: dict[tuple[str, int], bool] = {}
    for trial in agents[agent].get("trials", []):
        if not isinstance(trial, dict):
            continue
        effective = trial.get("effective_reward")
        if effective is None:
            continue
        task = trial.get("task_id") or trial.get("task")
        repeat = trial.get("repeat")
        if not isinstance(task, str) or not isinstance(repeat, int):
            continue
        out[(task, repeat)] = float(effective) == 1.0
    return out


def compare(
    old: dict[tuple[str, int], bool],
    new: dict[tuple[str, int], bool],
    *,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    keys = sorted(set(old) & set(new))
    if not keys:
        raise ValueError("没有可配对的 trial")
    both = old_only = new_only = neither = 0
    per_task: dict[str, list[float]] = {}
    flips: list[dict[str, Any]] = []
    for key in keys:
        a, b = old[key], new[key]
        if a and b:
            both += 1
        elif a:
            old_only += 1
        elif b:
            new_only += 1
        else:
            neither += 1
        if a != b:
            flips.append({"task_id": key[0], "repeat": key[1], "old": a, "new": b})
        per_task.setdefault(key[0], []).append((1.0 if b else 0.0) - (1.0 if a else 0.0))

    n = len(keys)
    old_pass = both + old_only
    new_pass = both + new_only
    task_delta = {task: statistics.mean(values) for task, values in per_task.items()}
    boot = paired_bootstrap(task_delta, samples=samples, seed=seed)
    return {
        "paired_trials": n,
        "paired_tasks": len(task_delta),
        "old_pass": old_pass,
        "new_pass": new_pass,
        "old_rate": old_pass / n,
        "new_rate": new_pass / n,
        "delta_pp": (new_pass - old_pass) / n * 100,
        "mcnemar": {
            "old_only": old_only,
            "new_only": new_only,
            "test": "exact_binomial_two_sided",
            "p_value": binom_two_sided_p(old_only, new_only),
        },
        "bootstrap": boot,
        "flips": {
            "total": len(flips),
            "both_pass": both,
            "both_fail": neither,
            "old_only": old_only,
            "new_only": new_only,
        },
        "flip_trials": flips,
    }


def _print(result: dict[str, Any], old_path: Path, new_path: Path, agent: str) -> None:
    mcnemar = result["mcnemar"]
    boot = result["bootstrap"]
    interval = boot.get("interval_95")
    ci = f"[{interval[0] * 100:+.1f}, {interval[1] * 100:+.1f}] pp" if interval is not None else "—"
    print(f"old = {old_path}  (agent={agent})")
    print(f"new = {new_path}")
    print(f"配对 trial = {result['paired_trials']}（{result['paired_tasks']} 题）")
    print(
        f"通过：old {result['old_pass']}/{result['paired_trials']} = {result['old_rate']:.1%}  "
        f"→ new {result['new_pass']}/{result['paired_trials']} = {result['new_rate']:.1%}"
    )
    print(f"Δ = {result['delta_pp']:+.1f} pp")
    print(
        f"McNemar exact p = {mcnemar['p_value']:.4f}"
        f"（old 独过 {mcnemar['old_only']} / new 独过 {mcnemar['new_only']}）"
    )
    print(
        f"题块 bootstrap（{boot['tasks']} 题，{boot['samples']} 次）：estimate={result['delta_pp']:+.1f} pp  CI95={ci}"
    )
    flips = result["flips"]
    print(
        f"翻转 {flips['total']} 个 trial（both_pass={flips['both_pass']}，"
        f"both_fail={flips['both_fail']}）"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD, help="旧批次 FINAL-SUMMARY.json")
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW, help="新批次 FINAL-SUMMARY.json")
    parser.add_argument("--agent", default="sayacode", help="默认 sayacode")
    parser.add_argument("--samples", type=int, default=SAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=None, help="输出 JSON 路径")
    args = parser.parse_args(argv)

    for path in (args.old, args.new):
        if not path.is_file():
            parser.error(f"找不到 FINAL-SUMMARY：{path}")
    try:
        old = load_trials(args.old, args.agent)
        new = load_trials(args.new, args.agent)
        result = compare(old, new, samples=args.samples, seed=args.seed)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    payload = {"old": str(args.old), "new": str(args.new), "agent": args.agent, **result}
    _print(result, args.old, args.new, args.agent)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n明细已写 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
