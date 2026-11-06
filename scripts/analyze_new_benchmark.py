"""SWE-EVO 题库难度画像，并与旧 40 题（SWE-bench Pro V2 子集）对比。

难度代理指标：gold patch 改动文件数 / 行数、f2p 数量、test_patch 体量。
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

EVO = Path(r"C:\sb\tmp\benchmarks\swe-evo-rows.json")
PRO = Path(r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks")
SAMPLE = Path(r"C:\develop\sayacode-bench\studies\sample-40-final.json")


def patch_stats(text: str) -> tuple[int, int]:
    """返回 (文件数, 增删行数)。"""
    if not text:
        return 0, 0
    files = len(re.findall(r"^diff --git ", text, re.M))
    added = len(re.findall(r"^\+[^+]", text, re.M))
    removed = len(re.findall(r"^-[^-]", text, re.M))
    return files, added + removed


def evo_stats() -> dict:
    rows = json.loads(EVO.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        files, lines = patch_stats(r.get("patch") or "")
        tp_files, tp_lines = patch_stats(r.get("test_patch") or "")
        out.append(
            {
                "id": r["instance_id"],
                "repo": r["repo"],
                "files": files,
                "lines": lines,
                "f2p": len(r.get("FAIL_TO_PASS") or []),
                "tp_files": tp_files,
                "tp_lines": tp_lines,
                "ghcr": "epoch-research" in (r.get("image") or ""),
            }
        )
    return {"rows": out}


def pro_stats() -> dict:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    ids = {t["task_id"] for t in sample["tasks"]}
    out = []
    for d in sorted(PRO.iterdir()):
        if not d.is_dir() or d.name not in ids:
            continue
        gold = d / "solution" / "gold_patch.diff"
        tp = d / "tests" / "test_patch.patch"
        files, lines = patch_stats(gold.read_text(encoding="utf-8", errors="replace") if gold.is_file() else "")
        tp_files, tp_lines = patch_stats(tp.read_text(encoding="utf-8", errors="replace") if tp.is_file() else "")
        out.append({"id": d.name, "files": files, "lines": lines, "tp_files": tp_files, "tp_lines": tp_lines})
    return {"rows": out}


def describe(name: str, rows: list[dict]) -> None:
    if not rows:
        print(f"{name}: 无数据")
        return
    files = [r["files"] for r in rows]
    lines = [r["lines"] for r in rows]
    tp_lines = [r["tp_lines"] for r in rows]
    print(
        f"{name:26} n={len(rows):>3}  "
        f"文件 中位={statistics.median(files):>5.0f} 均值={statistics.mean(files):>6.1f} max={max(files):>4}  "
        f"行数 中位={statistics.median(lines):>6.0f} 均值={statistics.mean(lines):>7.1f} max={max(lines):>5}"
    )
    print(f"{'':26} test_patch 行数 中位={statistics.median(tp_lines):>7.0f} max={max(tp_lines):>6}")


def main() -> None:
    evo = evo_stats()["rows"]
    pro = pro_stats()["rows"]

    print("=" * 110)
    print("1. 难度画像对比（gold patch 改动量）")
    print("=" * 110)
    describe("SWE-EVO 48 题（全部）", evo)
    describe("SWE-EVO（非 ghcr 42 题）", [r for r in evo if not r["ghcr"]])
    describe("SWE-bench Pro V2 旧 40 题", pro)

    print("\n" + "=" * 110)
    print("2. SWE-EVO 按 repo 分布")
    print("=" * 110)
    by_repo: dict[str, list[dict]] = {}
    for r in evo:
        by_repo.setdefault(r["repo"], []).append(r)
    for repo, rs in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        files = statistics.median([r["files"] for r in rs])
        lines = statistics.median([r["lines"] for r in rs])
        print(f"  {repo:26} n={len(rs):>3}  文件中位={files:>5.0f}  行数中位={lines:>6.0f}")

    print("\n" + "=" * 110)
    print("3. 改动文件数分布（难度分档）")
    print("=" * 110)
    buckets: Counter[str] = Counter()
    for r in evo:
        f = r["files"]
        b = "1-2" if f <= 2 else "3-5" if f <= 5 else "6-10" if f <= 10 else "11-30" if f <= 30 else ">30"
        buckets[b] += 1
    for b in ("1-2", "3-5", "6-10", "11-30", ">30"):
        print(f"  {b:>6} 文件: {buckets.get(b, 0):>3} 题")

    print("\n" + "=" * 110)
    print("4. f2p 数量分布（判定粒度）")
    print("=" * 110)
    f2p = [r["f2p"] for r in evo]
    print(f"  中位={statistics.median(f2p):.0f} 均值={statistics.mean(f2p):.1f} max={max(f2p)}")
    print(f"  f2p=1 的题: {sum(1 for x in f2p if x == 1)} 题（单断言，判定最脆）")
    print(f"  f2p<=4 的题: {sum(1 for x in f2p if x <= 4)} 题")
    print(f"  f2p>20 的题: {sum(1 for x in f2p if x > 20)} 题")


if __name__ == "__main__":
    main()
