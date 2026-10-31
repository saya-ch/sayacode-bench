"""三 agent 正式结果汇总：pass@1/partial/cost/step/改测试/bloat/方差 + 两两配对。

用法: python scripts/summarize_formal.py --root C:\sb\hard\formal-240
"""

import argparse
import json
import math
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

AGENTS = ("sayacode", "mini-swe", "codex")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - hw), min(1, c + hw))


def binom_two_sided_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    s = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * s)


def analyze_trial(job: Path):
    inner = next((d for d in job.iterdir() if d.is_dir() and d.name.startswith("instance_")), None)
    if inner is None:
        return None
    out = {"task": None, "reward": None, "partial": None, "steps": None, "tokens": None,
           "patch": None, "gold": None, "restored": 0, "stripped": 0, "empty": False}
    d = {}
    rj = inner / "result.json"
    if rj.is_file():
        try:
            d = json.loads(rj.read_text(encoding="utf-8"))
        except Exception:
            d = {}
    out["task"] = (d.get("task_name", "") or "").split("/")[-1]

    rw = inner / "verifier" / "reward.txt"
    if rw.is_file():
        try:
            out["reward"] = float(rw.read_text().strip())
        except Exception:
            pass
    for so in inner.rglob("test-stdout.txt"):
        txt = so.read_text(encoding="utf-8", errors="replace")
        mr = re.search(r"Required tests:\s*(\d+)", txt)
        mp = re.search(r"Required tests that passed:\s*(\d+)", txt)
        if mr and mp and int(mr.group(1)):
            out["partial"] = int(mp.group(1)) / int(mr.group(1))
        break
    ar = d.get("agent_result") or {}
    ti, to = ar.get("n_input_tokens"), ar.get("n_output_tokens")
    if isinstance(ti, int) and isinstance(to, int):
        out["tokens"] = ti + to
    for ev in inner.rglob("events.jsonl"):
        n = sum(1 for line in ev.read_text(encoding="utf-8", errors="replace").splitlines() if '"tool.started"' in line)
        out["steps"] = n
        break
    for name, key in (("restored-test-files.json", "restored"), ("stripped-new-test-files.json", "stripped")):
        f = inner / "agent" / name
        if f.is_file():
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
                out[key] = len(j) if isinstance(j, (list, dict)) else 1
            except Exception:
                out[key] = 1
    mp = inner / "agent" / "model.patch"
    if mp.is_file():
        out["patch"] = mp.stat().st_size
        out["empty"] = out["patch"] == 0
    c = inner / "config.json"
    if c.is_file():
        try:
            cfg = json.loads(c.read_text(encoding="utf-8"))
            tp = (cfg.get("task") or {}).get("path")
            if tp:
                gp = Path(tp) / "solution" / "gold_patch.diff"
                if gp.is_file():
                    out["gold"] = gp.stat().st_size
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root)

    stats = {}
    for agent in AGENTS:
        jobs = root / agent / "jobs"
        if not jobs.is_dir():
            print(f"{agent}: 无结果目录")
            continue
        trials = []
        for job in jobs.iterdir():
            if job.is_dir():
                t = analyze_trial(job)
                if t and (t["reward"] is not None or t["partial"] is not None):
                    trials.append(t)
        stats[agent] = trials

    print(f"{'agent':<12}{'n':>4}{'pass@1':>9}{'95%CI':>16}{'partial':>9}{'tok/成功':>10}{'step/成功':>10}{'改测试':>8}{'空转':>6}")
    for agent, trials in stats.items():
        n = len(trials)
        p = sum(1 for t in trials if t["reward"] == 1.0)
        lo, hi = wilson(p, n)
        parts = [t["partial"] for t in trials if t["partial"] is not None]
        toks = [t["tokens"] for t in trials if t["tokens"]]
        stps = [t["steps"] for t in trials if t["steps"]]
        hacked = sum(1 for t in trials if t["restored"] or t["stripped"])
        empty = sum(1 for t in trials if t["empty"])
        cp = f"{sum(toks)/max(p,1)/1000:.0f}K" if toks else "-"
        sp = f"{sum(stps)/max(p,1):.0f}" if stps else "-"
        print(f"{agent:<12}{n:>4}{p/n:>8.1%}{f'[{lo:.0%},{hi:.0%}]':>16}"
              f"{(st.mean(parts) if parts else 0):>8.1%}{cp:>10}{sp:>10}{hacked:>8}{empty:>6}")

    # 两两配对（同题、按多数或 best）
    print("\n=== 两两配对（同题）===")
    names = [a for a in stats if stats[a]]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            A, B = names[i], names[j]
            byA = defaultdict(list)
            for t in stats[A]:
                byA[t["task"]].append(t["reward"])
            byB = defaultdict(list)
            for t in stats[B]:
                byB[t["task"]].append(t["reward"])
            common = [k for k in byA if k in byB]
            b = c = 0
            for k in common:
                ra = max(byA[k]) if None not in byA[k] else None
                rb = max(byB[k]) if None not in byB[k] else None
                if ra == 1.0 and rb == 0.0:
                    b += 1
                elif ra == 0.0 and rb == 1.0:
                    c += 1
            p = binom_two_sided_p(b, c)
            print(f"  {A} vs {B}: 共同 {len(common)} 题，A独过 {b} / B独过 {c}，McNemar p={p:.3f}")


if __name__ == "__main__":
    main()
