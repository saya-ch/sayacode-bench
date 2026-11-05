"""大评测集汇总：每套题单独出统计，再给合并总体。

输入目录约定（每个 source 独立跑批、独立结果根）：
    <root>/<source>/<agent>/{jobs,verify/jobs}

用法::

    uv run --no-sync python scripts/summarize_large_set.py \
        --root C:\\sb\\hard\\large-v1 \
        --sample studies/large-sample-v1.json \
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
from strict_compare import SNAP_RE, _collect, _find_patch, _patch_files  # noqa: E402

from sayacode_bench.analysis import paired_bootstrap  # noqa: E402


def _source_rows(sample: dict) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for t in sample["tasks"]:
        by[t["source"]].append(t)
    return dict(by)


def summarize_source(agent: str, source: str, agent_dir: Path, tasks: list[dict]) -> dict:
    expected = len(tasks)
    trials, _ = _collect(agent_dir) if agent_dir.is_dir() else ({}, 0)
    observed = passes = strict = snap = 0
    per_stratum: dict[str, list[float]] = defaultdict(list)
    by_native = {t["native_id"]: t for t in tasks}
    outcomes: dict[str, dict[str, bool | None]] = defaultdict(dict)
    for key, info in sorted(trials.items()):
        reward = info["reward"]
        if reward is None and info.get("terminal") is None:
            continue
        observed += 1
        ok = reward in ("1", "1.0")
        if ok:
            passes += 1
            patch = _find_patch(info["job"])
            files = _patch_files(patch) or [] if patch else []
            if any(SNAP_RE.search(f) for f in files):
                snap += 1
            else:
                strict += 1
        # 该题属于哪个层：job 名里含 native_id 前缀
        matched = next((t for tid, t in by_native.items() if tid and tid[:30] in key), None)
        stratum = matched["stratum"] if matched else "unknown"
        per_stratum[stratum].append(1.0 if ok else 0.0)
        outcomes[agent][key] = ok
    return {
        "agent": agent,
        "source": source,
        "planned": expected,
        "observed": observed,
        "missing": expected - observed,
        "passes": passes,
        "snap_passes": snap,
        "strict_passes": strict,
        "planned_pct": round(100 * passes / expected, 1) if expected else None,
        "strict_pct": round(100 * strict / expected, 1) if expected else None,
        "strata": {
            k: {"n": len(v), "pass_pct": round(100 * sum(v) / len(v), 1)}
            for k, v in sorted(per_stratum.items())
        },
        "_outcomes": outcomes[agent],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--sample", required=True)
    p.add_argument("--agents", nargs="+", required=True)
    p.add_argument("--json-out", default=None)
    args = p.parse_args()

    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    sources = _source_rows(sample)
    root = Path(args.root)
    rows: list[dict] = []

    print("=== 每套题单独统计 ===")
    print(f"{'source':10}{'agent':14}{'N':>5}{'pass':>6}{'planned%':>10}{'strict%':>9}{'snap':>6}{'miss':>6}")
    print("-" * 66)
    for source, tasks in sources.items():
        for agent in args.agents:
            row = summarize_source(agent, source, root / source / agent, tasks)
            rows.append(row)
            print(
                f"{source:10}{agent:14}{row['planned']:>5}{row['passes']:>6}"
                f"{row['planned_pct'] or 0:>9.1f}%{row['strict_pct'] or 0:>8.1f}%"
                f"{row['snap_passes']:>6}{row['missing']:>6}"
            )

    print("\n=== 合并总体（跨题组，只作总体口径，不替代分组结论）===")
    print(f"{'agent':14}{'N':>5}{'pass':>6}{'planned%':>10}{'strict%':>9}")
    totals = []
    for agent in args.agents:
        sub = [r for r in rows if r["agent"] == agent]
        n = sum(r["planned"] for r in sub)
        passes = sum(r["passes"] for r in sub)
        strict = sum(r["strict_passes"] for r in sub)
        print(f"{agent:14}{n:>5}{passes:>6}{100 * passes / n:>9.1f}%{100 * strict / n:>8.1f}%")
        totals.append({"agent": agent, "n": n, "passes": passes, "strict": strict,
                       "planned_pct": round(100 * passes / n, 1), "strict_pct": round(100 * strict / n, 1)})

    # 题级配对 McNemar（跨全部 source，四组同题）
    if len(args.agents) >= 2:
        print("\n=== 题级配对 McNemar（全部 312 题）===")
        all_outcomes: dict[str, dict[str, bool | None]] = defaultdict(dict)
        for row in rows:
            all_outcomes[row["agent"]].update(row["_outcomes"])
        merged: dict[str, dict[str, bool | None]] = defaultdict(dict)
        for agent, outcomes in all_outcomes.items():
            for key, ok in outcomes.items():
                merged[key][agent] = ok
        for i, a in enumerate(args.agents):
            for b in args.agents[i + 1 :]:
                a_only = b_only = 0
                diffs: dict[str, float] = defaultdict(float)
                for key, vals in merged.items():
                    if a not in vals or b not in vals:
                        continue
                    va, vb = bool(vals[a]), bool(vals[b])
                    a_only += int(va and not vb)
                    b_only += int(vb and not va)
                    diffs[key] += (1.0 if va else 0.0) - (1.0 if vb else 0.0)
                boot = paired_bootstrap(dict(diffs), samples=10_000, seed=20261022)
                ci = boot.get("interval_95")
                ci_text = f"[{ci[0] * 100:+.1f}, {ci[1] * 100:+.1f}]pp" if ci else "n/a"
                print(f"  {a} vs {b}: a_only={a_only} b_only={b_only} p={binom_two_sided_p(a_only, b_only):.4f}  ΔCI={ci_text}")

    payload = {"sample": str(Path(args.sample)), "root": str(root), "by_source": [
        {k: v for k, v in r.items() if k != "_outcomes"} for r in rows
    ], "overall": totals}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
