"""Gold-patch 坏题筛查：用 Harbor OracleAgent 跑 task 自带 solution，验证参考解能否通过。

用法: python scripts/gold_patch_check.py --tasks-root <v2/tasks> --out <目录> [--concurrency 8]
判定：reward=1 好题；reward=0 坏题（参考解不通过）；异常=可疑。
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

from sayacode_bench.execution import run_official_trial  # noqa: E402

SAMPLE = ROOT / "studies" / "sample-40.json"
GATEWAY_V1 = "http://host.docker.internal:3425/v1"


def env_cfg() -> EnvironmentConfig:
    return EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={
            "messages_upstream": GATEWAY_V1 + "/messages",
            "chat_upstream": GATEWAY_V1 + "/chat/completions",
            "responses_upstream": GATEWAY_V1 + "/responses",
        },
    )


async def main_async(args: argparse.Namespace) -> int:
    import subprocess

    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False)

    spec = json.loads(SAMPLE.read_text(encoding="utf-8"))
    tasks = [t["task_id"] for t in spec["tasks"]]
    tasks_root = Path(args.tasks_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    agent = AgentConfig(name="oracle", model_name="oracle")
    sem = asyncio.Semaphore(max(1, args.concurrency))
    rows: list[dict] = []

    async def one(tid: str) -> None:
        async with sem:
            job = f"gold-{tid.replace('instance_', '')[:36]}"
            print(f"RUN {tid[:52]}", flush=True)
            try:
                rec = await run_official_trial(
                    tasks_root / tid, out / "jobs", job, agent, env_cfg(),
                    configuration="gold", repeat=1, canonical_model="oracle", endpoint="magpie",
                )
                reward, status = rec.get("original_reward"), rec.get("status")
            except Exception as exc:  # noqa: BLE001
                reward, status = None, f"exception:{type(exc).__name__}"
            rows.append({"task_id": tid, "reward": reward, "status": status})
            print(f"    -> {status} reward={reward}", flush=True)

    await asyncio.gather(*[one(t) for t in tasks])

    good = [r["task_id"] for r in rows if r["reward"] == 1.0]
    bad = [r["task_id"] for r in rows if r["reward"] == 0.0]
    susp = [r["task_id"] for r in rows if r["reward"] is None]
    summary = {"total": len(tasks), "good": len(good), "bad": len(bad), "suspicious": len(susp),
               "good_ids": good, "bad_ids": bad, "suspicious_ids": susp, "rows": rows}
    (out / "gold-report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== Gold patch 筛查 ===")
    print(f"  好题（reward=1）: {len(good)}")
    print(f"  坏题（reward=0）: {len(bad)}")
    print(f"  可疑（异常/无结果）: {len(susp)}")
    if bad:
        print("  坏题清单:")
        for t in bad:
            print(f"    - {t}")
    if susp:
        print("  可疑清单:")
        for t in susp:
            print(f"    - {t}")
    print(f"\n已写 {out / 'gold-report.json'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--concurrency", type=int, default=8)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
