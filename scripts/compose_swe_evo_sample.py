"""从基线验证结果生成新题库的评测 sample。

只纳入 verdict=usable 的题；task_id 用 task 目录名（Harbor 按目录名定位）。
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

BASELINE = Path(r"C:\sb\analysis\swe-evo-baseline.json")
TASKS = Path(r"C:\sb\newset\swe-evo\tasks")
OUT = Path(r"C:\sb\newset\swe-evo\sample-pilot.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--include", nargs="*", default=None, help="额外强制纳入的 task 目录名")
    args = ap.parse_args()

    rows = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    usable = [r for r in rows if r.get("verdict") == "usable"]
    names = [r["task"] for r in usable]

    if args.include:
        names += [n for n in args.include if n not in names]

    tasks = []
    for n in names:
        d = TASKS / n
        if not d.is_dir():
            print(f"skip missing dir: {n}")
            continue
        repo = n.split("__")[1].rsplit("_", 2)[0] if "__" in n else "?"
        tasks.append({"task_id": n, "repo": repo})

    sample = {
        "schema_version": 1,
        "date": date.today().isoformat(),
        "benchmark": "swe-evo",
        "purpose": "新题库接入端到端验证（基线验证可用题）",
        "seed": 20261106,
        "size": len(tasks),
        "note": "由 scripts/verify_task_baseline.py 的 usable 结果生成；p2p 已按基线过滤",
        "tasks": tasks,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(tasks)} 题 → {out}")
    for t in tasks:
        print("  ", t["task_id"], t["repo"])


if __name__ == "__main__":
    main()
