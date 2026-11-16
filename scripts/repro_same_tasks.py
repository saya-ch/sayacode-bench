"""同一批题重跑两次：逐题一致率、翻转率与净漂移。

为什么需要这个
--------------
本仓库此前把「flaky 13%–35%」写进每一份结论的边界里，但那个区间是从 `v2-325`
（另一套题、另一个代码版本）迁移来的**外部估计**，从未在本轮题集上直接测过。

`prov2-40x4`（2026-11-10~11）与 `prov2-100x4`（2026-11-11 起）覆盖同一套前 40 题
（`studies/large-sample-v1-pro-v2.json`），是两次独立执行。把两次结果逐题对齐，
就能就地量出「同一道题、同一个 agent、同一个验证器，换一次执行会怎样」。

翻转率就是 repeats=1 的噪声地板。它比「样本量不够」这种统计推断更直接：如果同一
道题重跑有四分之一的概率给出相反裁决，那么任何排名都只是这一次抽样。

归类复用 `analyze_ab.collect()` / `classify()`，不另写一套——`collect()` 读的是
`verifier/reward.txt`（真值）而非 `normalized.json` 字段，并按「有裁决 >
completed > 跑得久」去重。自己实现过一次，用错字段导致 mini-swe 算成 26/34
（权威口径 28/37），整张表会反向。

用法::

    python scripts/repro_same_tasks.py \\
        --run-a C:\\sb\\hard\\ab-ctx\\prov2-40x4 \\
        --run-b C:\\sb\\hard\\ab-ctx\\prov2-100x4 \\
        --study studies/large-sample-v1-pro-v2.json \\
        --out reproducibility.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_ab import AGENTS, AGENT_LABEL, classify, collect  # noqa: E402


def stem(task_id: str) -> str:
    """去掉 slice 里的 ``pro-v2/`` 前缀。

    slice 写的是 ``pro-v2/instance_xxx``，而 ``normalized.json`` 只记
    ``instance_xxx``。不归一化会匹配成 0/0。
    """
    return task_id.split("/", 1)[1] if "/" in task_id else task_id


def verdict(row: dict | None) -> bool | None:
    """True=通过，False=失败，None=不进入比较（infrastructure 或无记录）。"""
    if row is None:
        return None
    kind = classify(row)
    if kind == "infrastructure":
        return None
    return kind == "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-a", type=Path, required=True)
    ap.add_argument("--run-b", type=Path, required=True)
    ap.add_argument("--study", type=Path, required=True, help="两次跑批共同覆盖的题集")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    spec = json.loads(args.study.read_text(encoding="utf-8"))
    tasks = [stem(t["task_id"]) for t in spec["tasks"]]

    a = collect(args.run_a)
    b = collect(args.run_b)

    lines = [
        "# 同一批题重跑两次：一致率与翻转率（实测）",
        "",
        f"题集：`{args.study}`（{len(tasks)} 题）",
        "",
        f"- **跑批 A** = `{args.run_a}`",
        f"- **跑批 B** = `{args.run_b}`",
        "",
        "口径：复用 `scripts/analyze_ab.py` 的 `collect()` / `classify()`"
        "（`verifier/reward.txt` 优先；只排除 infrastructure；timeout 留在分母）。",
        "",
        "| agent | 可比题数 | 两次一致 | 一致率 | A通过→B失败 | A失败→B通过 | 翻转率 | 净漂移 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    rows = []
    for agent in AGENTS:
        agree = ok_a = ok_b = compar = flip_ab = flip_ba = 0
        for tid in tasks:
            va = verdict(a.get(agent, {}).get(tid))
            vb = verdict(b.get(agent, {}).get(tid))
            if va is None or vb is None:
                continue
            compar += 1
            ok_a += va
            ok_b += vb
            if va == vb:
                agree += 1
            elif va and not vb:
                flip_ab += 1
            else:
                flip_ba += 1
        flips = flip_ab + flip_ba
        agree_rate = agree / compar * 100 if compar else float("nan")
        flip_rate = flips / compar * 100 if compar else float("nan")
        drift = (ok_b - ok_a) / compar * 100 if compar else float("nan")
        rows.append((AGENT_LABEL[agent], compar, agree_rate, flip_rate, drift,
                     flip_ab, flip_ba))
        lines.append(
            f"| {AGENT_LABEL[agent]} | {compar} | {agree} | {agree_rate:.1f}% | "
            f"{flip_ab} | {flip_ba} | **{flip_rate:.1f}%** | {drift:+.2f}pp |"
        )

    valid = [r for r in rows if r[1]]
    if not valid:
        lines += ["", "**没有任何可比题，检查 --study 与两次跑批的输出目录。**"]

    if valid:
        worst = max(valid, key=lambda r: r[3])
        lines += [
            "",
            f"**翻转率最高 {worst[3]:.1f}%（{worst[0]}）。**",
            "",
            "## 怎么读",
            "",
            "翻转率就是 repeats=1 的噪声地板：同一道题、同一个 agent、同一个验证器，",
            "换一次执行就有这个概率给出相反裁决。它直接决定「排名」能不能成立——",
            "若翻转率与通过率之差同量级，名次就是抽样产物。",
            "",
            "## 各 agent 净漂移",
            "",
        ]
        for label, _compar, _agree_rate, _flip_rate, drift, _fa, _fb in rows:
            lines.append(f"- {label}：{drift:+.2f}pp")
        lines += [
            "",
            "漂移方向一致（同升或同降）说明有系统性成分；方向各异说明主要是抽样噪声。",
            "**不对称的翻转分布（例如某 agent 几乎只有 A→B 单向翻转）意味着存在尚未",
            "识别的系统性因素，跨轮次比较在解释清楚前应视为未受控。**",
        ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[6:]))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
