"""阶段 2：统一验证。对阶段 1 产出的 patch 用 PatchReplayAgent 在干净沙箱重放验证。

用法: python scripts/verify_patches.py --out C:\sb\hard\formal-240 --agents sayacode mini-swe codex [--concurrency 4]
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path(r"C:\develop\sayacode-bench")
TOOLING = Path(r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tooling")
TASKS = Path(r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks")

sys.path.insert(0, str(BENCH / "src"))
sys.path.insert(0, str(TOOLING))

from harbor.models.trial.config import AgentConfig, EnvironmentConfig  # noqa: E402

from sayacode_bench.execution import run_official_trial  # noqa: E402

GATEWAY_V1 = "http://host.docker.internal:3425/v1"


def env_cfg() -> EnvironmentConfig:
    return EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": GATEWAY_V1 + "/messages",
                "chat_upstream": GATEWAY_V1 + "/chat/completions",
                "responses_upstream": GATEWAY_V1 + "/responses"},
    )


async def main_async(args) -> int:
    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False)
    out_root = Path(args.out)
    sem = asyncio.Semaphore(max(1, args.concurrency))
    total = 0

    for name in args.agents:
        jobs = out_root / name / "jobs"
        if not jobs.is_dir():
            print(f"[{name}] 无 jobs", flush=True)
            continue
        # 阶段 1 的 trial（无 reward.txt 但有 model.patch）
        pending = []
        for job in jobs.iterdir():
            if not job.is_dir():
                continue
            inner = next((d for d in job.iterdir() if d.is_dir() and d.name.startswith("instance_")), None)
            if inner is None:
                continue
            patch = inner / "agent" / "model.patch"
            reward = inner / "verifier" / "reward.txt"
            if patch.is_file() and not reward.is_file():
                task = None
                rj = inner / "result.json"
                if rj.is_file():
                    try:
                        task = (json.loads(rj.read_text(encoding="utf-8")).get("task_name") or "").split("/")[-1]
                    except Exception:
                        pass
                if task:
                    pending.append((job.name, task, patch.stat().st_size))

        print(f"[{name}] 待验证 {len(pending)} 个", flush=True)
        verify_dir = out_root / name / "verify"

        async def one(job_name: str, task: str, patch_bytes: int):
            async with sem:
                if patch_bytes == 0:
                    print(f"[{name}] {task[:40]} 空 patch，跳过", flush=True)
                    return
                vjob = f"verify-{job_name}"
                print(f"[{name}] VERIFY {task[:44]}", flush=True)
                try:
                    rec = await run_official_trial(
                        TASKS / task, verify_dir / "jobs", vjob,
                        AgentConfig(import_path="patch_replay:PatchReplayAgent", model_name="replay",
                                    kwargs={"source_job": str(jobs / job_name)}),
                        env_cfg(), configuration="verify", repeat=1, canonical_model="replay", endpoint="magpie",
                    )
                    print(f"[{name}]   -> {rec.get('status')} reward={rec.get('original_reward')}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[{name}]   -> exception {type(exc).__name__}: {str(exc)[:100]}", flush=True)

        await asyncio.gather(*[one(j, t, b) for j, t, b in pending])
        total += len(pending)

    print(f"阶段2 完成，共验证 {total}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--agents", nargs="+", default=["sayacode", "mini-swe", "codex"])
    p.add_argument("--concurrency", type=int, default=4)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
