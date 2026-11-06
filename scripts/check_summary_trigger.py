"""检查 3.2.7 / 3.2.5 是否触发过上下文摘要（单次调用 input_tokens 是否接近/超过触发阈值）。

profile 的 summary_trigger_ratio=0.8、context_length=192000 → 触发线约 153,600 tokens。
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

THRESHOLDS = {
    "profile 触发线 (0.8×192k)": 153_600,
    "50% 上下文": 96_000,
    "100k": 100_000,
}


def scan(root: Path, agent: str) -> list[dict]:
    out = []
    base = root / agent / "jobs"
    if not base.is_dir():
        return out
    for job in sorted(base.iterdir()):
        f = next(job.rglob("usage-details.json"), None)
        if f is None:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        calls = d.get("calls") or []
        inputs = [(c.get("usage") or {}).get("input_tokens") for c in calls]
        inputs = [x for x in inputs if isinstance(x, int)]
        if not inputs:
            continue
        out.append(
            {
                "job": job.name,
                "calls": len(inputs),
                "max_input": max(inputs),
                "last_input": inputs[-1],
                "total_input": sum(inputs),
            }
        )
    return out


def main() -> None:
    for label, root, agent in (
        ("SAYACODE 3.2.7", Path(r"C:\sb\hard\v4-327"), "sayacode"),
        ("SAYACODE 3.2.5", Path(r"C:\sb\hard\v2-325"), "sayacode"),
    ):
        rows = scan(root, agent)
        maxes = [r["max_input"] for r in rows]
        print(f"\n=== {label}（{len(rows)} trial）===")
        print(
            f"单 trial 最大单次 input_tokens: median={statistics.median(maxes):,.0f} "
            f"mean={statistics.mean(maxes):,.0f} max={max(maxes):,}"
        )
        for name, th in THRESHOLDS.items():
            hit = sum(1 for m in maxes if m >= th)
            print(f"  超过 {name:28}: {hit:>3} / {len(maxes)} trial")
        top = sorted(rows, key=lambda r: -r["max_input"])[:3]
        for r in top:
            print(f"  最高: {r['job'][:52]:52} max={r['max_input']:,} calls={r['calls']}")


if __name__ == "__main__":
    main()
