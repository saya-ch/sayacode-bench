"""Definitive analysis for the pro-v2 four-agent comparison.

Caliber rules (these are the whole point -- earlier reports got them wrong)
--------------------------------------------------------------------------
1. **A trial that the verifier scored keeps its verdict.** ``verifier/reward.txt``
   is the ground truth, not ``normalized.json.status``: Harbor overwrites
   passing trials with ``infrastructure_error`` during job cleanup, so status
   alone produces false negatives.
2. **Only harness failures leave the denominator.** A trial counts as
   ``infrastructure`` only when the verifier produced *no* reward at all AND an
   exception came from the harness side. A trial that ran for 40 minutes and
   produced an empty patch is a *model* failure even though its status reads
   ``infrastructure_error``.
3. **Timeouts stay in the denominator.** Using up the time budget is a failure by
   the agent, not by us.
4. **Duplicates collapse to one record per (agent, task)**, preferring a record
   that actually carries a verdict.

Three denominators are reported because they answer different questions:
  * ``all``       -- denominator = every task (nothing excluded)
  * ``effective`` -- denominator excludes infrastructure only (the fair
                     capability comparison)
  * ``complete``  -- only tasks where all four agents ran successfully (rules out
                     any task that is unsolvable or broken in this environment)

Statistics: exact McNemar (two-sided binomial on discordant pairs) for each of
the six pairwise comparisons, Bonferroni over six comparisons, plus an explicit
power statement -- with 100 paired tasks "not significant" must not be read as
"no difference".
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

AGENTS = ["sayacode", "mini-swe", "claude-code", "opencode"]
AGENT_LABEL = {
    "sayacode": "sayacode 3.3.0",
    "mini-swe": "mini-swe-agent",
    "claude-code": "claude-code",
    "opencode": "opencode",
}


# --------------------------------------------------------------------------- #
# record discovery / normalization
# --------------------------------------------------------------------------- #
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def _verifier_reward(trial_dir: Path) -> float | None:
    """Read the verifier's own output; never trust our normalized status."""
    for rel in (("verifier", "reward.txt"), ("reward.txt",)):
        p = trial_dir.joinpath(*rel)
        if p.is_file():
            try:
                return float(p.read_text(encoding="utf-8", errors="replace").strip())
            except (OSError, ValueError):
                pass
    out = _read_json(trial_dir / "verifier" / "output.json")
    if isinstance(out, dict):
        for k in ("reward", "score"):
            v = out.get(k)
            if isinstance(v, int | float):
                return float(v)
    # Harbor also records it under verifier_result.rewards.{reward,score}
    rj = _read_json(trial_dir / "result.json")
    if isinstance(rj, dict):
        vr = rj.get("verifier_result")
        if isinstance(vr, dict):
            rewards = vr.get("rewards")
            if isinstance(rewards, dict):
                for k in ("reward", "score"):
                    v = rewards.get(k)
                    if isinstance(v, int | float):
                        return float(v)
            for k in ("reward", "score"):
                v = vr.get(k)
                if isinstance(v, int | float):
                    return float(v)
    return None


def _locate_trial_dir(job_dir: Path, rec: dict) -> Path:
    name = rec.get("trial_name")
    if name and (job_dir / name).is_dir():
        return job_dir / name
    cands = [
        p
        for p in job_dir.iterdir()
        if p.is_dir()
        and ((p / "verifier").is_dir() or (p / "result.json").is_file())
    ]
    if len(cands) == 1:
        return cands[0]
    if cands:
        # prefer the one that actually carries a reward
        for p in cands:
            if _verifier_reward(p) is not None:
                return p
        return cands[0]
    return job_dir


def collect(root: Path) -> dict[str, dict[str, dict]]:
    """-> {agent: {task_id: {...}}} with duplicates collapsed."""
    out: dict[str, dict[str, dict]] = {}
    for agent in AGENTS:
        base = root / agent
        rows: dict[str, list[dict]] = defaultdict(list)
        if not base.is_dir():
            out[agent] = {}
            continue
        for rec_path in base.rglob("normalized.json"):
            rec = _read_json(rec_path)
            if not isinstance(rec, dict):
                continue
            tid = rec.get("task_id")
            if not tid:
                continue
            job_dir = rec_path.parent
            trial_dir = _locate_trial_dir(job_dir, rec)
            reward = _verifier_reward(trial_dir)
            exc = rec.get("harbor_exception_type")
            rows[tid].append(
                {
                    "task_id": tid,
                    "agent": agent,
                    "reward": reward,
                    "status": rec.get("status"),
                    "exception": exc,
                    "duration": rec.get("duration_seconds"),
                    "job": job_dir.name,
                    "batch": job_dir.parent.name,
                    "trial_dir": str(trial_dir),
                    "input_tokens": rec.get("input_tokens"),
                    "output_tokens": rec.get("output_tokens"),
                    "terminal_error_types": rec.get("terminal_error_types") or [],
                    "model_calls": (rec.get("usage") or {}).get("model_calls"),
                }
            )

        picked: dict[str, dict] = {}
        for tid, cands in rows.items():
            # a record carrying a verifier verdict beats one that does not;
            # among equals prefer completed, then the longest run.
            best = max(
                cands,
                key=lambda r: (
                    r["reward"] is not None,
                    r["status"] == "completed",
                    r["duration"] or 0,
                ),
            )
            picked[tid] = best
        out[agent] = picked
    return out


