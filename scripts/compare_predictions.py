"""对照静态预测（patch 覆盖率 vs gold）与官方验证器的实际结果。

输入：
  C:\\sb\\newset\\pilot-predict.json       脚本 predict_pilot.py 产出的预测
  <run>/sayacode/verify/jobs/*/verifier/reward.txt  官方判定

输出：逐 trial 的 预测/实际 对照 + 混淆矩阵 + 准确率。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path(r"C:\sb\newset\runs\pilot1")
PRED = Path(r"C:\sb\newset\pilot-predict.json")


def find_reward(verify_root: Path, trial: str) -> float | None:
    """trial 名形如 sayacode-sweevo-xxx-r1；verify job 名是 verify-<同名>。"""
    for job in verify_root.iterdir() if verify_root.is_dir() else []:
        if not job.is_dir():
            continue
        if trial not in job.name and trial.replace("sayacode-", "") not in job.name:
            continue
        for f in job.rglob("reward.txt"):
            try:
                return float(f.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(RUN))
    ap.add_argument("--predictions", default=str(PRED))
    args = ap.parse_args()

    run = Path(args.run)
    preds = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    verify_root = run / "sayacode" / "verify" / "jobs"

    rows = []
    for p in preds:
        trial = p["trial"]
        reward = find_reward(verify_root, trial)
        pred_pass = str(p.get("predict", "")).startswith("PASS")
        actual = None if reward is None else reward >= 1.0
        rows.append({**p, "reward": reward, "actual": actual, "pred_pass": pred_pass})

    known = [r for r in rows if r["actual"] is not None]
    correct = sum(1 for r in known if r["pred_pass"] == r["actual"])

    print(f"{'trial':52}{'cov':>6}{'pred':>8}{'reward':>8}{'actual':>8}  ok")
    print("-" * 96)
    for r in rows:
        cov = f"{r['coverage'] * 100:.0f}%" if r.get("coverage") is not None else "-"
        act = "-" if r["actual"] is None else ("PASS" if r["actual"] else "FAIL")
        rew = "-" if r["reward"] is None else f"{r['reward']:.2f}"
        ok = "" if r["actual"] is None else ("✓" if r["pred_pass"] == r["actual"] else "✗")
        print(
            f"{r['trial'][:50]:52}{cov:>6}{'PASS' if r['pred_pass'] else 'FAIL':>8}{rew:>8}{act:>8}  {ok}"
        )

    tp = sum(1 for r in known if r["pred_pass"] and r["actual"])
    tn = sum(1 for r in known if not r["pred_pass"] and not r["actual"])
    fp = sum(1 for r in known if r["pred_pass"] and not r["actual"])
    fn = sum(1 for r in known if not r["pred_pass"] and r["actual"])

    print(f"\n有官方结果的 trial: {len(known)}/{len(rows)}")
    if known:
        print(f"混淆矩阵  TP={tp}  TN={tn}  FP={fp}  FN={fn}")
        print(f"准确率: {correct}/{len(known)} = {correct / len(known) * 100:.0f}%")
        print("\n注：样本极小（<=10），准确率只能当方向性参考，不能当结论。")

    out = run / "PREDICT-VS-ACTUAL.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
