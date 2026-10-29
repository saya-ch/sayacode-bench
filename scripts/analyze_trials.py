"""统一评测分析器：从 job 目录算出 partial credit + 过程指标 + pass^k + CI。

用法: python analyze_eval.py <jobs目录> [<jobs目录2> ...]
每个 trial 目录里若有 verifier/test-stdout.txt 或 agent/sayacode/{events.jsonl,result.json} 即可分析。
"""

import json
import math
import re
import sys
from collections import defaultdict
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


def analyze_trial(trial_dir: Path) -> dict:
    out = {"dir": trial_dir.name, "reward": None, "required": None, "required_passed": None,
           "partial": None, "steps": None, "repeat_reads": 0, "restored_tests": 0,
           "stripped_tests": 0, "empty_patch": False, "input_tokens": None, "duration": None}

    # partial credit
    for so in trial_dir.rglob("test-stdout.txt"):
        txt = so.read_text(encoding="utf-8", errors="replace")
        mr, mp = pat_req.search(txt), pat_reqpass.search(txt)
        if mr:
            out["required"] = int(mr.group(1))
            out["required_passed"] = int(mp.group(1)) if mp else 0
            if out["required"]:
                out["partial"] = out["required_passed"] / out["required"]

    rw = trial_dir / "verifier" / "reward.txt"
    if rw.is_file():
        try:
            out["reward"] = float(rw.read_text().strip())
        except Exception:
            pass

    # agent result
    res = trial_dir / "agent" / "sayacode" / "result.json"
    if res.is_file():
        try:
            d = json.loads(res.read_text(encoding="utf-8"))
            out["input_tokens"] = (d.get("usage") or {}).get("input_tokens")
            out["duration"] = d.get("duration_seconds")
        except Exception:
            pass

    # events 过程指标
    for ev in trial_dir.rglob("events.jsonl"):
        reads = defaultdict(int)
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
                        reads[p] += 1
        out["steps"] = steps
        out["repeat_reads"] = sum(1 for v in reads.values() if v > 1)
        break

    # 机制保护触发
    out["restored_tests"] = len(list(trial_dir.rglob("restored-test-files.json")))
    out["stripped_tests"] = len(list(trial_dir.rglob("stripped-new-test-files.json")))

    # 空转：patch 为空
    for mp in trial_dir.rglob("model.patch"):
        try:
            out["empty_patch"] = mp.stat().st_size == 0
        except Exception:
            pass

    return out


def main() -> None:
    roots = [Path(a) for a in sys.argv[1:]] or [Path(r"C:\sb\tmp\hard\pipeline-holdout-release-r1\jobs")]
    trials = []
    for root in roots:
        if not root.is_dir():
            continue
        # trial 目录 = 含 verifier 或 agent 的目录
        for cand in root.rglob("instance_*"):
            if cand.is_dir() and ((cand / "verifier").exists() or (cand / "agent").exists()):
                trials.append(analyze_trial(cand))

    trials = [t for t in trials if t["reward"] is not None or t["partial"] is not None]
    if not trials:
        print("未找到可分析 trial")
        return

    print(f"=== {len(trials)} 个 trial ===")
    print(f"{'trial':<34}{'reward':>7}{'partial':>9}{'steps':>7}{'repRead':>8}{'restore':>8}{'empty':>6}")
    for t in trials:
        p = f"{t['partial']*100:.0f}%" if t['partial'] is not None else "-"
        print(f"{t['dir'][:32]:<34}{str(t['reward']):>7}{p:>9}{str(t['steps']):>7}"
              f"{t['repeat_reads']:>8}{t['restored_tests']:>8}{str(t['empty_patch']):>6}")

    # 汇总（按 reward）
    has_r = [t for t in trials if t["reward"] is not None]
    if has_r:
        pass1 = sum(1 for t in has_r if t["reward"] == 1.0)
        lo, hi = wilson(pass1, len(has_r))
        print(f"\npass@1 = {pass1}/{len(has_r)} = {pass1/len(has_r):.1%}  95%CI [{lo:.1%},{hi:.1%}]")
        partials = [t["partial"] for t in has_r if t["partial"] is not None]
        if partials:
            print(f"平均 partial credit = {sum(partials)/len(partials):.1%}（0/1 会把接近成功的算作 0）")
            near = [t for t in has_r if t["reward"] == 0 and (t["partial"] or 0) >= 0.75]
            print(f"reward=0 但 partial≥75%: {len(near)} 个（这些其实是'差一点'）")
        # 过程指标均值
        steps = [t["steps"] for t in has_r if t["steps"]]
        if steps:
            print(f"平均步数 = {sum(steps)/len(steps):.0f}")
        print(f"改既有测试(保护触发)合计 = {sum(t['restored_tests'] for t in has_r)} 次；"
              f"空转(patch=0) = {sum(1 for t in has_r if t['empty_patch'])} 个")


if __name__ == "__main__":
    main()
