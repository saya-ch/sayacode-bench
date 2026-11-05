"""组成「大评测集」：从四个题组按分层配额抽样，单次重复，冻结成可复现清单。

设计（docs/LARGE-EVAL-SET.md）：
  - 不重复：repeats=1，把重复的资源换成题量，解决 n=40 的功效不足；
  - 走量：320 题，按来源 + 层内特征分层；
  - 每套题单独统计：每个 task 带 `source` / `stratum`，并额外输出按 source 的分片文件，
    让每个题组能用自己的 tasks_root 单独跑、单独汇总。

用法::

    uv run --no-sync python scripts/compose_large_sample.py \
        --out-dir studies --name large-sample-v1 --seed 20261105-large-eval

输出：
    <name>.json                     总集（带 source）
    <name>-<source>.json            4 个分片，可直接喂 run_formal_240.py --sample
    <name>-strata.json             分层配额报告
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path(r"C:\sb")
PRO_TASKS = HOME / r"tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
TB_TASKS = HOME / r"s\terminal-bench-2.1-7131e4375048a0e408a8fb404b5f499d726b695b\tasks"
BENCH = HOME / r"tmp\benchmarks"

# 配额：本地成本最低的 Pro V2 与判别力最强的 ProMax 为主，EVO 做难度上限，TB 只留形态补充。
# 用户定稿 100 题（单次重复）：单组约 4–5 小时，四组约 18 小时，可过夜/分批完成。
QUOTAS = {"pro-v2": 40, "promax": 35, "swe-evo": 15, "tb21": 10}


def _rank(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def _field(text: str, name: str) -> str:
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "unknown"


def _int_field(text: str, name: str) -> int:
    m = re.search(rf"^{name}\s*=\s*(\d+)", text, re.M)
    return int(m.group(1)) if m else 0


def load_pro_v2(seed: str) -> list[dict]:
    out = []
    for d in sorted(p for p in PRO_TASKS.iterdir() if p.is_dir()):
        tid = d.name
        repo = tid.split("__", 1)[1].split("-", 1)[0] if "__" in tid else "unknown"
        out.append(
            {
                "task_id": f"pro-v2/{tid}",
                "native_id": tid,
                "source": "pro-v2",
                "repo": repo,
                "stratum": repo,
                "category": "debugging",
                "difficulty": "medium",
                "memory_mb": 0,
            }
        )
    return out


def load_promax() -> list[dict]:
    rows = json.loads((BENCH / "promax-tasks.json").read_text(encoding="utf-8"))
    out = []
    for r in rows:
        patch = r.get("patch") or ""
        files = len([line for line in patch.splitlines() if line.startswith("+++ b/")])
        bucket = "files<=5" if files <= 5 else "files6-15" if files <= 15 else "files>15"
        lang = str(r.get("language") or "unknown")
        out.append(
            {
                "task_id": f"promax/{r['instance_id']}",
                "native_id": r["instance_id"],
                "source": "promax",
                "repo": r.get("repo") or "unknown",
                "stratum": f"{lang}:{bucket}",
                "language": lang,
                "file_count": files,
                "difficulty": "refactor",
                "memory_mb": 0,
            }
        )
    return out


def load_evo() -> list[dict]:
    rows = json.loads((BENCH / "swe-evo-rows.json").read_text(encoding="utf-8"))
    out = []
    for r in rows:
        iid = str(r.get("instance_id") or r.get("instance_id_swe") or "")
        repo = str(r.get("repo") or "unknown")
        patch = r.get("patch") or ""
        files = len([line for line in patch.splitlines() if line.startswith("+++ b/")])
        out.append(
            {
                "task_id": f"swe-evo/{iid}",
                "native_id": iid,
                "source": "swe-evo",
                "repo": repo,
                "stratum": repo,
                "file_count": files,
                "difficulty": "long-horizon",
                "memory_mb": 0,
            }
        )
    return out


def load_tb21() -> list[dict]:
    out = []
    for d in sorted(p for p in TB_TASKS.iterdir() if p.is_dir()):
        cfg = d / "task.toml"
        if not cfg.is_file():
            continue
        text = cfg.read_text(encoding="utf-8", errors="replace")
        mem = _int_field(text, "memory_mb")
        if mem > 4096:  # 硬件上限：WSL 7GB，排除 >4GB 的题
            continue
        out.append(
            {
                "task_id": f"tb21/{d.name}",
                "native_id": d.name,
                "source": "tb21",
                "repo": d.name,
                "stratum": _field(text, "category"),
                "category": _field(text, "category"),
                "difficulty": _field(text, "difficulty"),
                "memory_mb": mem,
            }
        )
    return out


def stratified_sample(items: list[dict], quota: int, seed: str, *, cap: int | None = None) -> list[dict]:
    """按层大小比例分配配额（单层可设上限），层内按 hash(seed, id) 确定性排序取前 k。"""
    by: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by[item["stratum"]].append(item)
    for key in by:
        by[key].sort(key=lambda x: _rank(seed, x["task_id"]))

    # 层数 >= 配额时（如 tb21 有 16 类但只抽 10 题），按比例分配会每层至少 1 个而超配额，
    # 回退逻辑又找不到可减的层而卡死。改为按 seed 选出 quota 个层、每层 1 题。
    if len(by) >= quota:
        chosen = sorted(by, key=lambda k: _rank(seed, f"stratum:{k}"))[:quota]
        return sorted((by[k][0] for k in chosen), key=lambda x: _rank(seed, x["task_id"]))

    # 初始按容量比例分配
    total = len(items)
    alloc = {
        key: min(len(v), max(1, math.floor(quota * len(v) / total)))
        for key, v in by.items()
    }
    if cap:
        alloc = {k: min(v, cap) for k, v in alloc.items()}
    # 补齐到 quota：按 (当前分配/层容量) 最小者优先，逐轮 +1
    keys = sorted(by)
    while sum(alloc.values()) < quota:
        progressed = False
        for key in sorted(keys, key=lambda k: (alloc[k] / max(1, len(by[k])), k)):
            limit = min(len(by[key]), cap or len(by[key]))
            if alloc[key] < limit:
                alloc[key] += 1
                progressed = True
                if sum(alloc.values()) >= quota:
                    break
        if not progressed:
            break
    # 超出则按差额最大的层回退
    while sum(alloc.values()) > quota:
        for key in sorted(keys, key=lambda k: (-alloc[k], k)):
            if alloc[key] > 1:
                alloc[key] -= 1
                break

    picked: list[dict] = []
    for key in keys:
        picked.extend(by[key][: alloc[key]])
    return sorted(picked, key=lambda x: _rank(seed, x["task_id"]))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", default="large-sample-v1")
    p.add_argument("--seed", default="20261105-large-eval")
    args = p.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    loaders = {
        "pro-v2": load_pro_v2,
        "promax": load_promax,
        "swe-evo": load_evo,
        "tb21": load_tb21,
    }
    all_tasks: list[dict] = []
    report: dict[str, dict] = {}
    for source, loader in loaders.items():
        pool = loader(args.seed) if source == "pro-v2" else loader()
        quota = min(QUOTAS[source], len(pool))
        cap = 10 if source == "swe-evo" else None  # dvc 占 26/48，限上限保多样性
        picked = stratified_sample(pool, quota, args.seed, cap=cap)
        all_tasks.extend(picked)
        report[source] = {
            "pool": len(pool),
            "quota": quota,
            "picked": len(picked),
            "strata": dict(Counter(x["stratum"] for x in picked)),
        }
        shard = out_dir / f"{args.name}-{source}.json"
        shard.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "name": f"{args.name}-{source}",
                    "source": source,
                    "seed": args.seed,
                    "repeats": 1,
                    "size": len(picked),
                    "tasks": picked,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"{source:10} pool={len(pool):>4} quota={quota:>3} picked={len(picked):>3}  -> {shard.name}")

    all_tasks.sort(key=lambda x: _rank(args.seed, x["task_id"]))
    master = out_dir / f"{args.name}.json"
    master.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "name": args.name,
                "seed": args.seed,
                "repeats": 1,
                "size": len(all_tasks),
                "sources": QUOTAS,
                "tasks": all_tasks,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / f"{args.name}-strata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n总集 {len(all_tasks)} 题 -> {master}")
    print(f"分层报告 -> {out_dir / (args.name + '-strata.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
