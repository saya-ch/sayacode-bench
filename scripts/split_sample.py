"""把冻结题集按「重题」拆成两个分片，用于分阶段跑批。

动机：Claude Code 在 vuls（Go 大项目全量编译）单题上容器内存可冲到 3.3GB，
并发 2 时两个重题同跑会打爆 WSL 内存上限（.wslconfig memory=7GB），
表现为跑批进程被宿主 OOM 静默杀死（日志末尾只剩心跳行、无 traceback）。

本脚本从 studies/sample-40-final.json 派生分片，保证：
  - 题集内容与顺序不变（只是过滤）；
  - 每个 part 记录来源与筛选规则，可随时合并回原题集复核。

用法::

    uv run --no-sync python scripts/split_sample.py \\
        --sample studies/sample-40-final.json \\
        --out-dir C:\\sb\\tmp\\claude-parts \\
        --heavy-repo future-architect
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--heavy-repo",
        nargs="+",
        required=True,
        help="归入重题分片的 repo 名（该分片用并发 1 跑）",
    )
    parser.add_argument("--heavy-name", default="heavy")
    parser.add_argument("--light-name", default="light")
    args = parser.parse_args()

    source = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    tasks = source["tasks"]
    heavy = [t for t in tasks if t.get("repo") in set(args.heavy_repo)]
    light = [t for t in tasks if t.get("repo") not in set(args.heavy_repo)]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, subset, note in (
        (args.light_name, light, f"排除重题 repo {sorted(set(args.heavy_repo))}；并发 2 跑"),
        (args.heavy_name, heavy, f"仅重题 repo {sorted(set(args.heavy_repo))}；并发 1 跑"),
    ):
        payload = {
            "schema_version": source.get("schema_version", 1),
            "date": source.get("date", ""),
            "benchmark": source.get("benchmark", ""),
            "purpose": f"{source.get('purpose','')}（分片：{note}）",
            "seed": source.get("seed", ""),
            "size": len(subset),
            "derived_from": str(args.sample),
            "split_rule": note,
            "tasks": subset,
        }
        path = out_dir / f"sample-{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path}: {len(subset)} 题 -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