def classify(row: dict) -> str:
    """ok / model / timeout / infrastructure -- reward first, status never decides
    between ok and failure.

    One important refinement over "reward is not None => model failure": a trial
    whose *model provider* died (APIStatusError / 502 / ECONNRESET) before the
    agent could do any real work is an infrastructure failure, not a capability
    signal. 2026-11-12 prov2-100x4: several sayacode trials ended after exactly
    2 model calls with ``WorkBuddy AI: ECONNRESET ... 502``, the worker exited 1,
    the verifier then scored the resulting empty patch as 0.0. Counting that as
    a model failure would charge the agent for the gateway being down.

    Guard rails so this cannot silently widen: require an explicit provider-side
    error type AND a tiny number of model calls (<= 3). A trial that ran for
    dozens of calls and then hit one 502 still counts as a model failure --
    that is the agent's run, with a transient error at the end.
    """
    if row["reward"] == 1.0:
        return "ok"
    exc = str(row.get("exception") or "")
    if "Timeout" in exc:
        return "timeout"

    provider_errs = {"APIStatusError", "APIConnectionError", "APIError",
                     "InternalServerError", "ServiceUnavailableError"}
    errs = set(row.get("terminal_error_types") or [])
    calls = row.get("model_calls")
    if errs & provider_errs and (calls is None or calls <= 3):
        return "infrastructure"

    if row["reward"] is not None:
        # verifier ran and scored it: a genuine agent failure
        return "model"
    if exc:
        return "infrastructure"
    return "infrastructure"


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test against p=0.5 (McNemar exact)."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / (2**n)
    return min(1.0, 2 * tail)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


