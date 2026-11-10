"""pro-v2 四 agent 对比分析（区分基础设施失败与模型失败）。

关键问题：sayacode 需要 pip install 产品 wheel，其他三个 agent 不需要。
安装环节的失败（pyc 损坏、网络、依赖冲突）会记成 reward=0，
但那是**基础设施失败**，不是模型没做对。

直接算通过率会系统性低估 sayacode。本脚本分开报：
  * 原始通过率 = 通过 / 全部 trial（含基础设施失败，和之前的口径一致）
  * 有效通过率 = 通过 / (全部 trial - 基础设施失败)

基础设施失败的判定：
  * exception_type in {NonZeroAgentExitCodeError, RuntimeError} 且
    trial.log 或 exception 里出现安装相关字样（imports 检查 / install / venv / uv pip）
  * exception_type == AgentTimeoutError → 单独算 timeout（模型太慢，算失败但标注）

用法：
    python analyze_prov2_4agents_v2.py <结果目录>
"""

from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
from collections import Counter
from itertools import combinations
from math import comb

TASKS = pathlib.Path(
    r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-"
    r"66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
)
AGENTS = ["sayacode", "mini-swe", "claude-code", "opencode"]
INSTALL_HINTS = ("imports 检查失败", "install", "venv", "uv pip", "pycache", "bad marshal")


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2**n))


def classify(rec: dict, job_dir: pathlib.Path, reward: float | None) -> str:
    """返回 ok / model / infrastructure / timeout。

    completed 不等于成功：completed + reward=0 是**模型做错了**，
    必须单独算 model，否则「模型失败」永远是 0。
    """
    status = rec.get("status")
    if status == "completed":
        return "ok" if reward == 1.0 else "model"
    etype = rec.get("harbor_exception_type") or ""
    if etype == "AgentTimeoutError":
        return "timeout"
    # 找安装痕迹
    blob = ""
    for name in ("trial.log", "job.log", "install.log"):
        for p in job_dir.rglob(name):
            try:
                blob += p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    for p in job_dir.rglob("exception-detail.txt"):
        try:
            blob += p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    low = blob.lower()
    if etype in {"NonZeroAgentExitCodeError", "RuntimeError", "FileNotFoundError"} and any(
        h.lower() in low for h in INSTALL_HINTS
    ):
        return "infrastructure"
    if status in {"infrastructure_error"}:
        # 判不出具体类别，保守归为基础设施（宁可少算模型失败）
        return "infrastructure"
    return "model"


def load_agent(root: pathlib.Path, agent: str) -> dict[str, dict]:
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
        reward = rec.get("original_reward")
        rfile = next(job_dir.rglob("verifier/reward.txt"), None)
        if rfile is not None:
            try:
                reward = float(rfile.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pass
        f2p_rate = None
        outj = next(job_dir.rglob("verifier/output.json"), None)
        cfg = TASKS / tid / "tests" / "config.json"
        if outj is not None and cfg.is_file():
            try:
                got = {
                    t["name"]: t["status"]
                    for t in json.loads(outj.read_text(encoding="utf-8")).get("tests") or []
                }
                c = json.loads(cfg.read_text(encoding="utf-8"))
                f2p = _as_list(c.get("fail_to_pass"))
                if f2p and len(got) >= max(1, len(f2p) // 2):
                    f2p_rate = sum(1 for n in f2p if got.get(n) == "PASSED") / len(f2p)
            except (OSError, ValueError):
                pass
        out[tid] = {
            "reward": reward,
            "status": rec.get("status"),
            "etype": rec.get("harbor_exception_type"),
            "duration": rec.get("duration_seconds"),
            "f2p_rate": f2p_rate,
            "passed": reward == 1.0,
            "kind": classify(rec, job_dir, reward),
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
    data = {a: d for a in AGENTS if (d := load_agent(root, a))}

    print("=" * 100)
    print(f"结果目录：{root}")
    print("=" * 100)

    print()
    print("【1】通过率（区分失败类型）")
    print(
        f"  {'agent':<14}{'trial':>6}{'通过':>6}{'原始':>9}{'基础设施':>9}{'超时':>6}"
        f"{'模型失败':>9}{'有效':>9}{'有效通过率':>12}"
    )
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        n = len(d)
        kinds = Counter(v["kind"] for v in d.values())
        p = sum(1 for v in d.values() if v["passed"])
        infra = kinds.get("infrastructure", 0)
        timeout = kinds.get("timeout", 0)
        model_fail = kinds.get("model", 0)
        # 有效分母：排除基础设施失败（超时算模型太慢，保留在分母里）
        eff = n - infra
        eff_rate = p / eff * 100 if eff else 0
        print(
            f"  {a:<14}{n:>6}{p:>6}{p/n*100:>8.1f}%{infra:>9}{timeout:>6}"
            f"{model_fail:>9}{eff:>9}{eff_rate:>11.1f}%"
        )

    common = set.intersection(*(set(d) for d in data.values())) if data else set()
    print()
    print(f"【2】共同题集配对（{len(common)} 题四组都有）")
    if len(common) < 2:
        print("  样本不足")
    else:
        print(f"  {'对比':<32}{'A独赢':>7}{'B独赢':>7}{'Δ':>9}{'p':>9}")
        for a, b in combinations([x for x in AGENTS if x in data], 2):
            da, db = data[a], data[b]
            only_a = sum(1 for t in common if da[t]["passed"] and not db[t]["passed"])
            only_b = sum(1 for t in common if db[t]["passed"] and not da[t]["passed"])
            delta = (only_a - only_b) / len(common) * 100
            p = mcnemar_exact(only_a, only_b)
            print(
                f"  {a} vs {b:<14}{only_a:>7}{only_b:>7}{delta:>+8.1f}pp{p:>9.4f}"
            )

    print()
    print("【3】F2P 测试级通过率")
    print(f"  {'agent':<14}{'可算题数':>9}{'F2P 均值':>12}")
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        rates = [v["f2p_rate"] for v in d.values() if v["f2p_rate"] is not None]
        if rates:
            print(f"  {a:<14}{len(rates):>9}{statistics.mean(rates)*100:>11.2f}%")

    print()
    print("【4】失败明细（只列非 ok 的）")
    for a in AGENTS:
        d = data.get(a)
        if not d:
            continue
        for tid, v in sorted(d.items()):
            if v["kind"] == "ok":
                continue
            print(f"  [{a}] {tid[:52]:<54} {v['kind']:<14} {v['etype'] or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
