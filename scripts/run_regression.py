"""L2 快速回归：跑 studies/regression-set.json 的题，判定「无回归」与「修复生效」。

用法：
  python scripts/run_regression.py --tasks-root <v2/tasks> --wheel <whl> \
      --requirements <requirements.txt> --profile <profile.json> --variant <variant.json> \
      --out <输出目录> [--repeats 1]

说明：仅作开发期快速回归（见 docs/ITERATION-WORKFLOW.md），不产生正式成绩。
镜像需预先存在于本地（可用 ghcr.nju.edu.cn 镜像源预热）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor.models.trial.config import AgentConfig, EnvironmentConfig  # noqa: E402

from sayacode_bench.connections import messages_endpoint  # noqa: E402
from sayacode_bench.execution import CANONICAL_MODEL, run_official_trial  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_summary import summary_text  # noqa: E402

SET = ROOT / "studies" / "regression-set.json"


def build_agent(args: argparse.Namespace, work: Path) -> tuple[AgentConfig, EnvironmentConfig]:
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    upstream = messages_endpoint(profile["base_url"])
    profile["base_url"] = "http://saya-model-gateway:8080"
    private = work / "profile-private.json"
    private.write_text(json.dumps(profile), encoding="utf-8")
    agent = AgentConfig(
        import_path="sayacode_bench.adapter:SayacodeAgent",
        model_name=CANONICAL_MODEL,
        extra_allowed_hosts=["saya-model-gateway"],
        kwargs={
            "product_wheel": str(Path(args.wheel).resolve(strict=True)),
            "requirements_path": str(Path(args.requirements).resolve(strict=True)),
            "profile_path": str(private),
            "variant_path": str(Path(args.variant).resolve(strict=True)),
        },
    )
    env = EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": upstream},
    )
    return agent, env


async def main_async(args: argparse.Namespace) -> int:
    spec = json.loads(SET.read_text(encoding="utf-8"))
    print(summary_text(args.profile), flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agent, env = build_agent(args, out)
    tasks_root = Path(args.tasks_root)
    rows = []

    for item in spec["tasks"]:
        task_id = item["task_id"]
        expect = item["expect"]
        for repeat in range(1, args.repeats + 1):
            job = f"reg-{task_id.replace('instance_', '')[:36]}-r{repeat}"
            print(f"RUN {expect:4} {task_id[:40]} r{repeat}", flush=True)
            try:
                rec = await run_official_trial(
                    tasks_root / task_id, out / "jobs", job, agent, env,
                    configuration="regression", repeat=repeat, endpoint="magpie",
                )
                reward = rec.get("original_reward")
                status = rec.get("status")
            except Exception as exc:  # noqa: BLE001
                reward, status = None, f"exception:{type(exc).__name__}"
            rows.append({"task_id": task_id, "expect": expect, "repeat": repeat,
                         "reward": reward, "status": status})
            print(f"    -> {status} reward={reward}", flush=True)

    # 判定：优先使用「该模型自己的基线」，否则用 regression-set 的期望但只作参考
    ok = 0
    breaks = []
    fixed = []
    baseline_path = ROOT / "studies" / f"regression-baseline-{args.model_label}.json"
    judged = baseline_path.is_file()
    if judged:
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        expect_map = {t["task_id"]: ("pass" if t["reward"] == 1.0 else "fail") for t in base["tasks"]}
    else:
        expect_map = {item["task_id"]: item["expect"] for item in spec["tasks"]}
    for item in spec["tasks"]:
        tid = item["task_id"]
        got = [r["reward"] for r in rows if r["task_id"] == tid and r["reward"] is not None]
        passed = bool(got) and max(got) == 1.0
        expect = expect_map.get(tid)
        if expect == "pass" and not passed:
            breaks.append(tid)
        if expect == "fail" and passed:
            fixed.append(tid)
        if got:
            ok += 1

    report = {"summary": {"runs": len(rows), "with_reward": ok,
                          "baseline_model": args.model_label, "baseline_used": judged,
                          "regressions": breaks, "fixes": fixed},
              "rows": rows}
    (out / "regression-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== 回归判定 ===")
    print(f"  有效运行 {ok}/{len(rows)}")
    print(f"  回归破坏（原 PASS 现非 PASS）: {breaks or '无'}")
    print(f"  修复生效（原 FAIL 现 PASS）: {fixed or '无'}")
    print(f"  基线: {args.model_label} ({'已用该模型基线' if judged else '无该模型基线，判定仅供参考'})")
    print(f"  结论: {'Go（无回归）' if not breaks else 'No-Go（有回归，回退）'}")
    return 0 if not breaks else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks-root", required=True)
    p.add_argument("--wheel", required=True)
    p.add_argument("--requirements", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--model-label", default="deepseek-v4.1-flash", help="用于匹配 studies/regression-baseline-<label>.json")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
