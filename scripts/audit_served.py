"""审计 Magpie 路由日志的 served 分布（按 agent/User-Agent 精确过滤，排除本机 DSH）。

背景（AGENTS.md 坑 38）：未过滤 DSH 请求会污染统计；「served 全是 hy3、零 deepseek」
这个结论过去只有一次手工统计、没有脚本。本脚本把该统计固化下来：

  python scripts/audit_served.py --source C:\\sb\\magpie-export\\config\\routing \
      --json-out docs/evidence/served-distribution-20261107.json

数据源是 Magpie 的 routing 日志（`*.jsonl` / `*.jsonl.gz`），每条记录含
`time`、`agent`（即请求方 User-Agent 的归一化标识）、`served`（模型名）、
`usage[].provider`（额度池/provider）。**本脚本不修改任何数据。**

口径：
  - agent 分类按 `agent` 字段精确匹配（表见 AGENT_LABELS），未知值归 unknown；
  - `dsh*` 一律排除（本机 DSH 请求，不是评测）；
  - served 分布按模型名归一化：hy3 / hy3-x / deepseek / glm / other / unknown；
  - provider 分布按 `usage[].provider` 统计（workbuddy / workbuddy-ai / ...）；
  - 时间窗按记录 `time` 与 --since/--until 比较（ISO 8601，缺省时区按 +08:00）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_VERSION = "1.0.0"
DEFAULT_SOURCE = r"C:\sb\magpie-export\config\routing"
TZ = timezone(timedelta(hours=8))

# agent 字段（User-Agent 归一化）→ 展示名；dsh* 单独处理。
AGENT_LABELS = {
    "langchain-anthropic": "SAYACODE",
    "litellm": "mini-swe",
    "claude": "Claude Code",
    "claude-code": "Claude Code",
    "opencode": "OpenCode",
    "codex": "Codex",
}
DSH_AGENTS = ("dsh", "dsh-mcp-client", "dsh-subagent", "dsh-worker")


def classify_agent(agent: str) -> str:
    a = (agent or "").strip()
    if a in AGENT_LABELS:
        return AGENT_LABELS[a]
    if a.startswith("dsh"):
        return "DSH"
    return "unknown"


def classify_served(served: str | None) -> str:
    s = (served or "").strip().lower()
    if not s:
        return "unknown"
    if s.startswith("hy3-x") or s == "hy3-x":
        return "hy3-x"
    if s.startswith("hy3"):
        return "hy3"
    if "deepseek" in s:
        return "deepseek"
    if "glm" in s:
        return "glm"
    return "other"


def parse_time(value: str) -> datetime:
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        dt = datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def parse_bound(value: str | None, *, end: bool) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if len(v) == 10:  # YYYY-MM-DD
        return parse_time(v + ("T23:59:59" if end else "T00:00:00"))
    return parse_time(v)


def iter_records(paths: list[Path]):
    for p in paths:
        opener = gzip.open if p.name.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def collect_paths(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.is_dir():
        return []
    return sorted(p for p in source.iterdir()
                  if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.gz")))


def audit(source: Path, since: str | None, until: str | None) -> dict:
    paths = collect_paths(source)
    lo = parse_bound(since, end=False)
    hi = parse_bound(until, end=True)

    per_agent: dict[str, dict] = defaultdict(lambda: {
        "records": 0, "served": Counter(), "providers": Counter(), "first": None, "last": None})
    file_meta: list[dict] = []
    total = 0
    excluded_dsh = 0

    for p in paths:
        n = 0
        first = last = None
        for rec in iter_records([p]):
            t = rec.get("time")
            try:
                dt = parse_time(t) if t else None
            except (ValueError, TypeError):
                dt = None
            if dt is not None:
                if lo is not None and dt < lo:
                    continue
                if hi is not None and dt > hi:
                    continue
                first = first or dt
                last = dt
            label = classify_agent(str(rec.get("agent") or ""))
            if label == "DSH":
                excluded_dsh += 1
                continue
            d = per_agent[label]
            d["records"] += 1
            d["served"][classify_served(rec.get("served"))] += 1
            for u in rec.get("usage") or []:
                d["providers"][str(u.get("provider") or "unknown")] += 1
            if dt is not None:
                d["first"] = d["first"] or dt
                d["last"] = dt
            n += 1
            total += 1
        file_meta.append({
            "path": str(p),
            "records_counted": n,
            "size_bytes": p.stat().st_size,
            "first_time": first.isoformat() if first else None,
            "last_time": last.isoformat() if last else None,
        })

    agents_out = {}
    for label, d in sorted(per_agent.items()):
        agents_out[label] = {
            "records": d["records"],
            "served": dict(d["served"].most_common()),
            "providers": dict(d["providers"].most_common()),
            "first_time": d["first"].isoformat() if d["first"] else None,
            "last_time": d["last"].isoformat() if d["last"] else None,
        }
    by_served = Counter()
    for d in agents_out.values():
        by_served.update(d["served"])
    return {
        "schema_version": 1,
        "script": {"path": "scripts/audit_served.py", "version": SCRIPT_VERSION},
        "source": {"input": str(source), "files": file_meta},
        "window": {"since": since, "until": until, "timezone": "+08:00"},
        "totals": {"records": total, "excluded_dsh": excluded_dsh, "by_served": dict(by_served.most_common())},
        "agents": agents_out,
    }


def compare_with_claims(result: dict, claimed_records: int = 42681, claimed_zero_deepseek: bool = True) -> dict:
    """把实测与文档声称对比；不为了迎合声称而调整过滤条件。"""
    observed = result["totals"]["records"]
    deepseek = result["totals"]["by_served"].get("deepseek", 0)
    reasons = []
    if observed != claimed_records:
        reasons.append(
            f"记录数不一致：文档声称 {claimed_records} 条，本数据源在给定时间窗内实测 {observed} 条"
        )
        files = result["source"]["files"]
        if files:
            reasons.append(
                "数据源覆盖范围：" + ", ".join(
                    f"{Path(f['path']).name}={f['records_counted']}" for f in files)
            )
        reasons.append("本地导出只到 2026-10-29 18:40；2026-10-30 之后的 routing 日志不在导出内，"
                       "因此无法在当前机器上复核 42681 条")
    if claimed_zero_deepseek and deepseek > 0:
        reasons.append(
            f"served 中出现 deepseek 模型 {deepseek} 条；需确认这些记录是否落在声称的评测窗口内"
            "（若不在，不能据此推翻原结论；若在，原结论「零 deepseek」需要修订）"
        )
    return {
        "claims": {"records": claimed_records, "zero_deepseek": claimed_zero_deepseek},
        "observed": {"records": observed, "deepseek": deepseek},
        "records_match": observed == claimed_records,
        "zero_deepseek_holds_in_observed_window": deepseek == 0,
        "reasons": reasons,
    }


def render_table(result: dict) -> str:
    lines = ["| agent | records | served 分布 | provider 分布 |",
             "|---|---:|---|---|"]
    for label, d in result["agents"].items():
        served = ", ".join(f"{k}={v}" for k, v in d["served"].items()) or "-"
        prov = ", ".join(f"{k}={v}" for k, v in d["providers"].items()) or "-"
        lines.append(f"| {label} | {d['records']} | {served} | {prov} |")
    lines.append("")
    lines.append(f"合计 {result['totals']['records']} 条（已排除 DSH {result['totals']['excluded_dsh']} 条）；"
                 f"served 总计：{result['totals']['by_served']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="routing 日志目录或单个 .jsonl/.jsonl.gz 文件")
    ap.add_argument("--since", default=None, help="ISO 8601，如 2026-10-31 或 2026-10-31T00:00:00+08:00")
    ap.add_argument("--until", default=None, help="ISO 8601，缺省按当天 23:59:59（+08:00）")
    ap.add_argument("--json-out", default=None, help="写 JSON 的路径；缺省只打印")
    ap.add_argument("--claimed-records", type=int, default=42681)
    ap.add_argument("--allow-deepseek-in-claims", action="store_true",
                    help="若文档声称零 deepseek 为假，仍继续（仅影响 comparison 文案）")
    args = ap.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"数据源不存在：{source}", file=sys.stderr)
        print("已尝试：C:\\sb\\magpie-export\\config\\routing（含 2026-10-26/27/28/29 四个文件）", file=sys.stderr)
        return 2
    result = audit(source, args.since, args.until)
    result["comparison"] = compare_with_claims(
        result, args.claimed_records, not args.allow_deepseek_in_claims)
    text = render_table(result)
    print(text)
    print("\n对比文档声称：")
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=1))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        result["generated_at"] = datetime.now(TZ).isoformat()
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nJSON → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
