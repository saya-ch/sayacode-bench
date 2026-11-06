"""行为 × 结果：失败 trial 与成功 trial 的行为差异，以及按工具的耗时/输出体量。"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

DS = Path(r"C:\sb\analysis\dataset.json")
BEH = Path(r"C:\sb\analysis\behavior.json")
AUDIT_ROOT = Path(r"C:\sb\hard\v4-327\sayacode\jobs")


def main() -> None:
    ds = json.loads(DS.read_text(encoding="utf-8"))
    beh = json.loads(BEH.read_text(encoding="utf-8"))

    # 用 (agent, tag, task, repeat) 对齐；behavior 的 task 是截断名
    def key(agent, tag, task, rep):
        return (agent, tag, task[:34].replace("instance_", ""), rep)

    partial = {key(r["agent"], r["tag"], r["task"], r["repeat"]): r["partial"] for r in ds}

    rows = []
    for b in beh:
        k = key(b["agent"], b["tag"], b["task"], b["repeat"])
        p = partial.get(k)
        if p is None:
            continue
        b["partial"] = p
        rows.append(b)

    print("=" * 96)
    print("1. 失败 vs 成功 trial 的行为差异（合并 5 组）")
    print("=" * 96)
    fail = [r for r in rows if r["partial"] < 0.999]
    ok = [r for r in rows if r["partial"] >= 0.999]
    for name, grp in (("成功", ok), ("失败", fail)):
        if not grp:
            continue
        print(
            f"{name} n={len(grp):>3}  工具调用={statistics.mean([r['tool_calls'] for r in grp]):6.1f}  "
            f"探索={statistics.mean([r['explore'] for r in grp]):6.1f}  编辑={statistics.mean([r['edit'] for r in grp]):5.1f}  "
            f"执行={statistics.mean([r['exec'] for r in grp]):5.1f}  "
            f"模型调用={statistics.mean([r.get('model_calls') or r.get('steps') or 0 for r in grp]):5.1f}"
        )

    print("\n" + "=" * 96)
    print("2. 每组内部的失败/成功差异")
    print("=" * 96)
    for gkey in sorted({f"{r['agent']} {r['tag']}" for r in rows}):
        gs = [r for r in rows if f"{r['agent']} {r['tag']}" == gkey]
        gf = [r for r in gs if r["partial"] < 0.999]
        go = [r for r in gs if r["partial"] >= 0.999]
        if not gf or not go:
            continue
        print(
            f"{gkey:22} 失败 {len(gf):>2} / 成功 {len(go):>2}  "
            f"调用 {statistics.mean([r['tool_calls'] for r in gf]):5.1f} vs {statistics.mean([r['tool_calls'] for r in go]):5.1f}  "
            f"编辑 {statistics.mean([r['edit'] for r in gf]):4.1f} vs {statistics.mean([r['edit'] for r in go]):4.1f}"
        )

    print("\n" + "=" * 96)
    print("3. sayacode 按工具的耗时与输出体量（audit.jsonl）")
    print("=" * 96)
    dur: dict[str, list[float]] = defaultdict(list)
    chars: dict[str, list[int]] = defaultdict(list)
    for job in sorted(AUDIT_ROOT.iterdir()):
        f = next(job.rglob("audit.jsonl"), None)
        if f is None:
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if "tool.completed" not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            d = e.get("details") or {}
            t = str(d.get("tool_name"))
            if isinstance(d.get("duration_ms"), (int, float)):
                dur[t].append(float(d["duration_ms"]))
            if isinstance(d.get("output_characters"), int):
                chars[t].append(d["output_characters"])
    print(f"{'tool':24}{'n':>6}{'耗时中位ms':>12}{'p95 ms':>10}{'输出中位':>10}{'输出max':>10}")
    for t in sorted(dur, key=lambda x: -statistics.median(dur[x])):
        ds_ = sorted(dur[t])
        p95 = ds_[int(len(ds_) * 0.95)] if ds_ else 0
        print(
            f"{t:24}{len(dur[t]):>6}{statistics.median(dur[t]):>12.0f}{p95:>10.0f}"
            f"{statistics.median(chars[t]) if chars[t] else 0:>10.0f}{max(chars[t]) if chars[t] else 0:>10}"
        )


if __name__ == "__main__":
    main()
