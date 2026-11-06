"""行为层分析：工具调用结构、探索/编辑/执行配比、token 与产出的关系。

数据源：
  sayacode      → agent/sayacode/audit.jsonl（tool.completed: tool_name/duration/output_characters/error_type）
  三个基线      → ATIF-v1.7 trajectory.json（steps[].tool_calls[].function_name + final_metrics）

输出：C:\\sb\\analysis\\behavior.json + 控制台报告
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from sayacode_bench import trialdir

V2 = Path(r"C:\sb\hard\v2-325")
V4 = Path(r"C:\sb\hard\v4-327")
OUT = Path(r"C:\sb\analysis\behavior.json")

GROUPS = [
    ("sayacode", V4, "3.2.7"),
    ("sayacode", V2, "3.2.5"),
    ("mini-swe", V2, "baseline"),
    ("claude-code", V2, "baseline"),
    ("opencode", V2, "baseline"),
]

EDIT = {
    "write_file",
    "search_replace",
    "Edit",
    "Write",
    "MultiEdit",
    "str_replace_editor",
    "apply_patch",
    "edit",
}
EXPLORE = {
    "read_file",
    "grep_search",
    "list_directory",
    "Read",
    "Grep",
    "Glob",
    "LS",
    "NotebookRead",
    "read",
    "grep",
    "list",
    "search",
    "find",
    "view",
}
EXEC = {"execute_command_tool", "Bash", "bash", "shell", "terminal", "run_command"}


def parse_job(name: str) -> tuple[str, int] | None:
    m = re.search(r"-r([12])$", name)
    if not m:
        return None
    stem = name[: m.start()]
    if stem.startswith("verify-"):
        stem = stem[len("verify-") :]
    for a in ("sayacode", "mini-swe", "claude-code", "opencode"):
        if stem.startswith(a + "-"):
            stem = stem[len(a) + 1 :]
            break
    return stem[:34], int(m.group(1))


def cat(tool: str) -> str:
    if tool in EDIT:
        return "edit"
    if tool in EXPLORE:
        return "explore"
    if tool in EXEC:
        return "exec"
    return "other"


def from_sayacode_audit(inner: Path) -> dict:
    f = next(inner.rglob("audit.jsonl"), None)
    if f is None:
        return {}
    tools: Counter[str] = Counter()
    errors = 0
    outchars = 0
    durations = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"tool.completed"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        d = e.get("details") or {}
        tools[str(d.get("tool_name"))] += 1
        if d.get("error_type"):
            errors += 1
        outchars += int(d.get("output_characters") or 0)
        if isinstance(d.get("duration_ms"), (int, float)):
            durations.append(d["duration_ms"])
    if not tools:
        return {}
    return {
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "tool_errors": errors,
        "output_chars": outchars,
        "tool_ms_median": statistics.median(durations) if durations else None,
        "edit": sum(v for k, v in tools.items() if cat(k) == "edit"),
        "explore": sum(v for k, v in tools.items() if cat(k) == "explore"),
        "exec": sum(v for k, v in tools.items() if cat(k) == "exec"),
    }


def from_atif(inner: Path) -> dict:
    f = next(inner.rglob("trajectory.json"), None)
    if f is None:
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tools: Counter[str] = Counter()
    steps = d.get("steps") or []
    for s in steps:
        for tc in s.get("tool_calls") or []:
            tools[str(tc.get("function_name"))] += 1
    fm = d.get("final_metrics") or {}
    return {
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "steps": len(steps),
        "prompt_tokens": fm.get("total_prompt_tokens"),
        "completion_tokens": fm.get("total_completion_tokens"),
        "cached_tokens": fm.get("total_cached_tokens"),
        "cost_usd": fm.get("total_cost_usd"),
        "edit": sum(v for k, v in tools.items() if cat(k) == "edit"),
        "explore": sum(v for k, v in tools.items() if cat(k) == "explore"),
        "exec": sum(v for k, v in tools.items() if cat(k) == "exec"),
    }


def usage_of(inner: Path, agent: str) -> dict:
    for cand in inner.rglob("usage-details.json"):
        try:
            d = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return {
            "model_calls": d.get("model_calls"),
            "input_tokens": d.get("input_tokens"),
            "output_tokens": d.get("output_tokens"),
            "cached_tokens": d.get("cache_read_input_tokens"),
        }
    return {}


def main() -> None:
    rows: list[dict] = []
    for agent, root, tag in GROUPS:
        base = root / agent / "jobs"
        if not base.is_dir():
            continue
        for job in sorted(base.iterdir()):
            if not job.is_dir():
                continue
            meta = parse_job(job.name)
            if meta is None:
                continue
            task, rep = meta
            inner = trialdir.find_trial_dir(job)
            if inner is None:
                continue
            beh = from_sayacode_audit(inner) if agent == "sayacode" else from_atif(inner)
            if not beh:
                continue
            beh.update(usage_of(inner, agent))
            beh.update({"agent": agent, "tag": tag, "task": task, "repeat": rep})
            rows.append(beh)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    print("=" * 104)
    print("1. 行为量（每 trial 均值）")
    print("=" * 104)
    print(
        f"{'group':16}{'n':>4}{'工具调用':>10}{'探索':>8}{'编辑':>8}{'执行':>8}"
        f"{'工具错误':>10}{'模型调用':>10}{'输入token':>14}"
    )
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_group[f"{r['agent']} {r['tag']}"].append(r)
    for key, rs in by_group.items():
        tc = statistics.mean([r["tool_calls"] for r in rs])
        ex = statistics.mean([r["explore"] for r in rs])
        ed = statistics.mean([r["edit"] for r in rs])
        ec = statistics.mean([r["exec"] for r in rs])
        err = statistics.mean([r.get("tool_errors") or 0 for r in rs])
        mc = statistics.mean([r.get("model_calls") or r.get("steps") or 0 for r in rs])
        it = statistics.mean([r.get("input_tokens") or r.get("prompt_tokens") or 0 for r in rs])
        print(
            f"{key:16}{len(rs):>4}{tc:>10.1f}{ex:>8.1f}{ed:>8.1f}{ec:>8.1f}{err:>10.1f}{mc:>10.1f}{it:>14,.0f}"
        )

    print("\n" + "=" * 104)
    print("2. 工具类型分布（占该组全部调用）")
    print("=" * 104)
    for key, rs in by_group.items():
        agg: Counter[str] = Counter()
        for r in rs:
            agg.update(r.get("tools") or {})
        total = sum(agg.values()) or 1
        top = ", ".join(f"{k} {v / total * 100:.0f}%" for k, v in agg.most_common(5))
        print(f"{key:16} {top}")

    print("\n" + "=" * 104)
    print("3. 探索 : 编辑 : 执行 比例")
    print("=" * 104)
    for key, rs in by_group.items():
        e = sum(r["explore"] for r in rs) or 1
        d = sum(r["edit"] for r in rs) or 1
        c = sum(r["exec"] for r in rs) or 1
        print(f"{key:16} {e:>5} : {d:>4} : {c:>4}   (每编辑 {e / d:.1f} 次探索)")

    print("\n" + "=" * 104)
    print("4. 成本（仅 ATIF 基线有 cost_usd）")
    print("=" * 104)
    for key, rs in by_group.items():
        costs = [r["cost_usd"] for r in rs if r.get("cost_usd") is not None]
        if not costs:
            continue
        print(
            f"{key:16} n={len(costs):>3} 每 trial ${statistics.mean(costs):.4f} "
            f"总计 ${sum(costs):.2f} 中位 ${statistics.median(costs):.4f}"
        )


if __name__ == "__main__":
    main()
