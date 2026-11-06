"""题库体检器（v2）：区分「跨 agent 共性失败」与「单 agent 自身缺陷」。

判据：
  broken     同一测试在 >=2 个不同 agent 中各自稳定失败（>=2 次）→ 环境性不可过，排除
  agent_gap  仅某个 agent 稳定失败同一测试 → 该 agent 的缺陷，题目本身不排除
  saturated  所有观测部分得分≈1 → 无区分度
  dead       所有观测≈0
  flaky      max-min >= 0.30 且均值 > 0.9 → 只贡献噪声
  healthy    跨组 sd >= 0.03 且 0.05 < 均值 < 0.99
  weak       其余
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from sayacode_bench import trialdir

SATURATED = 0.995
DEAD = 0.005
MIN_OBS = 3


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


def collect(roots: list[Path]) -> dict[str, dict[str, list[set[str]]]]:
    """task -> agent -> [失败测试集合]。同一 (agent, task, repeat) 只记一次。"""
    out: dict[str, dict[str, list[set[str]]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str, int]] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for agent_dir in root.iterdir():
            if not agent_dir.is_dir():
                continue
            agent = agent_dir.name
            # 同一 trial 可能在 jobs/ 与 verify/jobs/ 各有一份产物，优先 jobs/
            for base in (agent_dir / "jobs", agent_dir / "verify" / "jobs"):
                if not base.is_dir():
                    continue
                for job in sorted(base.iterdir()):
                    meta = parse_job(job.name)
                    if meta is None:
                        continue
                    task, rep = meta
                    key = (agent, task, rep)
                    if key in seen:
                        continue
                    inner = trialdir.find_trial_dir(job)
                    if inner is None:
                        continue
                    f = inner / "verifier" / "output.json"
                    if not f.is_file():
                        continue
                    try:
                        tests = json.loads(f.read_text(encoding="utf-8")).get("tests") or []
                    except (OSError, ValueError):
                        continue
                    seen.add(key)
                    failed = {
                        str(t.get("name"))
                        for t in tests
                        if str(t.get("status", "")).upper() != "PASSED"
                    }
                    out[task][agent].append(failed)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=r"C:\sb\analysis\dataset.json")
    ap.add_argument("--roots", nargs="*", default=[r"C:\sb\hard\v2-325", r"C:\sb\hard\v4-327"])
    ap.add_argument("--out", default=r"C:\sb\analysis\health.md")
    args = ap.parse_args()

    rows = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    per_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("partial") is not None:
            per_task[r["task"]].append(r)

    fails = collect([Path(p) for p in args.roots])

    reports = []
    for task, rs in per_task.items():
        if len(rs) < MIN_OBS:
            continue
        vals = [r["partial"] for r in rs]
        mean, sd = statistics.mean(vals), statistics.pstdev(vals)
        pass01 = sum(1 for v in vals if v >= SATURATED) / len(vals)

        # 找该题的失败记录：必须精确匹配（同一 repo 的多题前 20 字符往往相同，不能用前缀）
        agents_fail: dict[str, list[set[str]]] = {}
        if task in fails:
            agents_fail = fails[task]
        else:
            for key, val in fails.items():
                if key == task or (len(key) >= 30 and key[:30] == task[:30]):
                    agents_fail = val
                    break

        # 每个测试在多少个 agent 中稳定出现（>=2 次）
        hit: dict[str, set[str]] = defaultdict(set)
        for agent, sets in agents_fail.items():
            cnt: dict[str, int] = defaultdict(int)
            for s in sets:
                for test in s:
                    cnt[test] += 1
            for test, c in cnt.items():
                if c >= 2:
                    hit[test].add(agent)

        chronic = [t for t, ags in hit.items() if len(ags) >= 2]
        single = {t: ags for t, ags in hit.items() if len(ags) == 1}

        if chronic:
            grade = "broken"
        elif mean >= SATURATED:
            grade = "saturated"
        elif mean <= DEAD:
            grade = "dead"
        elif (max(vals) - min(vals)) >= 0.30 and mean > 0.9:
            grade = "flaky"
        elif sd >= 0.03 and 0.05 < mean < 0.99:
            grade = "healthy"
        else:
            grade = "weak"

        reports.append(
            {
                "task": task,
                "n": len(rs),
                "mean": mean,
                "sd": sd,
                "pass01": pass01,
                "grade": grade,
                "chronic": chronic[:2],
                "single": dict(list(single.items())[:2]),
            }
        )

    order = {"broken": 0, "dead": 1, "saturated": 2, "flaky": 3, "weak": 4, "healthy": 5}
    reports.sort(key=lambda x: (order[x["grade"]], -x["sd"]))
    counts: dict[str, int] = defaultdict(int)
    for r in reports:
        counts[r["grade"]] += 1

    lines = [
        "# 题库体检报告",
        "",
        f"题数（观测≥{MIN_OBS}）: **{len(reports)}**",
        "",
        "| 评级 | 题数 | 含义 |",
        "|---|---:|---|",
        f"| broken | {counts['broken']} | **跨 ≥2 agent 稳定失败同一测试 → 环境性不可过，排除** |",
        f"| dead | {counts['dead']} | 全组≈0 |",
        f"| saturated | {counts['saturated']} | 全组≈满分，无区分度 |",
        f"| flaky | {counts['flaky']} | 重复间大幅翻转，只贡献噪声 |",
        f"| weak | {counts['weak']} | 有波动但无系统差异 |",
        f"| **healthy** | {counts['healthy']} | **有跨组差异，值得保留** |",
        "",
        "## 逐题明细",
        "",
        "| 评级 | 题 | n | 部分得分 | sd | 0/1 通过 | 跨 agent 共性失败测试 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for r in reports:
        sf = r["chronic"][0][:64] if r["chronic"] else ""
        lines.append(
            f"| {r['grade']} | `{r['task'][:44]}` | {r['n']} | {r['mean'] * 100:.1f}% | "
            f"{r['sd'] * 100:.1f} | {r['pass01'] * 100:.0f}% | {sf} |"
        )

    keep = [r for r in reports if r["grade"] == "healthy"]
    drop = [r for r in reports if r["grade"] in ("broken", "dead")]
    lines += [
        "",
        "## 建议",
        "",
        f"- **保留** {len(keep)} 题（healthy，sd≥0.03 且未饱和）",
        f"- **排除** {len(drop)} 题（broken/dead）",
        f"- **替换** {counts['saturated'] + counts['flaky'] + counts['weak']} 题（饱和/翻转/无差异）",
        "",
        "选区规则：优先 `sd` 大的题；不要用 0/1 通过率选题（会把 99% 的部分得分压成 0）。",
        "单 agent 的稳定失败（`agent_gap`）不算题目坏，属于该 agent 的缺陷，可用于诊断。",
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:13]))
    print(f"\n完整报告 → {out}")
    print(
        f"healthy={counts['healthy']} saturated={counts['saturated']} broken={counts['broken']} "
        f"flaky={counts['flaky']} weak={counts['weak']} dead={counts['dead']}"
    )


if __name__ == "__main__":
    main()
