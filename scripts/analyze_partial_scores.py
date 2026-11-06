"""深度分析：用 verifier 的部分得分（passed/required）重看四组与题库质量。

输出：
  1. 每组 0/1 通过率 vs 部分得分均值（部分得分更敏感）
  2. 题目难度矩阵（40 题 × 5 组 run）
  3. 饱和题 / 死题 / 有区分度的题
  4. 「0/1 失败但部分得分 > 0」的差一点题
  5. patch 特征与部分得分的相关
  6. 成本（token/调用）与产出（部分得分）
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

DS = Path(r"C:\sb\analysis\dataset.json")
SAMPLE = Path(r"C:\develop\sayacode-bench\studies\sample-40-final.json")

GROUPS = [
    ("sayacode", "3.2.7", "SAYACODE 3.2.7"),
    ("sayacode", "3.2.5", "SAYACODE 3.2.5"),
    ("mini-swe", "baseline", "mini-swe"),
    ("claude-code", "baseline", "Claude Code"),
    ("opencode", "baseline", "OpenCode"),
]


def canon(task: str, tasks: dict[str, str]) -> str:
    """把截断的 job task 名映射到完整 task_id。"""
    best = None
    for full, short in tasks.items():
        if full.startswith(task) or short.startswith(task) or task.startswith(short):
            if best is None or len(short) > len(tasks[best]):
                best = full
    return best or task


def main() -> None:
    rows = json.loads(DS.read_text(encoding="utf-8"))
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    # short name -> full id：job stem 是 task_id 去掉 instance_ 前缀并截断
    tasks: dict[str, str] = {}
    for t in sample["tasks"]:
        tid = t["task_id"]
        short = tid.replace("instance_", "")[:34]
        tasks[tid] = short

    for r in rows:
        r["task_canon"] = canon(r["task"], tasks)

    def sel(agent: str, tag: str) -> list[dict]:
        return [r for r in rows if r["agent"] == agent and r["tag"] == tag]

    print("=" * 96)
    print("1. 0/1 通过率 vs 部分得分（部分得分 = 通过测试数 / 要求测试数）")
    print("=" * 96)
    print(f"{'group':16}{'n':>4}{'0/1 通过':>10}{'部分得分均值':>14}{'中位':>8}{'完全通过':>10}{'部分>0且<1':>12}")
    for agent, tag, label in GROUPS:
        rs = sel(agent, tag)
        valid = [r for r in rs if r["partial"] is not None]
        if not valid:
            continue
        rates = [1.0 if (r["partial"] or 0) >= 0.999 else 0.0 for r in valid]
        partials = [r["partial"] for r in valid]
        near = sum(1 for p in partials if 0 < p < 0.999)
        print(
            f"{label:16}{len(valid):>4}{statistics.mean(rates) * 100:>9.1f}%"
            f"{statistics.mean(partials) * 100:>13.1f}%{statistics.median(partials) * 100:>7.1f}%"
            f"{sum(1 for x in rates if x == 1.0):>10}{near:>12}"
        )

    print("\n" + "=" * 96)
    print("2. 题目难度与区分度（跨 5 组的部分得分）")
    print("=" * 96)
    per_task: dict[str, list[float]] = defaultdict(list)
    per_task_01: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["partial"] is None:
            continue
        per_task[r["task_canon"]].append(r["partial"])
        per_task_01[r["task_canon"]].append(1.0 if r["partial"] >= 0.999 else 0.0)

    stats = []
    for task, vals in per_task.items():
        if len(vals) < 3:
            continue
        stats.append(
            {
                "task": task,
                "n": len(vals),
                "mean": statistics.mean(vals),
                "min": min(vals),
                "max": max(vals),
                "sd": statistics.pstdev(vals),
            }
        )
    stats.sort(key=lambda x: x["mean"])

    sat = [s for s in stats if s["mean"] >= 0.999]
    dead = [s for s in stats if s["mean"] <= 0.001]
    mid = [s for s in stats if 0.001 < s["mean"] < 0.999]
    print(f"题数（≥3 次观测）: {len(stats)}")
    print(f"  饱和（全组部分得分=1）: {len(sat):>3}  死题（全组=0）: {len(dead):>3}  中间: {len(mid):>3}")
    print(f"  题级部分得分均值: {statistics.mean([s['mean'] for s in stats]) * 100:.1f}%")
    print(f"  区分度（sd>0 的题）: {sum(1 for s in stats if s['sd'] > 0.02)}")

    print("\n最难的 8 题：")
    for s in stats[:8]:
        print(f"  {s['task'][:52]:52} mean={s['mean'] * 100:5.1f}% min={s['min'] * 100:5.1f} sd={s['sd'] * 100:4.1f}")
    print("\n区分度最大的 8 题（sd 高 = 能拉开差距）：")
    for s in sorted(stats, key=lambda x: -x["sd"])[:8]:
        print(f"  {s['task'][:52]:52} mean={s['mean'] * 100:5.1f}% sd={s['sd'] * 100:4.1f}")

    print("\n" + "=" * 96)
    print("3. 「0/1 失败但部分得分 > 0」的差一点 trial")
    print("=" * 96)
    for agent, tag, label in GROUPS:
        near = [r for r in sel(agent, tag) if r["partial"] and 0 < r["partial"] < 0.999]
        if not near:
            continue
        print(f"\n{label}: {len(near)} 个")
        for r in sorted(near, key=lambda x: -x["partial"])[:6]:
            print(
                f"  {r['task_canon'][:50]:50} r{r['repeat']} "
                f"{r['passed']}/{r['required']} = {r['partial'] * 100:.0f}%"
            )

    print("\n" + "=" * 96)
    print("4. patch 特征 vs 部分得分")
    print("=" * 96)
    withpatch = [r for r in rows if r["patch_bytes"] and r["partial"] is not None]
    print(f"有 patch 的 trial: {len(withpatch)}")
    big = [r for r in withpatch if r["patch_bytes"] > 5000]
    small = [r for r in withpatch if r["patch_bytes"] <= 5000]
    for name, grp in (("patch>5KB", big), ("patch<=5KB", small)):
        if grp:
            print(
                f"  {name:12} n={len(grp):>3} 部分得分均值={statistics.mean([r['partial'] for r in grp]) * 100:5.1f}%"
            )
    multi = [r for r in withpatch if (r["patch_files"] or 0) >= 3]
    single = [r for r in withpatch if (r["patch_files"] or 0) < 3]
    for name, grp in (("≥3 文件", multi), ("<3 文件", single)):
        if grp:
            print(
                f"  {name:12} n={len(grp):>3} 部分得分均值={statistics.mean([r['partial'] for r in grp]) * 100:5.1f}%"
            )

    print("\n" + "=" * 96)
    print("5. 成本 vs 产出（有 usage 的 trial）")
    print("=" * 96)
    print(f"{'group':16}{'n':>4}{'每 trial 输入token':>20}{'输出':>12}{'调用':>8}{'分钟':>8}")
    for agent, tag, label in GROUPS:
        rs = [r for r in sel(agent, tag) if r.get("input_tokens")]
        if not rs:
            continue
        mi = statistics.mean([r["input_tokens"] for r in rs])
        mo = statistics.mean([r["output_tokens"] or 0 for r in rs])
        mc = statistics.mean([r["model_calls"] or 0 for r in rs])
        mm = statistics.mean([r["exec_minutes"] or 0 for r in rs])
        print(f"{label:16}{len(rs):>4}{mi:>20,.0f}{mo:>12,.0f}{mc:>8.0f}{mm:>8.1f}")


if __name__ == "__main__":
    main()
