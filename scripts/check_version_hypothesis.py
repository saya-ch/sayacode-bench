"""验证假设：SWE-EVO 版本演进题里，「没改 gold 中的版本文件」是否真的导致失败。"""

from __future__ import annotations

import json
import re
from pathlib import Path

RUN = Path(r"C:\sb\newset\runs\pilot1")
TASKS = Path(r"C:\sb\newset\swe-evo\tasks")
ACTUAL = RUN / "PREDICT-VS-ACTUAL.json"

VERSION_RE = re.compile(r"(^|/)(version[^/]*\.(py|txt|rb|ts|js)|__version__\.py|_version\.py)$", re.I)


def files_of(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        if line.startswith("+++ "):
            n = line[4:].strip()
            if n.startswith("b/"):
                n = n[2:]
            if n and n != "/dev/null":
                out.add(n)
    return out


def main() -> None:
    rows = json.loads(ACTUAL.read_text(encoding="utf-8"))
    print(f"{'trial':46}{'gold 有版本文件':>14}{'agent 改了':>12}{'reward':>8}{'假设':>8}")
    print("-" * 96)
    hits = []
    for r in rows:
        trial = r["trial"]
        stem = trial.replace("sayacode-", "").rsplit("-r", 1)[0].rstrip("-")
        td = next((d for d in TASKS.iterdir() if d.is_dir() and d.name.startswith(stem)), None)
        if td is None:
            continue
        gold = td / "solution" / "gold_patch.diff"
        gold_ver = {f for f in files_of(gold.read_text(encoding="utf-8", errors="replace")) if VERSION_RE.search(f)}
        job = RUN / "sayacode" / "jobs" / trial
        patch = next(job.rglob("model.patch"), None) if job.is_dir() else None
        agent_ver = {f for f in files_of(patch.read_text(encoding="utf-8", errors="replace")) if VERSION_RE.search(f)} if patch else set()

        reward = r.get("reward")
        touched = bool(agent_ver & gold_ver)
        # 假设：gold 有版本文件而 agent 没改 -> 应失败
        pred = None
        if gold_ver:
            pred = "FAIL" if not touched else "PASS"
        print(
            f"{trial[:44]:46}{len(gold_ver):>14}{len(agent_ver):>12}"
            f"{('-' if reward is None else f'{reward:.2f}'):>8}{('-' if pred is None else pred):>8}"
        )
        if gold_ver:
            hits.append({"trial": trial, "gold_ver": sorted(gold_ver), "agent_touched": touched,
                         "reward": reward, "predicted_fail": not touched})

    print("\n=== 假设检验（仅 gold 含版本文件的题）===")
    ok = sum(1 for h in hits if (not h["agent_touched"]) == (h["reward"] == 0.0))
    for h in hits:
        print(
            f"  {h['trial'][:44]:46} gold版本={h['gold_ver']}  agent碰了={h['agent_touched']}  "
            f"reward={h['reward']}  {'符合' if (not h['agent_touched']) == (h['reward'] == 0.0) else '不符'}"
        )
    print(f"\n符合假设: {ok}/{len(hits)}")

    out = RUN / "VERSION-HYPOTHESIS.json"
    out.write_text(json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
