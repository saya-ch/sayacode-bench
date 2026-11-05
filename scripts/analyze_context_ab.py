"""长上下文压力 A/B 的配对退化分析（clean vs noise，同题同 repeat）。

判定标准见 docs/EXPERIMENT-CONTEXT-AB.md §2.6：
  - 假设成立：noise-100k 下至少一组 Δ ≥ 15pp，且 SAYACODE 的 Δ 与其他组的最小差值 ≥ 10pp（CI 不含 0）；
  - 不成立：四组 Δ 都 < 5pp 且两两不显著 → 该题集不吃上下文；
  - 中间地带：只有部分组显著退化。

用法::

    uv run --no-sync python scripts/analyze_context_ab.py \\
        --clean-root C:\\sb\\hard\\v4-327 \\
        --noise-root C:\\sb\\hard\\v4-327-noise100k \\
        --sample C:\\sb\\tmp\\parts-327\\sample-light.json \\
        --agents sayacode mini-swe claude-code opencode
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compare_trials import binom_two_sided_p  # noqa: E402

from sayacode_bench.analysis import paired_bootstrap  # noqa: E402
from sayacode_bench.formal import load_sample, scan_agent  # noqa: E402


def rewards(agent_dir: Path, agent: str, tasks: list) -> dict[tuple[str, int], float]:
    """(task_id, repeat) -> effective_reward；未观测的 trial 不进入配对。"""
    out: dict[tuple[str, int], float] = {}
    if not agent_dir.is_dir():
        return out
    for trial in scan_agent(agent_dir, agent, tasks):
        if trial.task_id is None or trial.effective_reward is None:
            continue
        out[(trial.task_id, trial.repeat)] = float(trial.effective_reward)
    return out


def analyze(
    agent: str, clean: dict, noise: dict, task_ids: list[str], repeats: int
) -> dict:
    plan = [(tid, r) for tid in task_ids for r in range(1, repeats + 1)]
    both = clean_only = noise_only = neither = 0
    per_task: dict[str, list[float]] = defaultdict(list)
    paired_rows = []
    for tid, repeat in plan:
        key = (tid, repeat)
        if key not in clean or key not in noise:
            continue
        c = clean[key] == 1.0
        n = noise[key] == 1.0
        per_task[tid].append((1.0 if c else 0.0) - (1.0 if n else 0.0))
        paired_rows.append({"task_id": tid, "repeat": repeat, "clean": c, "noise": n})
        if c and n:
            both += 1
        elif c and not n:
            clean_only += 1
        elif n and not c:
            noise_only += 1
        else:
            neither += 1
    n_pairs = len(paired_rows)
    clean_rate = (both + clean_only) / n_pairs if n_pairs else None
    noise_rate = (both + noise_only) / n_pairs if n_pairs else None
    cycle = {tid: sum(vals) / len(vals) for tid, vals in per_task.items() if vals}
    boot = paired_bootstrap(cycle, samples=10_000, seed=20261022) if cycle else {"estimate": None}
    return {
        "agent": agent,
        "pairs": n_pairs,
        "clean_rate": clean_rate,
        "noise_rate": noise_rate,
        "delta_pp": None if None in (clean_rate, noise_rate) else (clean_rate - noise_rate) * 100,
        "both_pass": both,
        "clean_only": clean_only,
        "noise_only": noise_only,
        "both_fail": neither,
        "mcnemar_p": binom_two_sided_p(clean_only, noise_only) if n_pairs else None,
        "task_block_bootstrap": boot,
        "unpaired_clean_only": len(set(clean) - set(noise)),
        "unpaired_noise_only": len(set(noise) - set(clean)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-root", required=True)
    parser.add_argument("--noise-root", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--agents", nargs="+", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    tasks, _ = load_sample(Path(args.sample))
    task_ids = [t.task_id for t in tasks]
    print(f"题集 {len(task_ids)} 题 × {args.repeats} 重复；agents={args.agents}\n")
    header = (
        f"{'agent':14}{'pairs':>7}{'clean%':>9}{'noise%':>9}{'Δpp':>8}"
        f"{'c-only':>8}{'n-only':>8}{'p':>9}{'Δ CI95':>22}"
    )
    print(header)
    print("-" * len(header))
    rows = []
    for agent in args.agents:
        clean = rewards(Path(args.clean_root) / agent, agent, tasks)
        noise = rewards(Path(args.noise_root) / agent, agent, tasks)
        row = analyze(agent, clean, noise, task_ids, args.repeats)
        rows.append(row)
        ci = row["task_block_bootstrap"].get("interval_95")
        ci_text = f"[{ci[0] * 100:+.1f}, {ci[1] * 100:+.1f}]" if ci else "n/a"
        print(
            f"{agent:14}{row['pairs']:>7}"
            f"{(row['clean_rate'] or 0) * 100:>8.1f}%{(row['noise_rate'] or 0) * 100:>8.1f}%"
            f"{(row['delta_pp'] or 0):>+8.1f}{row['clean_only']:>8}{row['noise_only']:>8}"
            f"{(row['mcnemar_p'] or 1):>9.3f}{ci_text:>22}"
        )
    payload = {"clean_root": args.clean_root, "noise_root": args.noise_root, "agents": rows}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
