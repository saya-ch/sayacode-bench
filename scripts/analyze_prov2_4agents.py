"""pro-v2 四 agent 对比分析：通过率 + 配对 McNemar + F2P 测试级 + 逐题输赢。

用法：
    python analyze_prov2_4agents.py <结果目录>
    python analyze_prov2_4agents.py C:\\sb\\hard\\ab-ctx\\prov2-40x4
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import statistics
from collections import Counter
from itertools import combinations
from math import comb

TASKS = pathlib.Path(
    r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-"
    r"66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
)
AGENTS = ["sayacode", "mini-swe", "claude-code", "opencode"]


def mcnemar_exact(b: int, c: int) -> float:
    """双侧精确 McNemar。b/c 是两种不一致配对的计数。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2**n))


def norm_task(tid: str) -> str:
    return tid[:-2] if tid.endswith("-v") else tid


def repo_of(tid: str) -> str:
    return tid.split("__")[1].split("-")[0] if "__" in tid else "?"


def load_agent(root: pathlib.Path, agent: str) -> dict[str, dict]:
    """{task_id: {reward, status, duration, f2p_rate, ...}}"""
    out: dict[str, dict] = {}
    base = root / agent
    if not base.is_dir():
        return out
    for norm in base.rglob("normalized.json"):
        try:
            rec = json.loads(norm.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tid = rec.get("task_id")
        if not tid:
            continue
        job_dir = pathlib.Path(rec.get("job_dir") or norm.parent)
        # reward：优先 reward.txt
        reward = rec.get("original_reward")
        rfile = next(job_dir.rglob("verifier/reward.txt"), None)
        if rfile is not None:
            try:
                reward = float(rfile.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pass
        # F2P 测试级
        f2p_rate = f2p_n = None
        outj = next(job_dir.rglob("verifier/output.json"), None)
        cfg = TASKS / tid / "tests" / "config.json"
        if outj is not None and cfg.is_file():
            try:
                got = {t["name"]: t["status"] for t in json.loads(outj.read_text(encoding="utf-8")).get("tests") or []}
                c = json.loads(cfg.read_text(encoding="utf-8"))
                f2p = _as_list(c.get("fail_to_pass"))
                if f2p and len(got) >= max(1, len(f2p) // 2):
                    f2p_n = len(f2p)
                    f2p_rate = sum(1 for n in f2p if got.get(n) == "PASSED") / len(f2p)
            except (OSError, ValueError):
                pass
        out[tid] = {
            "reward": reward,
            "status": rec.get("status"),
            "duration": rec.get("duration_seconds"),
            "f2p_rate": f2p_rate,
            "f2p_n": f2p_n,
            "passed": reward == 1.0,
        }
    return out


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value.replace("'", '"'))
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return re.findall(r'"([^"]+)"', value) or re.findall(r"'([^']+)'", value)
    return []


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\sb\hard\ab-ctx\prov2-40x4")
    data = {a: load_agent(root, a) for a in AGENTS}
    data = {a: d for a, d in data.items() if d}

    print("=" * 96)
    print(f"结果目录：{root}")
    print("=" * 96)

    # 1. 总体
    print()
    print("【1】总体通过率")
    print(f"  {'agent':<16}{'trial':>7}{'通过':>7}{'通过率':>10}{'中位耗时':>10}{'异常':>7}")
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        n = len(d)
        p = sum(1 for v in d.values() if v["passed"])
        dur = [v["duration"] / 60 for v in d.values() if v["duration"]]
        bad = sum(1 for v in d.values() if v["status"] in {"infrastructure_error", "timeout", "cancelled"})
        print(f"  {a:<16}{n:>7}{p:>7}{p/n*100:>9.1f}%{(statistics.median(dur) if dur else 0):>10.1f}{bad:>7}")

    # 2. 共同题集上的配对比较
    common = set.intersection(*(set(d) for d in data.values())) if data else set()
    print()
    print(f"【2】共同题集配对比较（{len(common)} 题四组都有）")
    if len(common) < 2:
        print("  样本不足")
    else:
        print(f"  {'对比':<34}{'A独赢':>7}{'B独赢':>7}{'Δ':>9}{'McNemar p':>12}")
        for a, b in combinations([x for x in AGENTS if x in data], 2):
            da, db = data[a], data[b]
            only_a = sum(1 for t in common if da[t]["passed"] and not db[t]["passed"])
            only_b = sum(1 for t in common if db[t]["passed"] and not da[t]["passed"])
            delta = (only_a - only_b) / len(common) * 100
            p = mcnemar_exact(only_a, only_b)
            mark = " *" if p < 0.05 else ""
            print(f"  {a} vs {b:<18}{only_a:>7}{only_b:>7}{delta:>+8.1f}pp{p:>12.4f}{mark}")

    # 3. F2P 测试级
    print()
    print("【3】F2P 测试级通过率（更细的粒度，不受整体 0/1 影响）")
    print(f"  {'agent':<16}{'可算题数':>9}{'F2P 均值':>12}")
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        rates = [v["f2p_rate"] for v in d.values() if v["f2p_rate"] is not None]
        if rates:
            print(f"  {a:<16}{len(rates):>9}{statistics.mean(rates)*100:>11.2f}%")
        else:
            print(f"  {a:<16}{0:>9}{'—':>12}")

    # 4. 逐题输赢
    if common:
        print()
        print("【4】逐题明细（列出不是四组全通过/全失败的）")
        print(f"  {'task':<50}" + "".join(f"{a[:6]:>8}" for a in AGENTS))
        for t in sorted(common):
            flags = [data[a][t]["passed"] for a in AGENTS if a in data]
            if all(flags) or not any(flags):
                continue
            row = "".join(f"{'✓' if data[a][t]['passed'] else '✗':>8}" for a in AGENTS if a in data)
            print(f"  {t[:48]:<50}{row}")

    # 5. 异常统计
    print()
    print("【5】异常状态分布")
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        c = Counter(v["status"] for v in d.values())
        print(f"  {a:<16} {dict(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
