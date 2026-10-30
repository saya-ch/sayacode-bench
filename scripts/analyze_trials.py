"""统一评测分析器：结果 + 过程 + 效率 + 护栏 + 记分卡指标。

指标：pass@1 / partial credit / 步数 / 重复读 / 改测试(reward hacking) / 空转 /
      token / cost-per-success / bloat ratio / step-per-success / 重复方差

用法: python analyze_trials.py <jobs目录> [<jobs目录2> ...]
兼容两种层级：jobs/<trial>/... 或 jobs/<job>/instance_<...>/...
"""

import json
import math
import re
import statistics as st
import sys
from pathlib import Path

pat_req = re.compile(r"Required tests:\s*(\d+)")
pat_reqpass = re.compile(r"Required tests that passed:\s*(\d+)")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - hw), min(1, c + hw))


def load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def find_inner(job: Path):
    # 先找 trial 级 instance_* 子目录（ho-/reg- job 结构）
    for d in job.iterdir():
        if d.is_dir() and d.name.startswith("instance_"):
            return d
    # 退化：job 本身即 trial（jobs/instance_xxx 结构）
    if (job / "verifier").is_dir() or (job / "agent").is_dir():
        return job
    return None


def analyze_trial(job: Path):
    inner = find_inner(job)
    if inner is None:
        return None
    out = {"job": job.name, "task_id": None, "reward": None, "partial": None, "steps": None,
           "repeat_reads": 0, "restored": 0, "stripped": 0, "empty_patch": False,
           "tokens": None, "patch_bytes": None, "gold_bytes": None}

    d = load_json(inner / "result.json") or {}
    tn = (d.get("task_name", "") or "").split("/")[-1]
    out["task_id"] = tn or job.name

    rw = inner / "verifier" / "reward.txt"
    if rw.is_file():
        try:
            out["reward"] = float(rw.read_text().strip())
        except Exception:
            pass
    for so in inner.rglob("test-stdout.txt"):
        txt = so.read_text(encoding="utf-8", errors="replace")
        mr, mp = pat_req.search(txt), pat_reqpass.search(txt)
        if mr and mp and int(mr.group(1)):
            out["partial"] = int(mp.group(1)) / int(mr.group(1))
        break

    ar = d.get("agent_result") or {}
    tin, tout = ar.get("n_input_tokens"), ar.get("n_output_tokens")
    if isinstance(tin, int) and isinstance(tout, int):
        out["tokens"] = tin + tout

    for ev in inner.rglob("events.jsonl"):
        reads = {}
        steps = 0
        for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") == "tool.started":
                steps += 1
                if e.get("tool_name") == "read_file":
                    p = (e.get("tool_input") or {}).get("path")
                    if isinstance(p, str):
                        reads[p] = reads.get(p, 0) + 1
        out["steps"] = steps
        out["repeat_reads"] = sum(1 for v in reads.values() if v > 1)
        break

    for name, key in (("restored-test-files.json", "restored"), ("stripped-new-test-files.json", "stripped")):
        f = inner / "agent" / name
        if f.is_file():
            j = load_json(f) or {}
            out[key] = len(j) if isinstance(j, (list, dict)) else 1

    mp = inner / "agent" / "model.patch"
    if mp.is_file():
        out["patch_bytes"] = mp.stat().st_size
        out["empty_patch"] = out["patch_bytes"] == 0

    c = load_json(inner / "config.json") or {}
    tp = (c.get("task") or {}).get("path")
    if tp:
        gp = Path(tp) / "solution" / "gold_patch.diff"
        if gp.is_file():
            out["gold_bytes"] = gp.stat().st_size
    return out


def main():
    roots = [Path(a) for a in sys.argv[1:]] or [Path(r"C:\sb\hard\hy3-holdout\jobs")]
    trials = []
    for root in roots:
        if not root.is_dir():
            continue
        for job in root.iterdir():
            if job.is_dir():
                t = analyze_trial(job)
                if t:
                    trials.append(t)
    trials = [t for t in trials if t["reward"] is not None or t["partial"] is not None]
    if not trials:
        print("无可分析 trial")
        return

    print(f"=== {len(trials)} 个 trial ===")
    print(f"{'task':<30}{'reward':>7}{'partial':>8}{'steps':>6}{'tokK':>7}{'patch':>7}{'gold':>7}{'改测':>5}")
    for t in trials:
        tk = str(t["tokens"] // 1000) if t["tokens"] else "-"
        pp = f"{t['partial']*100:.0f}%" if t["partial"] is not None else "-"
        rh = "Y" if (t["restored"] or t["stripped"]) else ""
        print(f"{(t['task_id'] or '')[:28]:<30}{str(t['reward']):>7}{pp:>8}"
              f"{str(t['steps']):>6}{tk:>7}{str(t['patch_bytes']):>7}{str(t['gold_bytes']):>7}{rh:>5}")

    has = [t for t in trials if t["reward"] is not None]
    n = len(has)
    if not n:
        return
    pass_n = sum(1 for t in has if t["reward"] == 1.0)
    lo, hi = wilson(pass_n, n)
    print(f"\n=== 记分卡（n={n}，pass {pass_n}）===")
    print(f"  pass@1            {pass_n}/{n} = {pass_n/n:.1%}  95%CI [{lo:.1%},{hi:.1%}]")
    parts = [t["partial"] for t in has if t["partial"] is not None]
    if parts:
        print(f"  partial credit    均值 {st.mean(parts):.1%}")
    toks = [t["tokens"] for t in has if t["tokens"]]
    if toks:
        print(f"  cost-per-success  {sum(toks)/max(pass_n,1)/1000:.0f}K tokens/成功（总 {sum(toks)/1e6:.1f}M）")
    stps = [t["steps"] for t in has if t["steps"]]
    if stps:
        print(f"  step-per-success  {sum(stps)/max(pass_n,1):.0f} 步/成功（总 {sum(stps)}）")
    hacked = sum(1 for t in has if t["restored"] > 0 or t["stripped"] > 0)
    print(f"  reward hacking    {hacked}/{n} trial 改/删测试（{hacked/n:.0%}）")
    bl = [t["patch_bytes"] / t["gold_bytes"] for t in has if t["patch_bytes"] and t["gold_bytes"]]
    if bl:
        print(f"  bloat ratio       中位 {st.median(bl):.2f}×（patch/gold，>1.5 膨胀）")
    if stps:
        print(f"  平均步数           {st.mean(stps):.0f}；重复读 {sum(t['repeat_reads'] for t in has)} 处")
    print(f"  空转(patch=0)      {sum(1 for t in has if t['empty_patch'])}")
    by_task = {}
    for t in trials:
        by_task.setdefault(t["task_id"], []).append(t["reward"])
    multi = {k: v for k, v in by_task.items() if len(v) > 1 and None not in v}
    if multi:
        print(f"  重复方差(同题)     {len(multi)} 题有重复，通过率标准差均值 {st.mean([st.pstdev(v) for v in multi.values()]):.2f}")


if __name__ == "__main__":
    main()
