"""分析同一题 r1/r2 的失败测试集合是否一致。

分类：
  stable_pass   两次都全过
  stable_fail   两次都失败，且失败测试集合相同（系统性问题：题目 bug 或 agent 硬缺陷）
  flip          一次全过一次失败（真随机）
  unstable_fail 两次都失败但集合不同（测试不稳定）
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from sayacode_bench import trialdir

ROOTS = {
    "SAYACODE 3.2.7": (Path(r"C:\sb\hard\v4-327"), "sayacode"),
    "SAYACODE 3.2.5": (Path(r"C:\sb\hard\v2-325"), "sayacode"),
    "mini-swe": (Path(r"C:\sb\hard\v2-325"), "mini-swe"),
    "Claude Code": (Path(r"C:\sb\hard\v2-325"), "claude-code"),
    "OpenCode": (Path(r"C:\sb\hard\v2-325"), "opencode"),
}


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


def collect(root: Path, agent: str) -> dict[str, dict[int, set[str] | None]]:
    """task -> repeat -> 失败测试集合（None 表示全部通过/无数据）。"""
    out: dict[str, dict[int, set[str] | None]] = defaultdict(dict)
    for base in (root / agent / "jobs", root / agent / "verify" / "jobs"):
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
            f = inner / "verifier" / "output.json"
            if not f.is_file():
                continue
            try:
                tests = json.loads(f.read_text(encoding="utf-8")).get("tests") or []
            except (OSError, ValueError):
                continue
            failed = {
                str(t.get("name")) for t in tests if str(t.get("status", "")).upper() != "PASSED"
            }
            if task in out and rep in out[task]:
                continue
            out[task][rep] = failed
    return out


def main() -> None:
    print("=" * 100)
    print("同题 r1/r2 失败测试集合一致性（每组）")
    print("=" * 100)
    print(
        f"{'group':16}{'配对题':>8}{'稳定通过':>10}{'稳定失败(同集合)':>18}{'随机翻转':>10}{'不稳定失败':>12}"
    )
    details: list[tuple[str, str, str, set[str]]] = []
    for label, (root, agent) in ROOTS.items():
        data = collect(root, agent)
        n = sp = sf = fl = uf = 0
        for task, reps in data.items():
            if 1 not in reps or 2 not in reps:
                continue
            a, b = reps[1], reps[2]
            if a is None or b is None:
                continue
            n += 1
            a_ok, b_ok = not a, not b
            if a_ok and b_ok:
                sp += 1
            elif a_ok != b_ok:
                fl += 1
                details.append((label, task, "flip", (a if a_ok else b)))
            elif a == b:
                sf += 1
                details.append((label, task, "stable_fail", a))
            else:
                uf += 1
        print(f"{label:16}{n:>8}{sp:>10}{sf:>18}{fl:>10}{uf:>12}")

    print("\n稳定失败（两次都挂同一个测试）的题——最可能是题目/判据问题：")
    seen = set()
    for label, task, kind, fails in details:
        if kind != "stable_fail":
            continue
        key = (label, task)
        if key in seen:
            continue
        seen.add(key)
        short = sorted(fails)[:2]
        print(f"  [{label:14}] {task:36} 失败 {len(fails)} 个测试，例: {short}")


if __name__ == "__main__":
    main()
