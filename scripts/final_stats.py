"""从已有汇总产物重算题级统计，不重新判分、不重跑模型。

用法::

    uv run --no-sync python scripts/final_stats.py --summary C:\\sb\\hard\\formal-240\\FINAL-SUMMARY.json
    uv run --no-sync python scripts/final_stats.py --root C:\\sb\\hard\\formal-240

统计单位是**任务块**（一题一个观察值）：题级 Wilson、任务块 bootstrap、仓库簇 bootstrap、
pass@2/pass^2 的区间、题级 McNemar。区间参数固定 ``samples=10000``、``seed=20261022``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sayacode_bench.formal import summarize  # noqa: E402
from sayacode_bench.formal_stats import summarize_stats  # noqa: E402

DEFAULT_ROOT = Path(r"C:\sb\hard\formal-240")


def _load_summary(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"汇总文件不是 JSON 对象：{path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="已有 FINAL-SUMMARY.json；与 --root 二选一",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_FORMAL_ROOT", DEFAULT_ROOT)),
        help="结果根目录（当 --summary 不存在时直接扫描）",
    )
    parser.add_argument("--sample", type=Path, default=ROOT / "studies" / "sample-40-final.json")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--out", type=Path, default=None, help="把统计写成 JSON；默认只打印")
    args = parser.parse_args()

    summary_path = args.summary
    if summary_path is None and (args.root / "FINAL-SUMMARY.json").is_file():
        summary_path = args.root / "FINAL-SUMMARY.json"
    if summary_path is not None and summary_path.is_file():
        summary = _load_summary(summary_path)
        if "agents" not in summary:
            raise SystemExit(f"汇总文件缺少 agents 段：{summary_path}")
        repeats = int(summary.get("repeats", args.repeats))
        print(f"读取 {summary_path}")
    else:
        if not args.root.is_dir():
            parser.error(f"结果根目录不存在：{args.root}")
        summary = summarize(args.root, sample=args.sample, repeats=args.repeats)
        repeats = args.repeats
        print(f"扫描 {args.root}（未找到 FINAL-SUMMARY.json）")

    stats = summarize_stats({**summary, "repeats": repeats})
    payload = {
        "source": str(summary_path) if summary_path is not None else str(args.root),
        "repeats": repeats,
        "stats": stats,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"统计已写 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