def mde_paired(n_pairs: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Rough MDE for a paired proportion design (McNemar, two-sided).

    Uses the standard normal approximation for the discordance rate: with
    ~2*p*(1-p) discordant share, detectable difference is approximately
    (z_{a/2}+z_p) * sqrt(2*pi_d/n) where pi_d is the discordant proportion.
    Reported for pi_d = 0.25 as a conservative working figure.
    """
    z_a, z_b = 1.959964, 0.841621
    pi_d = 0.25
    return (z_a + z_b) * math.sqrt(pi_d / n_pairs)


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    data: dict[str, dict[str, dict]] = {a: {} for a in AGENTS}
    for root in args.root:
        got = collect(root)
        for a in AGENTS:
            data[a].update(got.get(a, {}))

    kinds = {a: {t: classify(r) for t, r in data[a].items()} for a in AGENTS}
    tasks = sorted(set().union(*[set(data[a]) for a in AGENTS]))

    L: list[str] = []
    L.append("# pro-v2 四 agent 对比结果\n")
    L.append(f"题目录来源：{'; '.join(str(r) for r in args.root)}\n")
    L.append(f"出现过的题数：{len(tasks)}；各 agent 覆盖率：")
    L.append("")
    L.append("| agent | 有记录题数 |")
    L.append("|---|---:|")
    for a in AGENTS:
        L.append(f"| {AGENT_LABEL[a]} | {len(data[a])} |")
    L.append("")

    # ---- per-agent 4-way counts ----
    L.append("## 每条 trial 的归类\n")
    L.append("| agent | 题数 | ok | model | timeout | infrastructure |")
    L.append("|---|---:|---:|---:|---:|---:|")
    counts: dict[str, Counter] = {}
    for a in AGENTS:
        c = Counter(kinds[a].values())
        counts[a] = c
        L.append(
            f"| {AGENT_LABEL[a]} | {len(kinds[a])} | {c['ok']} | {c['model']} | "
            f"{c['timeout']} | {c['infrastructure']} |"
        )
    L.append("")

    # ---- three denominators ----
    L.append("## 三种分母下的通过率\n")
    L.append("`all` 什么都不排除；`effective` 只排除 infrastructure；")
    L.append("`complete` 只用四家都成功跑完（无 infra/timeout）的题。\n")
    L.append("| agent | all | effective | complete-case |")
    L.append("|---|---:|---:|---:|")

    def rate_effective(a: str) -> tuple[float, int, int]:
        c = counts[a]
        denom = c["ok"] + c["model"] + c["timeout"]
        return (100.0 * c["ok"] / denom if denom else 0.0, c["ok"], denom)

    four_clean = [
        t
        for t in tasks
        if all(t in kinds[a] for a in AGENTS)
        and all(kinds[a][t] not in {"infrastructure", "timeout"} for a in AGENTS)
    ]
    for a in AGENTS:
        c = counts[a]
        n_all = len(kinds[a])
        eff, ok, den = rate_effective(a)
        n_pass_cc = sum(1 for t in four_clean if kinds[a].get(t) == "ok")
        cc = 100.0 * n_pass_cc / len(four_clean) if four_clean else 0.0
        L.append(
            f"| {AGENT_LABEL[a]} | {c['ok']}/{n_all} = "
            f"{100.0 * c['ok'] / n_all if n_all else 0:.1f}% | "
            f"{ok}/{den} = {eff:.2f}% | {n_pass_cc}/{len(four_clean)} = {cc:.1f}% |"
        )
    L.append("")
    L.append(f"complete-case 题数：{len(four_clean)}\n")

    # ---- pairwise McNemar ----
    L.append("## 两两配对检验（McNemar 精确二项，two-sided）\n")
    L.append("只用双方都有记录且都不是 infrastructure 的题；timeout 记为失败。\n")
    L.append("| A | B | 共同题 | A赢(仅A过) | B赢(仅B过) | 率差 | p | Bonferroni(0.0083) |")
    L.append("|---|---|---:|---:|---:|---:|---:|---|")
    pairs = [(AGENTS[i], AGENTS[j]) for i in range(len(AGENTS)) for j in range(i + 1, len(AGENTS))]
    results = []
    for a, b in pairs:
        shared = [
            t
            for t in tasks
            if t in kinds[a]
            and t in kinds[b]
            and kinds[a][t] != "infrastructure"
            and kinds[b][t] != "infrastructure"
        ]
        only_a = sum(1 for t in shared if kinds[a][t] == "ok" and kinds[b][t] != "ok")
        only_b = sum(1 for t in shared if kinds[b][t] == "ok" and kinds[a][t] != "ok")
        n = len(shared)
        pa = sum(1 for t in shared if kinds[a][t] == "ok") / n if n else 0.0
        pb = sum(1 for t in shared if kinds[b][t] == "ok") / n if n else 0.0
        p = binom_two_sided(min(only_a, only_b), only_a + only_b)
        sig = "**是**" if p < 0.0083 else "否"
        L.append(
            f"| {AGENT_LABEL[a]} | {AGENT_LABEL[b]} | {n} | {only_a} | {only_b} | "
            f"{100 * (pa - pb):+.1f}pp | {p:.4f} | {sig} |"
        )
        results.append((a, b, n, only_a, only_b, p, pa - pb))
    L.append("")

    # ---- power ----
    n_pairs = max((len(t) for t in [data[a] for a in AGENTS]), default=0)
    L.append("## 检验效能（必须和 p 值一起读）\n")
    L.append(
        f"配对题数约 {n_pairs}。配对设计中不一致率约 25% 时，双侧 α=0.05、"
        f"power=0.8 能检出的最小差异约 **{100 * mde_paired(n_pairs):.1f}pp**。"
    )
    L.append(
        "也就是说：**比这个更小的差异，本设计测不出来**；"
        "「p 值不显著」只能说明「没有证据表明有差异」，"
        "不能反过来说「两者一样好」。\n"
    )

    # ---- per-repo ----
    def repo_of(native: str) -> str:
        s = native
        if s.startswith("instance_"):
            s = s[9:]
        if "__" in s:
            s = s.split("__", 1)[1]
        return s.split("-", 1)[0]

    L.append("## 按 repo 拆分（有效分母：排除 infrastructure）\n")
    repos = sorted({repo_of(t) for t in tasks})
    L.append("| repo | " + " | ".join(AGENT_LABEL[a] for a in AGENTS) + " |")
    L.append("|---|" + "---:|" * len(AGENTS))
    for repo in repos:
        cells = []
        for a in AGENTS:
            ts = [t for t in data[a] if repo_of(t) == repo]
            ok = sum(1 for t in ts if kinds[a][t] == "ok")
            den = sum(1 for t in ts if kinds[a][t] in {"ok", "model", "timeout"})
            cells.append(f"{ok}/{den}" if den else "-")
        L.append(f"| {repo} | " + " | ".join(cells) + " |")
    L.append("")

    # ---- per-task matrix ----
    L.append("## 逐题矩阵\n")
    L.append("记法：`1`=通过，`0`=模型失败，`T`=超时，`I`=基础设施失败，`.`=无记录\n")
    L.append("| task | " + " | ".join(a for a in AGENTS) + " |")
    L.append("|---|" + "---|" * len(AGENTS))
    sym = {"ok": "1", "model": "0", "timeout": "T", "infrastructure": "I"}
    for t in tasks:
        cells = [sym.get(kinds[a].get(t), ".") for a in AGENTS]
        L.append(f"| `{t.split('__', 1)[-1][:38]}` | " + " | ".join(cells) + " |")
    L.append("")

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")

    # side-car machine readable
    payload = {
        "roots": [str(r) for r in args.root],
        "tasks": tasks,
        "kinds": kinds,
        "four_clean_tasks": four_clean,
        "pairwise": [
            {
                "a": a,
                "b": b,
                "shared": n,
                "only_a": oa,
                "only_b": ob,
                "p": p,
                "rate_diff_pp": 100 * rd,
            }
            for a, b, n, oa, ob, p, rd in results
        ],
    }
    (out.with_suffix(".json")).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n".join(L[:60]))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
