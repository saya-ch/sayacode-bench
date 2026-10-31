"""最终汇总（修复版）：按 job 名合并 native + verify 结果，每 trial 一个 reward。"""

import json
import math
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\sb\hard\formal-240")
AGENTS = ("sayacode", "mini-swe", "codex")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - hw), min(1, c + hw))


def reward_of(inner: Path):
    rw = inner / "verifier" / "reward.txt"
    if rw.is_file():
        try:
            return float(rw.read_text().strip())
        except Exception:
            return None
    return None


def partial_of(inner: Path):
    for so in inner.rglob("test-stdout.txt"):
        txt = so.read_text(encoding="utf-8", errors="replace")
        mr = re.search(r"Required tests:\s*(\d+)", txt)
        mp = re.search(r"Required tests that passed:\s*(\d+)", txt)
        if mr and mp and int(mr.group(1)):
            return int(mp.group(1)) / int(mr.group(1))
        break
    return None


def hacked_of(inner: Path) -> bool:
    for name in ("restored-test-files.json", "stripped-new-test-files.json"):
        f = inner / "agent" / name
        if f.is_file():
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
                if j:
                    return True
            except Exception:
                return True
    return False


def patch_of(inner: Path):
    mp = inner / "agent" / "model.patch"
    if mp.is_file():
        return mp.stat().st_size
    return None


def gold_of(inner: Path):
    c = inner / "config.json"
    if not c.is_file():
        return None
    try:
        tp = (json.loads(c.read_text(encoding="utf-8")).get("task") or {}).get("path")
        if tp:
            gp = Path(tp) / "solution" / "gold_patch.diff"
            if gp.is_file():
                return gp.stat().st_size
    except Exception:
        pass
    return None


def collect(agent_dir: Path) -> dict:
    """返回 {task: [ {job, repeat, reward, partial, hacked, patch, gold} ]}，按 job 名合并两阶段。"""
    native = {}   # job_name -> inner dir
    verified = {}  # orig job_name -> inner dir
    for base, prefix in ((agent_dir / "jobs", ""), (agent_dir / "verify" / "jobs", "verify-")):
        if not base.is_dir():
            continue
        for job in base.iterdir():
            if not job.is_dir():
                continue
            inner = next((d for d in job.iterdir() if d.is_dir() and d.name.startswith("instance_")), None)
            if inner is None:
                continue
            orig = job.name[len(prefix):] if prefix and job.name.startswith(prefix) else job.name
            if prefix:
                verified[orig] = inner
            else:
                native[orig] = inner

    by_task = defaultdict(list)
    for job_name in set(native) | set(verified):
        reward = None
        partial = None
        patch = None
        gold = None
        hacked = False
        if job_name in native:
            n = native[job_name]
            reward = reward_of(n)
            partial = partial_of(n)
            patch = patch_of(n)
            gold = gold_of(n)
            hacked = hacked_of(n)
        if reward is None and job_name in verified:
            v = verified[job_name]
            reward = reward_of(v)
            if partial is None:
                partial = partial_of(v)
            if patch is None:
                patch = patch_of(v)
            if gold is None:
                gold = gold_of(v)
        # task 名：从 result.json 拿
        task = None
        for cand in (native.get(job_name), verified.get(job_name)):
            if cand is None:
                continue
            rj = cand / "result.json"
            if rj.is_file():
                try:
                    task = (json.loads(rj.read_text(encoding="utf-8")).get("task_name") or "").split("/")[-1]
                except Exception:
                    pass
            if task:
                break
        if not task:
            task = job_name
        rep = 1 if job_name.endswith("r1") else (2 if job_name.endswith("r2") else 0)
        by_task[task].append({"job": job_name, "repeat": rep, "reward": reward,
                              "partial": partial, "hacked": hacked,
                              "patch": patch, "gold": gold})
    return by_task


def main():
    print("=" * 74)
    print("三 agent 正式对比 · 最终汇总（SWE-bench Pro V2，40 题 × 2 重复）")
    print("=" * 74)

    stats = {}
    for agent in AGENTS:
        d = ROOT / agent
        if not d.is_dir():
            continue
        by_task = collect(d)
        trials = [t for lst in by_task.values() for t in lst if t["reward"] is not None]
        stats[agent] = {"by_task": by_task, "trials": trials}

    print(f"\n{'agent':<10}{'有效trial':>9}{'pass@1':>10}{'95%CI':>18}{'partial':>9}{'改测试':>8}{'空patch':>8}{'bloat':>7}")
    for agent, s in stats.items():
        trials = s["trials"]
        n = len(trials)
        p = sum(1 for t in trials if t["reward"] == 1.0)
        lo, hi = wilson(p, n)
        parts = [t["partial"] for t in trials if t["partial"] is not None]
        hacked = sum(1 for t in trials if t["hacked"])
        empty = sum(1 for t in trials if t["patch"] == 0)
        bloat = [t["patch"] / t["gold"] for t in trials if t["patch"] and t["gold"]]
        print(f"{agent:<10}{n:>9}{p/n:>9.1%}{f'[{lo:.0%},{hi:.0%}]':>18}"
              f"{(st.mean(parts) if parts else 0):>9.1%}{hacked/n:>8.0%}{empty:>8}"
              f"{(st.median(bloat) if bloat else 0):>7.2f}")

    print("\n=== pass@2（任一次过）/ pass^2（两次都过）===")
    for agent, s in stats.items():
        bt = s["by_task"]
        multi = {k: v for k, v in bt.items() if len([x for x in v if x["reward"] is not None]) >= 2}
        if not multi:
            continue
        p2 = sum(1 for v in multi.values() if any(x["reward"] == 1.0 for x in v))
        ph2 = sum(1 for v in multi.values() if all(x["reward"] == 1.0 for x in v if x["reward"] is not None))
        print(f"  {agent:<10} 题 {len(multi):>2}  pass@2={p2}/{len(multi)}={p2/len(multi):.1%}  "
              f"pass^2={ph2}/{len(multi)}={ph2/len(multi):.1%}")

    print("\n=== 两两配对（同题取最好）· McNemar ===")
    names = [a for a in stats if stats[a]["trials"]]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            A, B = names[i], names[j]
            ba, bb = stats[A]["by_task"], stats[B]["by_task"]
            common = set(ba) & set(bb)
            b = c = 0
            for k in common:
                ra = max((x["reward"] for x in ba[k] if x["reward"] is not None), default=None)
                rb = max((x["reward"] for x in bb[k] if x["reward"] is not None), default=None)
                if ra == 1.0 and rb == 0.0:
                    b += 1
                elif ra == 0.0 and rb == 1.0:
                    c += 1
            n = b + c
            if n:
                kk = min(b, c)
                pv = min(1.0, 2 * sum(math.comb(n, x) for x in range(0, kk + 1)) / (2 ** n))
            else:
                pv = 1.0
            print(f"  {A} vs {B}: 共同 {len(common)}，A独过 {b} / B独过 {c}，p={pv:.3f}")

    # 逐题明细
    out = ROOT / "FINAL-SUMMARY.json"
    out.write_text(json.dumps({
        a: {"n": len(s["trials"]),
            "pass": sum(1 for x in s["trials"] if x["reward"] == 1.0),
            "trials": s["trials"]}
        for a, s in stats.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n明细已写 {out}")


if __name__ == "__main__":
    main()
