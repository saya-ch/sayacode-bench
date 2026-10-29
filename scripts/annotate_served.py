"""给已有 trial 标注实际命中的 served/provider（从 Magpie usage.jsonl 按时间窗关联）。

用法: python scripts/annotate_served.py <jobs目录> [usage.jsonl路径]
对每个 trial：读取 result.json 的 started_at/finished_at，取窗口内的 usage 记录，
统计 served/provider 分布，写入该 trial 的 served-distribution.json，并打印汇总。
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

USAGE_DEFAULT = Path.home() / ".config" / "magpie" / "usage.jsonl"
AGENT_FILTER = "langchain-anthropic"


def parse_t(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def load_usage(path):
    out = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(ln)
        except Exception:
            continue
        t = parse_t(d.get("t"))
        if t:
            out.append((t, d.get("served"), d.get("provider"), d.get("agent")))
    return out


def main():
    jobs = Path(sys.argv[1])
    usage_path = Path(sys.argv[2]) if len(sys.argv) > 2 else USAGE_DEFAULT
    usage = load_usage(usage_path)
    agg_all = defaultdict(int)
    n_trials = 0
    for start in jobs.rglob("instance_*"):
        if not start.is_dir():
            continue
        res = start / "result.json"
        if not res.is_file():
            continue
        try:
            data = json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            continue
        t0, t1 = parse_t(data.get("started_at")), parse_t(data.get("finished_at"))
        if not t0 or not t1:
            continue
        dist = defaultdict(int)
        for t, served, prov, agent in usage:
            if t0 <= t <= t1 and agent == AGENT_FILTER:
                dist[f"{served}/{prov}"] += 1
                agg_all[f"{served}/{prov}"] += 1
        (start / "served-distribution.json").write_text(
            json.dumps({"window": [str(t0), str(t1)], "served": dict(dist)}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        n_trials += 1
        top = sorted(dist.items(), key=lambda x: -x[1])[:3]
        print(f"  {start.name[:44]:<46} {dict(top)}")
    print(f"\n标注 {n_trials} 个 trial")
    print("总 served 分布:", dict(sorted(agg_all.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
