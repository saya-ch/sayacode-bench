"""配对 A/B 比对：McNemar 检验 + 效应量 + 置信区间。

用法: python compare_ab.py <A_jobs目录> <B_jobs目录> [--best-of]
每个 trial 目录需含 verifier/reward.txt。按 task_id 聚合（同题多次重复取 best-of 或 pass@1）。
"""

import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

pat = re.compile(r"instance_([A-Za-z0-9_.-]+?)(?:__|-r\d)")


def task_key(trial_dir: Path) -> str:
    # 用父 job 名（含完整 task id）作为 key；退化到目录名
    parent = trial_dir.parent.name if trial_dir.parent else trial_dir.name
    return parent


def collect(jobs: Path) -> dict[str, list[float]]:
    """返回 {task: [rewards per repeat]}"""
    out = defaultdict(list)
    if not jobs.is_dir():
        return out
    for trial in jobs.rglob("instance_*"):
        rw = trial / "verifier" / "reward.txt"
        if not rw.is_file():
            continue
        try:
            val = float(rw.read_text().strip())
        except Exception:
            continue
        key = task_key(trial)
        # 去掉 repeat 后缀让同一 task 的多次重复归并
        key = re.sub(r"-r\d+$", "", key)
        out[key].append(val)
    return out


def rate(rewards: list[float], best_of: bool) -> int:
    if not rewards:
        return 0
    return 1 if (max(rewards) == 1.0 if best_of else (sum(rewards) / len(rewards) >= 0.5)) else 0


def binom_two_sided_p(b: int, c: int) -> float:
    """McNemar 精确检验（二项），返回双尾 p。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # sum_{i=0}^{k} C(n,i) * 0.5^n * 2
    s = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * s)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    best_of = "--best-of" in sys.argv
    if len(args) < 2:
        print("用法: python compare_ab.py <A_jobs> <B_jobs> [--best-of]")
        return
    A, B = collect(Path(args[0])), collect(Path(args[1]))
    tasks = sorted(set(A) | set(B))
    common = [t for t in tasks if A.get(t) and B.get(t)]

    a_pass = b_pass = 0
    tbl = {"A过B过": 0, "A过B败": 0, "A败B过": 0, "A败B败": 0}
    print(f"{'task':<44}{'A':>6}{'B':>6}")
    for t in common:
        ra, rb = rate(A[t], best_of), rate(B[t], best_of)
        a_pass += ra
        b_pass += rb
        if ra and rb:
            tbl["A过B过"] += 1
        elif ra and not rb:
            tbl["A过B败"] += 1
        elif not ra and rb:
            tbl["A败B过"] += 1
        else:
            tbl["A败B败"] += 1
        print(f"{t.replace('instance_','')[:42]:<44}{ra:>6}{rb:>6}")

    n = len(common)
    if n == 0:
        print("无共同题目")
        return
    pa, pb = a_pass / n, b_pass / n
    rd = pb - pa
    # 配对 risk difference 的近似 95%CI（基于 discordant）
    b = tbl["A过B败"]
    c = tbl["A败B过"]
    se = math.sqrt(max(b + c - (b - c) ** 2 / n, 0) / n) / n if n else 0
    p = binom_two_sided_p(b, c)
    print(f"\n=== 配对结果（n={n} 题，{'best-of' if best_of else 'pass@1(多数)'}）===")
    print(f"  A 通过 {a_pass}/{n} = {pa:.1%}")
    print(f"  B 通过 {b_pass}/{n} = {pb:.1%}")
    print(f"  效应量 risk difference = {rd*100:+.1f}pp")
    print(f"  2x2: {tbl}")
    print(f"  McNemar 精确检验 p = {p:.4f} {'（显著）' if p < 0.05 else '（不显著）'}")
    z = NormalDist().inv_cdf(0.975)
    lo, hi = rd - z * se, rd + z * se
    print(f"  risk difference 95%CI 约 [{lo*100:+.1f}pp, {hi*100:+.1f}pp]")


if __name__ == "__main__":
    main()
